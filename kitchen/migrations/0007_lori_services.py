"""Lori's own list of services, grouped for the website. Replaces the two starter services from 0005 if they
haven't been edited, and sets the teacher/health care discount as the site offer if no offer is set."""
from django.db import migrations

STARTERS = {
    'Weekly meals at home': 'A menu planned around your household each week, cooked in your kitchen.',
    'Dinner parties and special occasions': 'A menu for one evening, planned with you and cooked for your guests.',
}

OFFER = '25% off for teachers and health care staff'

SERVICES = [
    ('Meal planning and meal prep',
     'Breakfast, lunch, snacks and dessert, planned, shopped for and prepped.',
     'I plan the week around what your household likes, do the grocery shopping, and prep the food.\n\n'
     '- Meal planning\n- Grocery shopping\n- Meal prep\n'
     '- Grab-and-go meals (breakfast, lunch or dinner)\n- Breakfast meals\n- Lunch meals\n'
     '- Snacks\n- Desserts\n- Homemade dressings',
     ''),
    ('Breakfast week packages',
     'A week of breakfasts, ready when you are.',
     '- Overnight oats ($20 for the week)\n- Breakfast sandwiches\n'
     '- Breakfast biscuits: cheddar and chive, pepper and sausage, or feta and spinach',
     'Overnight oats: $20 a week'),
    ('Pantry, fridge and freezer',
     'Organized, stocked and kept that way.',
     '- Pantry organization\n- Pantry stocking and restocking\n- Fridge organization\n- Fridge restock\n'
     '- Freezer restock\n- An ongoing pantry list, built and kept up to date',
     ''),
    ('Healthy snack swaps',
     'Better-for-you snacks your household will actually eat.',
     '- Healthy snack swaps\n- A Costco healthy snack roundup',
     ''),
    ('Cooking classes',
     'Bringing education and fun to cooking.',
     '- Learn how to make your favorite meal ($100)\n- The science of cooking classes',
     'Your favorite meal: $100'),
    ('Pop-ups for large events',
     'Breakfast sandwiches and healthy baked goods for a crowd.',
     '- Pop-up breakfast sandwiches\n- Pop-up healthy baked goods',
     ''),
    ('Composting and sustainability',
     'Help moving your kitchen toward more sustainable habits.',
     '- Composting and compost disposal\n- Learning how composting works\n'
     '- Help moving toward more sustainable options',
     ''),
    ('AI for managing meals',
     'Simple AI workflows that make planning and managing meals easier.',
     'I\'ll show you how to build AI tools into the way you plan meals, keep lists and shop.',
     ''),
]


def apply(apps, schema_editor):
    Service = apps.get_model('kitchen', 'Service')
    SiteSettings = apps.get_model('kitchen', 'SiteSettings')
    for name, summary in STARTERS.items():
        Service.objects.filter(name=name, summary=summary).delete()
    start = Service.objects.count()
    for order, (name, summary, details, price_note) in enumerate(SERVICES, start=start + 1):
        Service.objects.get_or_create(name=name, defaults={
            'summary': summary, 'details': details, 'price_note': price_note, 'order': order})
    site, _ = SiteSettings.objects.get_or_create(pk=1)
    if not site.offer:
        site.offer = OFFER
        site.save(update_fields=['offer'])


class Migration(migrations.Migration):
    dependencies = [('kitchen', '0006_website_offer')]
    operations = [migrations.RunPython(apply, migrations.RunPython.noop)]
