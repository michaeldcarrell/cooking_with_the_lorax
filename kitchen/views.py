import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import logout
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from kitchen import importer
from kitchen.forms import (
    AllowedUserForm, CategoryForm, ContactForm, HouseholdForm, MenuForm, MenuItemForm, NewHouseholdForm,
    NewMenuForm, NoteForm, OptionForm, PhotoEditForm, PhotoUploadForm, RecipeForm, SendMenuForm, SiteSettingsForm,
)
from kitchen.models import (
    SECTIONS, STANCES, AllowedUser, Contact, DishPhoto, Household, HouseholdPreference, Ingredient, Menu,
    MenuFeedback, MenuItem, Note, PreferenceCategory, PreferenceOption, Recipe, ShoppingItem, SiteSettings, Step,
)
from kitchen.quantities import parse_amount
from kitchen.services import PhotoError, rebuild_shopping_list, save_photo, send_menu

logger = logging.getLogger(__name__)

COURSE_SUGGESTIONS = ['Breakfast', 'Lunch', 'Dinner', 'Starter', 'Main', 'Side', 'Salad', 'Soup', 'Dessert', 'Snack']


def admin_required(view):
    def wrapped(request, *args, **kwargs):
        if not request.allowed_user.is_admin:
            messages.error(request, 'Only admins can open that page.')
            return redirect('home')
        return view(request, *args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


# --- sign in / home -----------------------------------------------------------------------------------

def welcome(request):
    if request.user.is_authenticated and AllowedUser.objects.filter(email__iexact=request.user.email).exists():
        return redirect('home')
    return render(request, 'welcome.html')


@require_POST
def sign_out(request):
    logout(request)
    return redirect('welcome')


def healthz(request):
    return HttpResponse('ok', content_type='text/plain')


def home(request):
    today = timezone.localdate()
    households = (Household.objects.filter(archived=False)
                  .annotate(menu_count=Count('menus'), last_menu=Max('menus__starts_on')))
    upcoming = (Menu.objects.filter(Q(ends_on__gte=today) | Q(ends_on__isnull=True, starts_on__gte=today) |
                                    Q(starts_on__isnull=True, ends_on__isnull=True, status='draft'))
                .select_related('household').order_by('starts_on')[:8])
    feedback = MenuFeedback.objects.filter(read=False).select_related('menu__household')[:10]
    return render(request, 'kitchen/home.html', {
        'households': households, 'upcoming': upcoming, 'feedback': feedback,
        'recipe_count': Recipe.objects.filter(archived=False).count(),
        'new_household_form': NewHouseholdForm(),
    })


# --- households ---------------------------------------------------------------------------------------

def households(request):
    show_archived = request.GET.get('archived') == '1'
    form = NewHouseholdForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        household = form.save()
        messages.success(request, f'Added {household.name}. Add their contacts and preferences next.')
        return redirect(household)
    qs = Household.objects.filter(archived=show_archived).annotate(
        menu_count=Count('menus', distinct=True), contact_count=Count('contacts', distinct=True))
    return render(request, 'kitchen/households.html', {'households': qs, 'form': form, 'show_archived': show_archived})


def household(request, pk):
    household = get_object_or_404(Household, pk=pk)
    return render(request, 'kitchen/household.html', {
        'household': household,
        'contacts': household.contacts.all(),
        'notes': household.notes.select_related('author'),
        'menus': household.menus.annotate(item_count=Count('items'),
                                          unread=Count('feedback', filter=Q(feedback__read=False))),
        'prefs': household.preferences_by_stance(),
        'stances': STANCES,
        'note_form': NoteForm(),
        'contact_form': ContactForm(),
        'new_menu_form': NewMenuForm(initial={'title': _default_menu_title(household)}),
    })


def _default_menu_title(household: Household) -> str:
    return f'{household.name} menu'


def household_edit(request, pk):
    household = get_object_or_404(Household, pk=pk)
    form = HouseholdForm(request.POST or None, instance=household)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Saved.')
        return redirect(household)
    return render(request, 'kitchen/household_edit.html', {'household': household, 'form': form})


@require_POST
def household_delete(request, pk):
    household = get_object_or_404(Household, pk=pk)
    if request.POST.get('confirm') != household.name:
        messages.error(request, 'Type the household name exactly to delete it.')
        return redirect('household_edit', pk=pk)
    household.delete()
    messages.success(request, f'Deleted {household.name} and everything that belonged to it.')
    return redirect('households')


def household_preferences(request, pk):
    household = get_object_or_404(Household, pk=pk)
    current = {p.option_id: p.stance for p in household.preferences.all()}
    categories = PreferenceCategory.objects.prefetch_related('options')
    if request.method == 'POST':
        valid = {key for key, _ in STANCES}
        with transaction.atomic():
            for category in categories:
                for option in category.options.all():
                    stance = request.POST.get(f'opt-{option.pk}', '')
                    if stance in valid:
                        HouseholdPreference.objects.update_or_create(
                            household=household, option=option, defaults={'stance': stance})
                    elif f'opt-{option.pk}' in request.POST:  # shown on the form and set to "—"
                        HouseholdPreference.objects.filter(household=household, option=option).delete()
            household.preference_notes = request.POST.get('preference_notes', '').strip()
            household.save(update_fields=['preference_notes'])
        messages.success(request, 'Preferences saved.')
        return redirect(household)
    rows = []
    for category in categories:
        options = [o for o in category.options.all() if o.active or o.pk in current]
        if options:
            rows.append((category, [(o, current.get(o.pk, '')) for o in options]))
    return render(request, 'kitchen/household_preferences.html', {
        'household': household, 'rows': rows, 'stances': STANCES})


@require_POST
def contact_add(request, pk):
    household = get_object_or_404(Household, pk=pk)
    form = ContactForm(request.POST)
    if form.is_valid():
        contact = form.save(commit=False)
        contact.household = household
        contact.save()
        messages.success(request, f'Added {contact.name}.')
    else:
        messages.error(request, 'Couldn\'t add that contact: ' + '; '.join(
            f'{field}: {" ".join(errors)}' for field, errors in form.errors.items()))
    return redirect(household)


def contact_edit(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == 'POST':
        if request.POST.get('delete'):
            contact.delete()
            messages.success(request, f'Removed {contact.name}.')
            return redirect(contact.household)
        if form.is_valid():
            form.save()
            messages.success(request, 'Saved.')
            return redirect(contact.household)
    return render(request, 'kitchen/contact_edit.html', {'contact': contact, 'form': form})


@require_POST
def note_add(request, pk):
    household = get_object_or_404(Household, pk=pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        Note.objects.create(household=household, body=form.cleaned_data['body'].strip(),
                            pinned=form.cleaned_data['pinned'], author=request.user)
    return redirect(reverse('household', args=[pk]) + '#notes')


@require_POST
def note_action(request, pk):
    note = get_object_or_404(Note, pk=pk)
    action = request.POST.get('action')
    if action == 'delete':
        note.delete()
    elif action == 'pin':
        note.pinned = not note.pinned
        note.save(update_fields=['pinned'])
    return redirect(reverse('household', args=[note.household_id]) + '#notes')


# --- menus --------------------------------------------------------------------------------------------

@require_POST
def menu_new(request, pk):
    household = get_object_or_404(Household, pk=pk)
    form = NewMenuForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Give the menu a title.')
        return redirect(household)
    menu = form.save(commit=False)
    menu.household = household
    menu.save()
    return redirect(menu)


def menu(request, pk):
    menu = get_object_or_404(Menu.objects.select_related('household'), pk=pk)
    form = MenuForm(request.POST or None, instance=menu)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Menu saved.')
        return redirect(menu)
    household = menu.household
    next_order = (menu.items.aggregate(m=Max('order'))['m'] or 0) + 1
    item_form = MenuItemForm(initial={'servings': household.default_servings, 'date': menu.starts_on,
                                      'course': 'Dinner'}, prefix='item')
    unread = menu.feedback.filter(read=False)
    response = render(request, 'kitchen/menu.html', {
        'menu': menu, 'household': household, 'form': form, 'item_form': item_form, 'next_order': next_order,
        'items': menu.items.select_related('recipe__photo', 'photo'),
        'feedback': menu.feedback.all(), 'courses': COURSE_SUGGESTIONS,
        'prefs': household.preferences_by_stance(), 'stances': STANCES,
        'pinned_notes': household.notes.filter(pinned=True),
    })
    unread.update(read=True)
    return response


@require_POST
def menu_delete(request, pk):
    menu = get_object_or_404(Menu, pk=pk)
    household = menu.household
    menu.delete()
    messages.success(request, f'Deleted "{menu.title}".')
    return redirect(household)


@require_POST
def menu_duplicate(request, pk):
    menu = get_object_or_404(Menu, pk=pk)
    items = list(menu.items.all())
    copy = Menu.objects.create(household=menu.household, title=f'{menu.title} (copy)', intro=menu.intro)
    MenuItem.objects.bulk_create([
        MenuItem(menu=copy, order=i.order, course=i.course, recipe=i.recipe, title=i.title,
                 description=i.description, servings=i.servings, photo=i.photo)
        for i in items
    ])
    messages.success(request, 'Copied. Set the dates for the new menu.')
    return redirect(copy)


@require_POST
def menu_item_add(request, pk):
    menu = get_object_or_404(Menu, pk=pk)
    form = MenuItemForm(request.POST, prefix='item')
    if form.is_valid():
        item = form.save(commit=False)
        item.menu = menu
        item.order = (menu.items.aggregate(m=Max('order'))['m'] or 0) + 1
        item.save()
        messages.success(request, f'Added {item.display_title()}.')
    else:
        messages.error(request, ' '.join(e for errors in form.errors.values() for e in errors))
    return redirect(reverse('menu', args=[pk]) + '#dishes')


def menu_item_edit(request, pk):
    item = get_object_or_404(MenuItem.objects.select_related('menu'), pk=pk)
    form = MenuItemForm(request.POST or None, instance=item)
    if request.method == 'POST':
        if request.POST.get('delete'):
            item.delete()
            messages.success(request, f'Removed {item.display_title()}.')
            return redirect(reverse('menu', args=[item.menu_id]) + '#dishes')
        if form.is_valid():
            form.save()
            return redirect(reverse('menu', args=[item.menu_id]) + '#dishes')
    return render(request, 'kitchen/menu_item_edit.html', {'item': item, 'form': form, 'courses': COURSE_SUGGESTIONS})


@require_POST
def menu_item_move(request, pk, direction):
    item = get_object_or_404(MenuItem, pk=pk)
    siblings = list(item.menu.items.all())
    index = siblings.index(item)
    swap = index - 1 if direction == 'up' else index + 1
    if 0 <= swap < len(siblings):
        other = siblings[swap]
        if other.date != item.date:
            # Moving across days moves the dish to that day.
            item.date = other.date
        siblings[index], siblings[swap] = siblings[swap], siblings[index]
        with transaction.atomic():
            item.save(update_fields=['date'])
            for order, sibling in enumerate(siblings):
                MenuItem.objects.filter(pk=sibling.pk).update(order=order)
    return redirect(reverse('menu', args=[item.menu_id]) + '#dishes')


def menu_send(request, pk):
    menu = get_object_or_404(Menu.objects.select_related('household'), pk=pk)
    contacts = list(menu.household.contacts.all())
    form = SendMenuForm(request.POST or None, contacts=contacts)
    if not menu.items.exists():
        messages.error(request, 'Add some dishes before sending the menu.')
        return redirect(menu)
    if request.method == 'POST' and form.is_valid():
        try:
            sent = send_menu(menu, form.cleaned_data['addresses'])
        except Exception:
            logger.exception('Sending menu %s failed', menu.pk)
            messages.error(request, 'The email didn\'t go out. Check the email settings, then try again.')
        else:
            messages.success(request, f'Sent to {sent} {"person" if sent == 1 else "people"}.')
            return redirect(menu)
    return render(request, 'kitchen/menu_send.html', {'menu': menu, 'form': form, 'contacts': contacts})


def menu_shopping(request, pk):
    menu = get_object_or_404(Menu.objects.select_related('household'), pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'rebuild':
            count = rebuild_shopping_list(menu)
            messages.success(request, f'Built the list from the menu: {count} items.')
        elif action == 'add':
            name = request.POST.get('name', '').strip()
            if name:
                section = request.POST.get('section')
                ShoppingItem.objects.create(
                    menu=menu, name=name[:200], amount=request.POST.get('amount', '').strip()[:200], manual=True,
                    section=section if section in dict(SECTIONS) else 'other')
        elif action == 'clear_checked':
            menu.shopping_items.filter(checked=True, manual=True).delete()
            menu.shopping_items.filter(checked=True).update(checked=False)
        return redirect('menu_shopping', pk=pk)
    if not menu.shopping_items.exists() and menu.items.filter(recipe__isnull=False).exists():
        rebuild_shopping_list(menu)
    groups = []
    items = list(menu.shopping_items.all())
    for key, label in SECTIONS:
        in_section = [i for i in items if i.section == key]
        if in_section:
            groups.append((label, in_section))
    without_recipe = menu.items.filter(recipe__isnull=True)
    remaining = sum(1 for i in items if not i.checked)
    return render(request, 'kitchen/shopping.html', {
        'menu': menu, 'groups': groups, 'sections': SECTIONS, 'without_recipe': without_recipe,
        'remaining': remaining, 'total': len(items),
        'done_pct': round(100 * (len(items) - remaining) / len(items)) if items else 0,
    })


@require_POST
def shopping_toggle(request, pk):
    item = get_object_or_404(ShoppingItem, pk=pk)
    item.checked = request.POST.get('checked') == '1'
    item.save(update_fields=['checked'])
    if request.headers.get('X-Requested-With') == 'fetch':
        return JsonResponse({'ok': True, 'checked': item.checked})
    return redirect('menu_shopping', pk=item.menu_id)


@require_POST
def shopping_delete(request, pk):
    item = get_object_or_404(ShoppingItem, pk=pk)
    item.delete()
    return redirect('menu_shopping', pk=item.menu_id)


# --- recipes ------------------------------------------------------------------------------------------

def recipes(request):
    query = request.GET.get('q', '').strip()
    show_archived = request.GET.get('archived') == '1'
    qs = Recipe.objects.filter(archived=show_archived).select_related('photo').defer('photo__image')
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(tags__icontains=query) | Q(description__icontains=query) |
                       Q(ingredients__name__icontains=query)).distinct()
    return render(request, 'kitchen/recipes.html', {'recipes': qs, 'query': query, 'show_archived': show_archived})


def recipe(request, pk):
    recipe = get_object_or_404(Recipe.objects.select_related('photo'), pk=pk)
    try:
        servings = max(1, min(500, int(request.GET.get('servings', recipe.servings))))
    except ValueError:
        servings = recipe.servings
    factor = Decimal(servings) / Decimal(recipe.servings or 1)
    ingredients = [(ing, ing.amount(factor)) for ing in recipe.ingredients.all()]
    return render(request, 'kitchen/recipe.html', {
        'recipe': recipe, 'servings': servings, 'ingredients': ingredients, 'steps': recipe.steps.all(),
        'photos': recipe.photos.defer('image'),
        'used_on': recipe.menu_items.select_related('menu__household').order_by('-menu__starts_on')[:10],
    })


def recipe_new(request):
    if request.method == 'POST':
        mode = request.POST.get('mode')
        try:
            if mode == 'url':
                url = request.POST.get('url', '').strip()
                draft = importer.from_url(url)
                recipe = importer.save_draft(draft, source_url=url, source_note='Imported from a web page')
            elif mode == 'photos':
                draft = importer.from_photos(request.FILES.getlist('photos'))
                recipe = importer.save_draft(draft, source_note='Imported from photos')
            elif mode == 'text':
                draft = importer.from_text(request.POST.get('text', ''))
                recipe = importer.save_draft(draft, source_note='Imported from pasted text')
            else:
                recipe = Recipe.objects.create(title=request.POST.get('title', '').strip()[:200] or 'New recipe')
                return redirect('recipe_edit', pk=recipe.pk)
        except importer.ImportError_ as e:
            messages.error(request, str(e))
            return render(request, 'kitchen/recipe_new.html', {'mode': mode, 'post': request.POST})
        messages.success(request, 'Imported. Check it over, then save.')
        return redirect('recipe_edit', pk=recipe.pk)
    return render(request, 'kitchen/recipe_new.html', {'mode': request.GET.get('mode', 'url'), 'post': {}})


def _ingredient_rows(post) -> tuple[list[Ingredient], list[str]]:
    """Ingredient rows from the edit form's parallel lists. Rows with no name are skipped."""
    rows, errors = [], []
    names = post.getlist('ing_name')
    amounts = post.getlist('ing_amount')
    units = post.getlist('ing_unit')
    notes = post.getlist('ing_note')
    sections = post.getlist('ing_section')
    valid_sections = dict(SECTIONS)
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        amount = amounts[i] if i < len(amounts) else ''
        try:
            low, high = parse_amount(amount)
        except ValueError as e:
            errors.append(f'{name}: {e}')
            low = high = None
        section = sections[i] if i < len(sections) and sections[i] in valid_sections else 'other'
        row = Ingredient(order=len(rows), quantity=low, quantity_max=high,
                         unit=(units[i] if i < len(units) else '').strip()[:40], name=name[:200],
                         note=(notes[i] if i < len(notes) else '').strip()[:200], section=section)
        row.typed_amount = amount  # shown again as typed if the form has errors
        rows.append(row)
    return rows, errors


def recipe_edit(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)
    form = RecipeForm(request.POST or None, instance=recipe)
    if request.method == 'POST':
        ingredients, ingredient_errors = _ingredient_rows(request.POST)
        steps = [s.strip() for s in request.POST.getlist('step') if s.strip()]
        if form.is_valid() and not ingredient_errors:
            with transaction.atomic():
                form.save()
                recipe.ingredients.all().delete()
                for ing in ingredients:
                    ing.recipe = recipe
                Ingredient.objects.bulk_create(ingredients)
                recipe.steps.all().delete()
                Step.objects.bulk_create([Step(recipe=recipe, order=i, text=t) for i, t in enumerate(steps)])
            messages.success(request, 'Recipe saved.')
            return redirect(recipe)
        for error in ingredient_errors:
            messages.error(request, error)
        ingredient_rows = [(ing, ing.typed_amount) for ing in ingredients]
    else:
        steps = [s.text for s in recipe.steps.all()]
        ingredient_rows = [(ing, ing.amount()) for ing in recipe.ingredients.all()]
    return render(request, 'kitchen/recipe_edit.html', {
        'recipe': recipe, 'form': form, 'ingredient_rows': ingredient_rows, 'steps': steps, 'sections': SECTIONS,
        'all_tags': sorted({t for tags in Recipe.objects.exclude(tags='').values_list('tags', flat=True)
                            for t in (x.strip().lower() for x in tags.split(',')) if t}),
    })


@require_POST
def recipe_archive(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)
    recipe.archived = not recipe.archived
    recipe.save(update_fields=['archived'])
    messages.success(request, f'{"Archived" if recipe.archived else "Restored"} {recipe.title}.')
    return redirect(recipe)


@require_POST
def recipe_photo_upload(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)
    uploads = request.FILES.getlist('photos')
    added = 0
    for upload in uploads:
        try:
            photo = save_photo(upload, request.user, recipe=recipe)
            added += 1
        except PhotoError as e:
            messages.error(request, str(e))
    if added and request.POST.get('make_main') and photo:
        recipe.photo = photo
        recipe.save(update_fields=['photo'])
    if added:
        messages.success(request, f'Added {added} photo{"s" if added != 1 else ""}.')
    return redirect(recipe)


@require_POST
def recipe_set_photo(request, pk):
    recipe = get_object_or_404(Recipe, pk=pk)
    photo = get_object_or_404(DishPhoto.objects.defer('image'), pk=request.POST.get('photo'))
    recipe.photo = photo
    recipe.save(update_fields=['photo'])
    return redirect(recipe)


# --- photos -------------------------------------------------------------------------------------------

def photos(request):
    # Not `request.POST or None`: an upload with no caption or recipe has an empty POST (only FILES).
    form = PhotoUploadForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        added = 0
        for upload in request.FILES.getlist('photos'):
            try:
                save_photo(upload, request.user, caption=form.cleaned_data['caption'],
                           recipe=form.cleaned_data['recipe'])
                added += 1
            except PhotoError as e:
                messages.error(request, str(e))
        if added:
            messages.success(request, f'Uploaded {added} photo{"s" if added != 1 else ""}.')
        elif not request.FILES.getlist('photos'):
            messages.error(request, 'Choose one or more photos to upload.')
        return redirect('photos')
    return render(request, 'kitchen/photos.html', {
        'photos': DishPhoto.objects.defer('image').select_related('recipe'), 'form': form})


def photo_edit(request, pk):
    photo = get_object_or_404(DishPhoto.objects.defer('image'), pk=pk)
    form = PhotoEditForm(request.POST or None, instance=photo)
    if request.method == 'POST':
        if request.POST.get('delete'):
            photo.delete()
            messages.success(request, 'Photo deleted.')
            return redirect('photos')
        if form.is_valid():
            form.save()
            messages.success(request, 'Saved.')
            return redirect('photos')
    return render(request, 'kitchen/photo_edit.html', {'photo': photo, 'form': form})


@cache_control(public=True, max_age=60 * 60 * 24 * 30, immutable=True)
def photo_file(request, token):
    photo = DishPhoto.objects.filter(token=token).only('image', 'content_type').first()
    if not photo:
        raise Http404
    return HttpResponse(bytes(photo.image), content_type=photo.content_type)


# --- admin page ---------------------------------------------------------------------------------------

@admin_required
def manage(request):
    site = SiteSettings.load()
    site_form = SiteSettingsForm(instance=site)
    category_form = CategoryForm(prefix='cat')
    option_form = OptionForm(prefix='opt')
    user_form = AllowedUserForm(prefix='user')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'site':
            site_form = SiteSettingsForm(request.POST, instance=site)
            if site_form.is_valid():
                site_form.save()
                messages.success(request, 'Business details saved.')
                return redirect('manage')
        elif action == 'category':
            category_form = CategoryForm(request.POST, prefix='cat')
            if category_form.is_valid():
                category_form.save()
                messages.success(request, 'Category added.')
                return redirect(reverse('manage') + '#preferences')
        elif action == 'option':
            option_form = OptionForm(request.POST, prefix='opt')
            if option_form.is_valid():
                option = option_form.save(commit=False)
                option.order = (option.category.options.aggregate(m=Max('order'))['m'] or 0) + 1
                option.save()
                messages.success(request, f'Added {option.name}.')
                return redirect(reverse('manage') + f'#cat-{option.category_id}')
        elif action == 'user':
            user_form = AllowedUserForm(request.POST, prefix='user')
            if user_form.is_valid():
                user_form.save()
                messages.success(request, 'Access added.')
                return redirect(reverse('manage') + '#access')
        if any(f.errors for f in (site_form, category_form, option_form, user_form)):
            messages.error(request, 'Please fix the errors below.')
    categories = PreferenceCategory.objects.prefetch_related('options').annotate(
        used=Count('options__household_preferences'))
    return render(request, 'kitchen/manage.html', {
        'site_form': site_form, 'category_form': category_form, 'option_form': option_form, 'user_form': user_form,
        'categories': categories, 'allowed_users': AllowedUser.objects.all(),
    })


@admin_required
@require_POST
def manage_option(request, pk):
    option = get_object_or_404(PreferenceOption, pk=pk)
    action = request.POST.get('action')
    if action == 'toggle':
        option.active = not option.active
        option.save(update_fields=['active'])
    elif action == 'rename':
        name = request.POST.get('name', '').strip()[:80]
        if name and not PreferenceOption.objects.filter(category=option.category, name=name).exclude(pk=pk).exists():
            option.name = name
            option.save(update_fields=['name'])
    elif action == 'delete':
        if option.household_preferences.exists():
            messages.error(request, f'{option.name} is used by households. Retire it instead.')
        else:
            option.delete()
    return redirect(reverse('manage') + f'#cat-{option.category_id}')


@admin_required
@require_POST
def manage_category(request, pk):
    category = get_object_or_404(PreferenceCategory, pk=pk)
    action = request.POST.get('action')
    if action == 'delete':
        if HouseholdPreference.objects.filter(option__category=category).exists():
            messages.error(request, f'{category.name} has options households use. Retire those options instead.')
        else:
            category.delete()
            messages.success(request, f'Deleted {category.name}.')
    elif action == 'update':
        form = CategoryForm(request.POST, instance=category, prefix=f'c{pk}')
        if form.is_valid():
            form.save()
    return redirect(reverse('manage') + '#preferences')


@admin_required
@require_POST
def manage_user(request, pk):
    allowed = get_object_or_404(AllowedUser, pk=pk)
    if allowed.pk == request.allowed_user.pk:
        messages.error(request, 'You can\'t change your own access.')
    elif request.POST.get('action') == 'delete':
        allowed.delete()
        messages.success(request, f'Removed access for {allowed.email}.')
    elif request.POST.get('action') == 'toggle_admin':
        allowed.is_admin = not allowed.is_admin
        allowed.save(update_fields=['is_admin'])
    return redirect(reverse('manage') + '#access')


# --- client pages (no login; unguessable links) -------------------------------------------------------

def client_menu(request, token):
    menu = get_object_or_404(Menu.objects.select_related('household'), share_token=token)
    if request.method == 'POST':
        comment = request.POST.get('comment', '').strip()[:4000]
        approved = request.POST.get('approved') == '1'
        if not comment and not approved:
            return redirect(menu.client_path() + '#respond')
        MenuFeedback.objects.create(menu=menu, name=request.POST.get('name', '').strip()[:120],
                                    comment=comment, approved=approved)
        if approved and menu.status != 'approved':
            menu.status = 'approved'
            menu.save(update_fields=['status'])
        return redirect(menu.client_path() + '?thanks=1#respond')
    items = list(menu.items.select_related('recipe__photo', 'photo'))
    days = []
    for item in items:
        if days and days[-1][0] == item.date:
            days[-1][1].append(item)
        else:
            days.append((item.date, [item]))
    return render(request, 'client/menu.html', {
        'menu': menu, 'days': days, 'site': SiteSettings.load(), 'thanks': request.GET.get('thanks') == '1',
        'has_dates': any(d for d, _ in days),
    })


def client_household(request, token):
    household = get_object_or_404(Household, share_token=token)
    menus = household.menus.exclude(status='draft')
    return render(request, 'client/household.html', {'household': household, 'menus': menus,
                                                     'site': SiteSettings.load()})
