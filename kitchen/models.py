import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from kitchen.quantities import format_amount

STANCES = [
    ('love', 'Loves'),
    ('like', 'Likes'),
    ('avoid', 'Avoids'),
    ('allergy', 'Allergy / never'),
]

SECTIONS = [
    ('produce', 'Produce'),
    ('meat', 'Meat & seafood'),
    ('dairy', 'Dairy & eggs'),
    ('bakery', 'Bakery'),
    ('pantry', 'Pantry & dry goods'),
    ('spices', 'Spices & seasonings'),
    ('frozen', 'Frozen'),
    ('other', 'Other'),
]
SECTION_KEYS = [key for key, _ in SECTIONS]


class AllowedUser(models.Model):
    """A Google account that may sign in. Admins can also use the Admin page and Django admin."""
    email = models.EmailField(unique=True)
    is_admin = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['email']

    def __str__(self):
        return self.email


class SiteSettings(models.Model):
    """Business details used on client menus and emails. A single row."""
    business_name = models.CharField(max_length=120, default='Cooking with the Lorax')
    chef_name = models.CharField(max_length=120, default='Lori Weischedel')
    contact_email = models.EmailField(default='lweischedel@gmail.com')
    menu_footer = models.TextField(
        blank=True, default='Questions or changes? Reply to this email or leave a note on the menu page.',
        help_text='Shown at the bottom of every client menu and menu email.')

    # Public website (cookingwiththe.loraxglobal.com). Edited on the Website page.
    tagline = models.CharField(
        max_length=160, default='Home-cooked meals, planned around your household.',
        help_text='The big headline on the home page.')
    intro = models.TextField(
        default='Menus built around what your family loves, and what it can\'t eat. '
                'You approve the menu, I shop and cook.',
        help_text='A sentence or two under the headline.')
    about = models.TextField(
        blank=True, help_text='The About page. Leave a blank line between paragraphs.')
    service_area = models.CharField(max_length=200, blank=True, help_text='e.g. Denver and the west suburbs')
    phone = models.CharField(max_length=40, blank=True, help_text='Shown on the website. Leave blank to hide it.')
    google_tag_id = models.CharField(
        max_length=40, blank=True, verbose_name='Google tag ID',
        validators=[RegexValidator(r'^(AW|G|GT)-[A-Za-z0-9]+$', 'Looks like AW-123456789 or G-ABC123.')],
        help_text='From Google Ads (AW-…) or Analytics (G-…). Adds the Google tag to the public website.')
    google_ads_conversion = models.CharField(
        max_length=80, blank=True, verbose_name='Google Ads conversion',
        validators=[RegexValidator(r'^AW-\d+/[A-Za-z0-9_-]+$', 'Looks like AW-123456789/AbCdEf.')],
        help_text='The conversion "send to" value. Counted when someone sends the contact form.')

    class Meta:
        verbose_name_plural = 'site settings'

    def __str__(self):
        return self.business_name

    @classmethod
    def load(cls) -> 'SiteSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class PreferenceCategory(models.Model):
    """A group of preference options, e.g. Diets, Allergies, Cuisines, Proteins."""
    name = models.CharField(max_length=80, unique=True)
    help_text = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'preference categories'

    def __str__(self):
        return self.name


class PreferenceOption(models.Model):
    category = models.ForeignKey(PreferenceCategory, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=80)
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True, help_text='Retired options stay on households that already use them.')

    class Meta:
        ordering = ['category__order', 'category__name', 'order', 'name']
        unique_together = [('category', 'name')]

    def __str__(self):
        return f'{self.category.name}: {self.name}'


class Household(models.Model):
    """A client. Menus, contacts, notes and preferences all hang off a household."""
    name = models.CharField(max_length=120)
    address = models.TextField(blank=True)
    default_servings = models.PositiveIntegerField(default=4)
    preference_notes = models.TextField(blank=True, help_text='Anything the options don\'t cover.')
    archived = models.BooleanField(default=False)
    # Unguessable link to the household's client page (all menus they've been sent). No login needed.
    share_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['archived', 'name']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('household', args=[self.pk])

    def client_url(self):
        return f'{settings.PUBLIC_BASE_URL}{reverse("client_household", args=[self.share_token])}'

    def preferences_by_stance(self) -> dict[str, list['HouseholdPreference']]:
        grouped: dict[str, list] = {key: [] for key, _ in STANCES}
        for pref in self.preferences.select_related('option__category'):
            grouped[pref.stance].append(pref)
        return grouped

    def menu_recipients(self):
        return self.contacts.filter(receives_menus=True).exclude(email='')


