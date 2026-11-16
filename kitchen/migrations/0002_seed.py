"""Starting data: the admins who can sign in, and a starter set of preference options (editable on
the Admin page)."""
from django.conf import settings
from django.db import migrations

STARTER_PREFERENCES = [
    ('Diets', 'Ways of eating the whole household follows', [
        'Vegetarian', 'Vegan', 'Pescatarian', 'Gluten-free', 'Dairy-free', 'Low-carb / keto', 'Paleo',
        'Low-sodium', 'Kosher', 'Halal',
    ]),
    ('Allergies', 'Mark as "Allergy / never" for anything that must never be served', [
        'Peanuts', 'Tree nuts', 'Shellfish', 'Fish', 'Eggs', 'Milk', 'Wheat', 'Soy', 'Sesame',
    ]),
    ('Proteins', '', [
        'Chicken', 'Beef', 'Pork', 'Lamb', 'Turkey', 'Salmon', 'White fish', 'Shrimp', 'Tofu', 'Beans & lentils',
    ]),
    ('Cuisines', '', [
        'Italian', 'Mexican', 'Mediterranean', 'French', 'Middle Eastern', 'Indian', 'Thai', 'Japanese',
        'Chinese', 'Korean', 'American comfort',
    ]),
    ('Ingredients', 'Specific foods they love or avoid', [
        'Mushrooms', 'Cilantro', 'Olives', 'Onions', 'Garlic', 'Spicy heat', 'Coconut', 'Eggplant', 'Blue cheese',
    ]),
]


def seed(apps, schema_editor):
    AllowedUser = apps.get_model('kitchen', 'AllowedUser')
    PreferenceCategory = apps.get_model('kitchen', 'PreferenceCategory')
    PreferenceOption = apps.get_model('kitchen', 'PreferenceOption')
    SiteSettings = apps.get_model('kitchen', 'SiteSettings')

    for email in settings.INITIAL_ADMIN_EMAILS:
        if email.strip():
            AllowedUser.objects.get_or_create(email=email.strip().lower(), defaults={'is_admin': True})

    for order, (name, help_text, options) in enumerate(STARTER_PREFERENCES):
        category, _ = PreferenceCategory.objects.get_or_create(
            name=name, defaults={'help_text': help_text, 'order': order})
        for option_order, option in enumerate(options):
            PreferenceOption.objects.get_or_create(category=category, name=option, defaults={'order': option_order})

    SiteSettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [('kitchen', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
