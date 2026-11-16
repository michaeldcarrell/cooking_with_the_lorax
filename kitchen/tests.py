import io
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from kitchen import importer
from kitchen.models import (
    AllowedUser, Contact, DishPhoto, Household, HouseholdPreference, Ingredient, Inquiry, Menu, MenuFeedback,
    MenuItem, PreferenceCategory, PreferenceOption, Recipe, Service, ShoppingItem, SiteSettings, Step,
)
from kitchen.quantities import format_amount, normalize_name, normalize_unit, parse_amount
from kitchen.services import rebuild_shopping_list


def jpeg_upload(name='dish.jpg', size=(40, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 120, 60)).save(buf, 'JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


class QuantityTests(TestCase):
    def test_parse(self):
        self.assertEqual(parse_amount('1 1/2'), (Decimal('1.500'), None))
        self.assertEqual(parse_amount('1½'), (Decimal('1.500'), None))
        self.assertEqual(parse_amount('¾'), (Decimal('0.750'), None))
        self.assertEqual(parse_amount('2-3'), (Decimal('2.000'), Decimal('3.000')))
        self.assertEqual(parse_amount('2 to 3'), (Decimal('2.000'), Decimal('3.000')))
        self.assertEqual(parse_amount(''), (None, None))
        with self.assertRaises(ValueError):
            parse_amount('a pinch')

    def test_format(self):
        self.assertEqual(format_amount(Decimal('1.5')), '1 ½')
        self.assertEqual(format_amount(Decimal('0.333')), '⅓')
        self.assertEqual(format_amount(Decimal('2')), '2')
        self.assertEqual(format_amount(Decimal('0.99')), '1')
        self.assertEqual(format_amount(Decimal('37.5')), '38')
        self.assertEqual(format_amount(Decimal('0.01')), '⅛')

    def test_normalize(self):
        self.assertEqual(normalize_unit('Tablespoons'), 'tbsp')
        self.assertEqual(normalize_unit('T'), 'tbsp')
        self.assertEqual(normalize_unit('t'), 'tsp')
        self.assertEqual(normalize_name('Yellow Onions'), 'yellow onion')
        self.assertEqual(normalize_name('tomatoes'), 'tomato')
        self.assertEqual(normalize_name('hummus'), 'hummus')


class SignedInTestCase(TestCase):
    """Signed in as Lori (seeded admin)."""

    def setUp(self):
        self.user = User.objects.create_user('lori', 'lweischedel@gmail.com', first_name='Lori')
        self.client.force_login(self.user)


class AccessTests(TestCase):
    def test_seeded_admins(self):
        self.assertEqual(set(AllowedUser.objects.filter(is_admin=True).values_list('email', flat=True)),
                         {'lweischedel@gmail.com', 'lori@loraxglobal.com', 'michael@carrell.us'})
        self.assertTrue(PreferenceCategory.objects.filter(name='Allergies').exists())

    def test_anonymous_redirected_to_sign_in(self):
        response = self.client.get(reverse('recipes'))
        self.assertRedirects(response, reverse('welcome'))
        self.assertEqual(self.client.get(reverse('welcome')).status_code, 200)

    def test_user_not_on_allow_list_is_signed_out(self):
        stranger = User.objects.create_user('x', 'stranger@example.com')
        self.client.force_login(stranger)
        self.assertRedirects(self.client.get(reverse('home')), reverse('welcome'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_non_admin_cannot_open_admin_page(self):
        AllowedUser.objects.create(email='helper@example.com', is_admin=False)
        self.client.force_login(User.objects.create_user('h', 'helper@example.com'))
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)
        self.assertRedirects(self.client.get(reverse('manage')), reverse('home'))

    def test_admin_flags_synced(self):
        from kitchen.adapter import sync_admin_flags
        user = User.objects.create_user('m', 'michael@carrell.us')
        sync_admin_flags(user, AllowedUser.objects.get(email='michael@carrell.us'))
        user.refresh_from_db()
        self.assertTrue(user.is_superuser and user.is_staff)


class HouseholdTests(SignedInTestCase):
    def test_create_and_view(self):
        response = self.client.post(reverse('households'), {'name': 'The Smiths', 'default_servings': 4})
        household = Household.objects.get(name='The Smiths')
        self.assertRedirects(response, household.get_absolute_url())
        self.assertContains(self.client.get(household.get_absolute_url()), 'The Smiths')

    def test_contacts_notes_preferences(self):
        household = Household.objects.create(name='Smiths')
        self.client.post(reverse('contact_add', args=[household.pk]),
                         {'name': 'Ann', 'email': 'ann@example.com', 'receives_menus': 'on'})
        self.client.post(reverse('note_add', args=[household.pk]), {'body': 'Gate code 1234', 'pinned': 'on'})
        peanuts = PreferenceOption.objects.get(name='Peanuts')
        italian = PreferenceOption.objects.get(name='Italian')
        self.client.post(reverse('household_preferences', args=[household.pk]), {
            f'opt-{peanuts.pk}': 'allergy', f'opt-{italian.pk}': 'love', 'preference_notes': 'No raw tomatoes'})
        self.assertEqual(household.contacts.get().email, 'ann@example.com')
        self.assertTrue(household.notes.get().pinned)
        self.assertEqual(HouseholdPreference.objects.get(household=household, option=peanuts).stance, 'allergy')
        page = self.client.get(household.get_absolute_url())
        self.assertContains(page, 'Peanuts')
        self.assertContains(page, 'Gate code 1234')
        # Clearing a stance removes it.
        self.client.post(reverse('household_preferences', args=[household.pk]), {
            f'opt-{peanuts.pk}': '', f'opt-{italian.pk}': 'love'})
        self.assertFalse(HouseholdPreference.objects.filter(household=household, option=peanuts).exists())

    def test_delete_needs_name(self):
        household = Household.objects.create(name='Smiths')
        self.client.post(reverse('household_delete', args=[household.pk]), {'confirm': 'nope'})
        self.assertTrue(Household.objects.filter(pk=household.pk).exists())
        self.client.post(reverse('household_delete', args=[household.pk]), {'confirm': 'Smiths'})
        self.assertFalse(Household.objects.filter(pk=household.pk).exists())


def make_recipe(title='Chili', servings=4, ingredients=()):
    recipe = Recipe.objects.create(title=title, servings=servings, description=f'A lovely {title}.')
    for i, (qty, unit, name, section) in enumerate(ingredients):
        low, high = parse_amount(qty)
        Ingredient.objects.create(recipe=recipe, order=i, quantity=low, quantity_max=high, unit=unit, name=name,
                                  section=section)
    return recipe


class RecipeTests(SignedInTestCase):
    def test_manual_create_and_edit(self):
        response = self.client.post(reverse('recipe_new'), {'mode': 'manual', 'title': 'Soup'})
        recipe = Recipe.objects.get(title='Soup')
        self.assertRedirects(response, reverse('recipe_edit', args=[recipe.pk]))
        response = self.client.post(reverse('recipe_edit', args=[recipe.pk]), {
            'title': 'Tomato soup', 'servings': 4, 'description': '', 'tags': 'soup, vegetarian',
            'ing_amount': ['1 1/2', '', '2-3'], 'ing_unit': ['cups', '', 'cloves'],
            'ing_name': ['stock', '', 'garlic'], 'ing_note': ['', '', 'minced'],
            'ing_section': ['pantry', 'other', 'produce'],
            'step': ['Simmer.', '', 'Blend.'],
        })
        self.assertRedirects(response, recipe.get_absolute_url())
        recipe.refresh_from_db()
        self.assertEqual(recipe.title, 'Tomato soup')
        self.assertEqual([str(i) for i in recipe.ingredients.all()], ['1 ½ cups stock', '2–3 cloves garlic, minced'])
        self.assertEqual([s.text for s in recipe.steps.all()], ['Simmer.', 'Blend.'])

    def test_tags_cleaned_and_suggested(self):
        Recipe.objects.create(title='Salad', tags='vegetarian, quick')
        recipe = Recipe.objects.create(title='Soup')
        page = self.client.get(reverse('recipe_edit', args=[recipe.pk]))
        self.assertContains(page, 'data-tag-input="tag-options"')
        self.assertContains(page, '<option value="vegetarian">', html=False)
        self.client.post(reverse('recipe_edit', args=[recipe.pk]), {
            'title': 'Soup', 'servings': 4, 'tags': ' Dinner, beef,,dinner , Gluten-Free'})
        recipe.refresh_from_db()
        self.assertEqual(recipe.tags, 'dinner, beef, gluten-free')

    def test_bad_amount_keeps_form(self):
        recipe = Recipe.objects.create(title='Soup')
        response = self.client.post(reverse('recipe_edit', args=[recipe.pk]), {
            'title': 'Soup', 'servings': 4, 'ing_amount': ['a bit'], 'ing_unit': [''], 'ing_name': ['salt'],
            'ing_note': [''], 'ing_section': ['spices'], 'step': []})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="a bit"')
        self.assertFalse(recipe.ingredients.exists())

    def test_scaling(self):
        recipe = make_recipe(ingredients=[('1 1/2', 'cups', 'beans', 'pantry'), ('', '', 'salt', 'spices')])
        response = self.client.get(recipe.get_absolute_url() + '?servings=8')
        self.assertContains(response, '<span class="amt">3</span> cups beans', html=False)
        self.assertContains(response, 'Scaled from 4 to 8')


def fake_parse_response(draft=None, stop_reason='end_turn'):
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=draft, usage={}, content=[], stop_details=None)


DRAFT = importer.RecipeDraft(
    found=True, problem='', title='Weeknight Chili', description='Hearty and quick.', servings=6,
    prep_minutes=15, cook_minutes=40, tags=['dinner', 'beef'],
    ingredients=[
        importer.IngredientDraft(quantity=1.5, quantity_max=None, unit='lb', name='ground beef', note='',
                                 section='meat'),
        importer.IngredientDraft(quantity=2, quantity_max=3, unit='cloves', name='garlic', note='minced',
                                 section='produce'),
    ],
    steps=['Brown the beef.', 'Simmer everything.'],
)


class ImporterTests(SignedInTestCase):
    def mock_claude(self, *responses):
        client = mock.Mock()
        client.beta.messages.parse.side_effect = list(responses)
        return mock.patch.object(importer, '_client', return_value=client), client

    def test_import_text(self):
        patcher, client = self.mock_claude(fake_parse_response(DRAFT))
        with patcher:
            response = self.client.post(reverse('recipe_new'), {'mode': 'text', 'text': 'Chili recipe...'})
        recipe = Recipe.objects.get(title='Weeknight Chili')
        self.assertRedirects(response, reverse('recipe_edit', args=[recipe.pk]))
        self.assertEqual(recipe.servings, 6)
        self.assertEqual(recipe.ingredients.count(), 2)
        self.assertEqual(recipe.ingredients.get(name='garlic').quantity_max, Decimal('3'))
        self.assertEqual(recipe.steps.count(), 2)
        kwargs = client.beta.messages.parse.call_args.kwargs
        self.assertEqual(kwargs['output_format'], importer.RecipeDraft)
        self.assertEqual(kwargs['fallbacks'], 'default')

    def test_import_photos(self):
        patcher, client = self.mock_claude(fake_parse_response(DRAFT))
        with patcher:
            self.client.post(reverse('recipe_new'), {'mode': 'photos', 'photos': [jpeg_upload(), jpeg_upload('p2.jpg')]})
        content = client.beta.messages.parse.call_args.kwargs['messages'][0]['content']
        self.assertEqual([c['type'] for c in content], ['image', 'image', 'text'])
        self.assertTrue(Recipe.objects.filter(source_note='Imported from photos').exists())

    def test_not_a_recipe(self):
        draft = DRAFT.model_copy(update={'found': False, 'problem': 'That page is a login screen.'})
        patcher, _ = self.mock_claude(fake_parse_response(draft))
        with patcher:
            response = self.client.post(reverse('recipe_new'), {'mode': 'text', 'text': 'hello'})
        self.assertContains(response, 'That page is a login screen.')
        self.assertFalse(Recipe.objects.exists())

    def test_refusal(self):
        patcher, _ = self.mock_claude(fake_parse_response(None, stop_reason='refusal'))
        with patcher:
            response = self.client.post(reverse('recipe_new'), {'mode': 'text', 'text': 'x'})
        self.assertContains(response, 'declined')

    def test_url_uses_page_json_ld(self):
        html = ('<html><head><title>Chili</title><script type="application/ld+json">'
                '{"@type": "Recipe", "name": "Chili", "recipeIngredient": ["1 lb beef"]}</script></head>'
                '<body><nav>menu</nav><p>Best chili ever.</p></body></html>')
        fake = mock.MagicMock(is_redirect=False, ok=True, encoding='utf-8')
        fake.raw.read.return_value = html.encode()
        fake.__enter__.return_value = fake
        patcher, client = self.mock_claude(fake_parse_response(DRAFT))
        with patcher, mock.patch.object(importer, 'check_url', side_effect=lambda u: u), \
                mock.patch.object(importer.requests, 'get', return_value=fake):
            self.client.post(reverse('recipe_new'), {'mode': 'url', 'url': 'https://example.com/chili'})
        text = client.beta.messages.parse.call_args.kwargs['messages'][0]['content'][0]['text']
        self.assertIn('recipeIngredient', text)
        self.assertIn('Best chili ever.', text)
        self.assertNotIn('tools', client.beta.messages.parse.call_args.kwargs)
        self.assertEqual(Recipe.objects.get().source_url, 'https://example.com/chili')

    def test_blocked_site_falls_back_to_web_fetch(self):
        fake = mock.MagicMock(is_redirect=False, ok=False, status_code=403)
        fake.__enter__.return_value = fake
        patcher, client = self.mock_claude(fake_parse_response(DRAFT))
        with patcher, mock.patch.object(importer, 'check_url', side_effect=lambda u: u), \
                mock.patch.object(importer.requests, 'get', return_value=fake):
            self.client.post(reverse('recipe_new'), {'mode': 'url', 'url': 'https://example.com/chili'})
        self.assertEqual(client.beta.messages.parse.call_args.kwargs['tools'][0]['type'], 'web_fetch_20260209')

    def test_private_addresses_refused(self):
        for url in ('http://192.168.68.78:8080/', 'http://localhost/', 'ftp://example.com/x'):
            with self.assertRaises(importer.ImportError_):
                importer.check_url(url)


class MenuTests(SignedInTestCase):
    def setUp(self):
        super().setUp()
        self.household = Household.objects.create(name='Smiths', default_servings=4)
        Contact.objects.create(household=self.household, name='Ann', email='ann@example.com')
        Contact.objects.create(household=self.household, name='Bob', email='bob@example.com', receives_menus=False)
        self.chili = make_recipe('Chili', 4, [('1', 'lb', 'ground beef', 'meat'), ('1', '', 'yellow onion', 'produce'),
                                              ('', '', 'salt', 'spices')])
        self.tacos = make_recipe('Tacos', 2, [('1/2', 'lb', 'Ground beef', 'meat'), ('2', '', 'Yellow onions', 'produce')])
        self.menu = Menu.objects.create(household=self.household, title='Week 1')

    def add(self, recipe, servings, **extra):
        return self.client.post(reverse('menu_item_add', args=[self.menu.pk]), {
            'item-recipe': recipe.pk if recipe else '', 'item-servings': servings, 'item-course': 'Dinner', **extra})

    def test_add_dishes_and_shopping_list(self):
        self.add(self.chili, 8)   # doubles chili
        self.add(self.tacos, 4)   # doubles tacos
        self.add(None, 4, **{'item-title': 'Green salad'})
        self.assertEqual(self.menu.items.count(), 3)
        page = self.client.get(reverse('menu_shopping', args=[self.menu.pk]))
        items = {i.name.lower(): i for i in self.menu.shopping_items.all()}
        self.assertEqual(items['ground beef'].amount, '3 lb')  # 2 + 1
        self.assertEqual(items['yellow onion'].amount, '6')    # 2 + 4
        self.assertEqual(items['salt'].amount, 'as needed')
        self.assertIn('Chili', items['ground beef'].used_in)
        self.assertContains(page, 'Green salad')  # listed under "Not on this list"

    def test_rebuild_keeps_checks_and_manual_items(self):
        self.add(self.chili, 4)
        rebuild_shopping_list(self.menu)
        beef = self.menu.shopping_items.get(name='ground beef')
        self.client.post(reverse('shopping_toggle', args=[beef.pk]), {'checked': '1'})
        self.client.post(reverse('menu_shopping', args=[self.menu.pk]), {'action': 'add', 'name': 'Paper towels'})
        self.client.post(reverse('menu_shopping', args=[self.menu.pk]), {'action': 'rebuild'})
        self.assertTrue(self.menu.shopping_items.get(name='ground beef').checked)
        self.assertTrue(self.menu.shopping_items.filter(name='Paper towels', manual=True).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_send_menu(self):
        self.add(self.chili, 4)
        form = self.client.get(reverse('menu_send', args=[self.menu.pk]))
        self.assertContains(form, 'value="ann@example.com"')
        response = self.client.post(reverse('menu_send', args=[self.menu.pk]),
                                    {'recipients': ['ann@example.com'], 'extra': 'chef@example.com'})
        self.assertRedirects(response, self.menu.get_absolute_url())
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['ann@example.com', 'chef@example.com'])
        message = mail.outbox[0]
        self.assertIn('Chili', message.body)
        self.assertIn(self.menu.client_url(), message.body)
        self.assertEqual(message.reply_to, ['lweischedel@gmail.com'])
        self.assertIn('Review and approve', message.alternatives[0][0])
        self.menu.refresh_from_db()
        self.assertEqual(self.menu.status, 'sent')

    def test_move_and_duplicate(self):
        self.add(self.chili, 4)
        self.add(self.tacos, 4)
        tacos = self.menu.items.get(recipe=self.tacos)
        self.client.post(reverse('menu_item_move', args=[tacos.pk, 'up']))
        self.assertEqual([i.recipe.title for i in self.menu.items.all()], ['Tacos', 'Chili'])
        self.client.post(reverse('menu_duplicate', args=[self.menu.pk]))
        copy = Menu.objects.exclude(pk=self.menu.pk).get()
        self.assertEqual(copy.items.count(), 2)


class ClientPageTests(TestCase):
    """The client-facing pages need no sign-in."""

    def setUp(self):
        self.household = Household.objects.create(name='Smiths')
        self.menu = Menu.objects.create(household=self.household, title='Holiday dinner', intro='Can\'t wait!')
        recipe = make_recipe('Roast chicken', 4)
        MenuItem.objects.create(menu=self.menu, recipe=recipe, servings=6, course='Main')

    def test_menu_page_and_feedback(self):
        page = self.client.get(self.menu.client_path())
        self.assertContains(page, 'Roast chicken')
        self.assertContains(page, 'Serves 6')
        self.assertContains(page, 'noindex')
        self.assertNotContains(page, 'Sign out')
        response = self.client.post(self.menu.client_path(), {'name': 'Ann', 'comment': 'Looks great', 'approved': '1'})
        self.assertRedirects(response, self.menu.client_path() + '?thanks=1#respond', fetch_redirect_response=False)
        feedback = MenuFeedback.objects.get()
        self.assertTrue(feedback.approved)
        self.menu.refresh_from_db()
        self.assertEqual(self.menu.status, 'approved')

    def test_empty_feedback_ignored(self):
        self.client.post(self.menu.client_path(), {'name': '', 'comment': '', 'approved': '0'})
        self.assertFalse(MenuFeedback.objects.exists())

    def test_household_page_lists_sent_menus_only(self):
        Menu.objects.create(household=self.household, title='Secret draft')
        self.menu.status = 'sent'
        self.menu.save()
        page = self.client.get(reverse('client_household', args=[self.household.share_token]))
        self.assertContains(page, 'Holiday dinner')
        self.assertNotContains(page, 'Secret draft')

    def test_unknown_token_404(self):
        self.assertEqual(self.client.get('/m/00000000-0000-0000-0000-000000000000/').status_code, 404)


class PhotoTests(SignedInTestCase):
    def test_upload_and_serve(self):
        recipe = make_recipe()
        self.client.post(reverse('photos'), {'photos': [jpeg_upload()], 'caption': 'Plated', 'recipe': recipe.pk})
        photo = DishPhoto.objects.get()
        recipe.refresh_from_db()
        self.assertEqual(recipe.photo, photo)  # first photo becomes the recipe's photo
        self.client.logout()
        response = self.client.get(photo.url())  # public
        self.assertEqual(response['Content-Type'], 'image/jpeg')
        self.assertTrue(response.content.startswith(b'\xff\xd8'))

    def test_upload_without_caption(self):
        self.client.post(reverse('photos'), {'photos': [jpeg_upload()]})
        self.assertEqual(DishPhoto.objects.count(), 1)

    def test_bad_file(self):
        bad = SimpleUploadedFile('notes.txt', b'not an image', content_type='text/plain')
        response = self.client.post(reverse('photos'), {'photos': [bad]}, follow=True)
        self.assertContains(response, 'isn&#x27;t a photo we can read')


class ManageTests(SignedInTestCase):
    def test_options_and_access(self):
        category = PreferenceCategory.objects.get(name='Cuisines')
        self.client.post(reverse('manage'), {'action': 'option', 'opt-category': category.pk, 'opt-name': 'Ethiopian'})
        option = PreferenceOption.objects.get(name='Ethiopian')
        self.client.post(reverse('manage_option', args=[option.pk]), {'action': 'toggle'})
        option.refresh_from_db()
        self.assertFalse(option.active)
        self.client.post(reverse('manage'), {'action': 'user', 'user-email': 'Helper@Example.com'})
        self.assertTrue(AllowedUser.objects.filter(email='helper@example.com', is_admin=False).exists())
        me = AllowedUser.objects.get(email='lweischedel@gmail.com')
        self.client.post(reverse('manage_user', args=[me.pk]), {'action': 'delete'})
        self.assertTrue(AllowedUser.objects.filter(pk=me.pk).exists())  # can't remove yourself

    def test_used_option_cannot_be_deleted(self):
        option = PreferenceOption.objects.get(name='Peanuts')
        HouseholdPreference.objects.create(household=Household.objects.create(name='H'), option=option, stance='allergy')
        self.client.post(reverse('manage_option', args=[option.pk]), {'action': 'delete'})
        self.assertTrue(PreferenceOption.objects.filter(pk=option.pk).exists())

    def test_pages_render(self):
        household = Household.objects.create(name='Smiths')
        menu = Menu.objects.create(household=household, title='M')
        recipe = make_recipe()
        MenuItem.objects.create(menu=menu, recipe=recipe, servings=2)
        for url in [reverse('home'), reverse('households'), reverse('household_preferences', args=[household.pk]),
                    reverse('household_edit', args=[household.pk]), menu.get_absolute_url(),
                    reverse('menu_send', args=[menu.pk]), reverse('recipes'), reverse('recipe_new'),
                    reverse('recipe_edit', args=[recipe.pk]), reverse('photos'), reverse('manage')]:
            self.assertEqual(self.client.get(url).status_code, 200, url)


PUBLIC = 'cookingwiththe.loraxglobal.com'
CHEF = 'chef.cookingwiththe.loraxglobal.com'


@override_settings(PUBLIC_BASE_URL=f'https://{PUBLIC}', PUBLIC_HOST=PUBLIC,
                   CHEF_BASE_URL=f'https://{CHEF}', CHEF_HOST=CHEF,
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class WebsiteTests(TestCase):
    def public(self, path, **kwargs):
        return self.client.get(path, HTTP_HOST=PUBLIC, secure=True, **kwargs)

    def test_public_pages_need_no_sign_in(self):
        for path in ['/', '/about/', '/services/', '/gallery/', '/contact/', '/contact/thanks/', '/privacy/',
                     '/robots.txt', '/sitemap.xml']:
            response = self.public(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn('X-Robots-Tag', response, path)
        home = self.public('/')
        self.assertContains(home, 'Breakfast week packages')  # Lori's services, seeded
        self.assertNotContains(home, 'Dinner parties')  # starter placeholder removed
        self.assertContains(home, '25% off for teachers and health care staff')
        self.assertContains(self.public('/services/'), '<li>Overnight oats ($20 for the week)</li>', html=False)
        self.assertContains(self.public('/sitemap.xml'), f'https://{PUBLIC}/services/')

    def test_workspace_host_is_private_and_noindex(self):
        response = self.client.get('/', HTTP_HOST=CHEF, secure=True)
        self.assertRedirects(response, reverse('welcome'), fetch_redirect_response=False)
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertContains(self.client.get('/robots.txt', HTTP_HOST=CHEF), 'Disallow: /')

    def test_workspace_paths_on_public_host_redirect(self):
        response = self.public('/recipes/?q=soup')
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], f'https://{CHEF}/recipes/?q=soup')
        self.assertEqual(self.public('/accounts/google/login/')['Location'],
                         f'https://{CHEF}/accounts/google/login/')
        self.assertEqual(self.public('/no-such-page/').status_code, 404)

    def test_client_links_use_public_host_and_work_on_both(self):
        household = Household.objects.create(name='Smiths')
        menu = Menu.objects.create(household=household, title='Week 1', status='sent')
        self.assertEqual(menu.client_url(), f'https://{PUBLIC}/m/{menu.share_token}/')
        self.assertContains(self.public(menu.client_path()), 'Week 1')
        self.assertContains(self.client.get(menu.client_path(), HTTP_HOST=CHEF), 'Week 1')
        self.assertContains(self.public(f'/h/{household.share_token}/'), 'Week 1')

    def test_gallery_shows_only_website_photos(self):
        shown = DishPhoto.objects.create(image=b'x', caption='Braised short ribs', on_website=True)
        DishPhoto.objects.create(image=b'x', caption='Private test dish')
        page = self.public('/gallery/')
        self.assertContains(page, 'Braised short ribs')
        self.assertContains(page, shown.url())
        self.assertNotContains(page, 'Private test dish')
        self.assertEqual(self.public(shown.url()).status_code, 200)

    def test_contact_form_saves_and_emails(self):
        response = self.client.post('/contact/', {
            'name': 'Jo Client', 'email': 'jo@example.com', 'service': 'Meal planning and meal prep',
            'household_size': 4, 'message': 'We need dinners Mon-Thu.',
        }, HTTP_HOST=PUBLIC, secure=True)
        self.assertRedirects(response, '/contact/thanks/', fetch_redirect_response=False)
        inquiry = Inquiry.objects.get()
        self.assertEqual(inquiry.service, 'Meal planning and meal prep')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, ['jo@example.com'])
        self.assertIn('Mon-Thu', mail.outbox[0].body)
        self.assertIn(f'https://{CHEF}/website/', mail.outbox[0].body)

    def test_contact_form_honeypot_drops_spam(self):
        response = self.client.post('/contact/', {
            'name': 'Bot', 'email': 'bot@example.com', 'message': 'buy now', 'website': 'http://spam.example',
        }, HTTP_HOST=PUBLIC, secure=True)
        self.assertRedirects(response, '/contact/thanks/', fetch_redirect_response=False)
        self.assertFalse(Inquiry.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_google_tag_and_conversion(self):
        self.assertNotContains(self.public('/'), 'googletagmanager')
        site = SiteSettings.load()
        site.google_tag_id = 'AW-123456789'
        site.google_ads_conversion = 'AW-123456789/AbC-d_1'
        site.save()
        self.assertContains(self.public('/'), 'gtag/js?id=AW-123456789')
        self.assertNotContains(self.public('/'), "'conversion'")
        self.assertContains(self.public('/contact/thanks/'), "'send_to': 'AW-123456789/AbC-d_1'")


@override_settings(PUBLIC_BASE_URL=f'https://{PUBLIC}', PUBLIC_HOST=PUBLIC,
                   CHEF_BASE_URL=f'https://{CHEF}', CHEF_HOST=CHEF)
class WebsiteManageTests(SignedInTestCase):
    def test_edit_text_services_and_inquiries(self):
        response = self.client.post(reverse('website'), {
            'action': 'text', 'tagline': 'Dinner, handled.', 'intro': 'Weekly menus.', 'about': 'I cook.',
            'service_area': 'Denver', 'offer': '', 'phone': '', 'google_tag_id': 'not-a-tag', 'google_ads_conversion': '',
        })
        self.assertContains(response, 'Looks like AW-123456789')
        self.client.post(reverse('website'), {
            'action': 'text', 'tagline': 'Dinner, handled.', 'intro': 'Weekly menus.', 'about': 'I cook.',
            'service_area': 'Denver', 'offer': '', 'phone': '', 'google_tag_id': 'G-ABC123', 'google_ads_conversion': '',
        })
        self.assertEqual(SiteSettings.load().tagline, 'Dinner, handled.')

        self.client.post(reverse('website'), {'action': 'service', 'svc-name': 'Knife skills', 'svc-summary': 'Batch cooking.',
                                              'svc-order': 3, 'svc-active': 'on'})
        service = Service.objects.get(name='Knife skills')
        self.client.post(reverse('website_service', args=[service.pk]), {
            f's{service.pk}-name': 'Knife skills', f's{service.pk}-summary': 'Batch cooking.', f's{service.pk}-order': 3})
        service.refresh_from_db()
        self.assertFalse(service.active)
        page = self.client.get('/services/', HTTP_HOST=PUBLIC)
        self.assertContains(page, 'Denver')
        self.assertNotContains(page, 'Knife skills')

        inquiry = Inquiry.objects.create(name='Jo', email='jo@example.com', message='Hi')
        self.assertContains(self.client.get(reverse('home')), 'New website inquiries')
        self.client.post(reverse('website_inquiry', args=[inquiry.pk]), {'action': 'toggle'})
        inquiry.refresh_from_db()
        self.assertTrue(inquiry.handled)


class ProseFilterTests(TestCase):
    def test_paragraphs_and_lists(self):
        from kitchen.templatetags.kitchen import prose
        self.assertEqual(prose('Hi <b>\nthere\n\n- one\n- two & three'),
                         '<p>Hi &lt;b&gt;<br>there</p><ul><li>one</li><li>two &amp; three</li></ul>')
        self.assertEqual(prose(''), '')