class HouseholdPreference(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name='preferences')
    option = models.ForeignKey(PreferenceOption, on_delete=models.CASCADE, related_name='household_preferences')
    stance = models.CharField(max_length=10, choices=STANCES)

    class Meta:
        unique_together = [('household', 'option')]
        ordering = ['option__category__order', 'option__order', 'option__name']


class Contact(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    role = models.CharField(max_length=60, blank=True, help_text='e.g. Primary, Spouse, Assistant')
    receives_menus = models.BooleanField(default=True)

    class Meta:
        ordering = ['-receives_menus', 'name']

    def __str__(self):
        return self.name


class Note(models.Model):
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name='notes')
    body = models.TextField()
    pinned = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pinned', '-created_at']


class DishPhoto(models.Model):
    """A photo of one of Lori's dishes. Bytes live in the database so they survive redeploys.

    Served publicly at an unguessable URL so client menus and emails can show them.
    """
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    image = models.BinaryField()
    content_type = models.CharField(max_length=40, default='image/jpeg')
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    caption = models.CharField(max_length=200, blank=True)
    on_website = models.BooleanField(default=False, verbose_name='Show on website',
                                     help_text='Show this photo in the public website\'s gallery.')
    recipe = models.ForeignKey('Recipe', null=True, blank=True, on_delete=models.SET_NULL, related_name='photos')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.caption or f'Photo {self.pk}'

    def url(self):
        return reverse('photo_file', args=[self.token])

    def label(self) -> str:
        """The caption, else the recipe's title, else ''."""
        return self.caption or (self.recipe.title if self.recipe_id and self.recipe else '')

    def absolute_url(self):
        return f'{settings.PUBLIC_BASE_URL}{self.url()}'


class Recipe(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, help_text='A sentence or two clients will see on menus.')
    servings = models.PositiveIntegerField(default=4)
    prep_minutes = models.PositiveIntegerField(null=True, blank=True)
    cook_minutes = models.PositiveIntegerField(null=True, blank=True)
    tags = models.CharField(max_length=300, blank=True, help_text='Comma separated, e.g. gluten-free, dinner, freezer-friendly')
    chef_notes = models.TextField(blank=True, help_text='Private. Never shown to clients.')
    source_url = models.URLField(max_length=1000, blank=True)
    source_note = models.CharField(max_length=200, blank=True)
    photo = models.ForeignKey(DishPhoto, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                              help_text='The default photo for this recipe on menus.')
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('recipe', args=[self.pk])

    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    def total_minutes(self) -> int | None:
        if self.prep_minutes is None and self.cook_minutes is None:
            return None
        return (self.prep_minutes or 0) + (self.cook_minutes or 0)


class Ingredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='ingredients')
    order = models.PositiveIntegerField(default=0)
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    quantity_max = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                       help_text='Upper end of a range, e.g. the 3 in "2-3 cloves".')
    unit = models.CharField(max_length=40, blank=True)
    name = models.CharField(max_length=200)
    note = models.CharField(max_length=200, blank=True, help_text='Prep, e.g. "finely chopped"')
    section = models.CharField(max_length=10, choices=SECTIONS, default='other')

    class Meta:
        ordering = ['order', 'pk']

    def amount(self, factor: Decimal = Decimal(1)) -> str:
        """Quantity and range scaled by `factor`, as kitchen text ("1 ½", "2–3"), or ''."""
        if self.quantity is None:
            return ''
        low = format_amount(self.quantity * factor)
        if self.quantity_max is not None and self.quantity_max != self.quantity:
            return f'{low}–{format_amount(self.quantity_max * factor)}'
        return low

    def __str__(self):
        parts = [self.amount(), self.unit, self.name]
        text = ' '.join(p for p in parts if p)
        return f'{text}, {self.note}' if self.note else text


