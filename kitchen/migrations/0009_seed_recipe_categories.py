"""Starter recipe categories. Lori edits them on the Admin page."""
from django.db import migrations

CATEGORIES = ['Main', 'Side', 'Salad', 'Soup', 'Breakfast', 'Lunch', 'Snack', 'Dessert', 'Baked goods',
              'Dressing & sauce']


def seed(apps, schema_editor):
    RecipeCategory = apps.get_model('kitchen', 'RecipeCategory')
    for order, name in enumerate(CATEGORIES, start=1):
        RecipeCategory.objects.get_or_create(name=name, defaults={'order': order})


class Migration(migrations.Migration):
    dependencies = [('kitchen', '0008_meals')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
