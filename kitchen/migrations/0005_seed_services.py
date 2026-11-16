"""Starter services for the public website. Lori rewrites them on the Website page."""
from django.db import migrations

SERVICES = [
    ('Weekly meals at home',
     'A menu planned around your household each week, cooked in your kitchen.',
     'Tell me what your family loves, what it avoids and any allergies. Each week I send a menu for you to '
     'approve or change, then I do the shopping and the cooking.'),
    ('Dinner parties and special occasions',
     'A menu for one evening, planned with you and cooked for your guests.',
     'We plan the menu together around the occasion and your guests\' needs, and I take care of the rest.'),
]


def seed(apps, schema_editor):
    Service = apps.get_model('kitchen', 'Service')
    if Service.objects.exists():
        return
    for order, (name, summary, details) in enumerate(SERVICES, start=1):
        Service.objects.create(name=name, summary=summary, details=details, order=order)


class Migration(migrations.Migration):
    dependencies = [('kitchen', '0004_website')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