class Step(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField(default=0)
    text = models.TextField()

    class Meta:
        ordering = ['order', 'pk']


class Menu(models.Model):
    """A meal plan for one household, sent to its contacts for review."""
    STATUSES = [('draft', 'Draft'), ('sent', 'Sent'), ('approved', 'Approved')]

    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name='menus')
    title = models.CharField(max_length=200)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    intro = models.TextField(blank=True, help_text='A note to the client at the top of the menu.')
    status = models.CharField(max_length=10, choices=STATUSES, default='draft')
    # Unguessable link to this menu. No login needed.
    share_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-starts_on', '-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('menu', args=[self.pk])

    def client_path(self):
        return reverse('client_menu', args=[self.share_token])

    def client_url(self):
        return f'{settings.PUBLIC_BASE_URL}{self.client_path()}'

    def date_range(self) -> str:
        if self.starts_on and self.ends_on and self.ends_on != self.starts_on:
            if self.starts_on.year == self.ends_on.year:
                return f'{self.starts_on:%b} {self.starts_on.day} – {self.ends_on:%b} {self.ends_on.day}, {self.ends_on.year}'
            return (f'{self.starts_on:%b} {self.starts_on.day}, {self.starts_on.year} – '
                    f'{self.ends_on:%b} {self.ends_on.day}, {self.ends_on.year}')
        day = self.starts_on or self.ends_on
        return f'{day:%A, %B} {day.day}, {day.year}' if day else ''


class MenuItem(models.Model):
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='items')
    order = models.PositiveIntegerField(default=0)
    date = models.DateField(null=True, blank=True)
    course = models.CharField(max_length=60, blank=True, help_text='e.g. Dinner, Starter, Dessert')
    recipe = models.ForeignKey(Recipe, null=True, blank=True, on_delete=models.SET_NULL, related_name='menu_items')
    title = models.CharField(max_length=200, blank=True, help_text='Leave blank to use the recipe title.')
    description = models.TextField(blank=True, help_text='Leave blank to use the recipe description.')
    servings = models.PositiveIntegerField(default=4)
    photo = models.ForeignKey(DishPhoto, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                              help_text='Leave blank to use the recipe photo.')

    class Meta:
        ordering = ['date', 'order', 'pk']

    def display_title(self) -> str:
        return self.title or (self.recipe.title if self.recipe else 'Untitled dish')

    def display_description(self) -> str:
        return self.description or (self.recipe.description if self.recipe else '')

    def display_photo(self) -> DishPhoto | None:
        return self.photo or (self.recipe.photo if self.recipe else None)

    def scale(self) -> Decimal:
        if not self.recipe or not self.recipe.servings:
            return Decimal(1)
        return Decimal(self.servings) / Decimal(self.recipe.servings)


class MenuFeedback(models.Model):
    """A client's response on the public menu page."""
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='feedback')
    name = models.CharField(max_length=120, blank=True)
    approved = models.BooleanField(default=False)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']


class ShoppingItem(models.Model):
    """One line of a menu's shopping list. Built from the menu's recipes; extra lines can be added by hand."""
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='shopping_items')
    section = models.CharField(max_length=10, choices=SECTIONS, default='other')
    name = models.CharField(max_length=200)
    amount = models.CharField(max_length=200, blank=True)
    used_in = models.CharField(max_length=500, blank=True)
    checked = models.BooleanField(default=False)
    manual = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']


class Service(models.Model):
    """Something Lori offers, listed on the public website's Services page."""
    name = models.CharField(max_length=120)
    summary = models.CharField(max_length=300, help_text='One line, shown on the home page.')
    details = models.TextField(blank=True, help_text='The Services page. Leave a blank line between paragraphs.')
    price_note = models.CharField(max_length=120, blank=True, help_text='Optional, e.g. "From $X per week"')
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True, help_text='Hidden from the website when off.')

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Inquiry(models.Model):
    """A message from the public website's contact form."""
    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    service = models.CharField(max_length=120, blank=True)
    household_size = models.PositiveIntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(default=False)

    class Meta:
        ordering = ['handled', '-created_at']
        verbose_name_plural = 'inquiries'

    def __str__(self):
        return f'{self.name} ({self.created_at:%b %-d})'
