from django.db import migrations

EMAIL = 'lori@loraxglobal.com'


def add_admin(apps, schema_editor):
    AllowedUser = apps.get_model('kitchen', 'AllowedUser')
    AllowedUser.objects.get_or_create(email=EMAIL, defaults={'is_admin': True})


class Migration(migrations.Migration):
    dependencies = [('kitchen', '0002_seed')]
    operations = [migrations.RunPython(add_admin, migrations.RunPython.noop)]
