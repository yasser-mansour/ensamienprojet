from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # Rate limiting uses the database cache in production. Creating its table during `migrate`
    # guarantees it exists even if `createcachetable` is forgotten (the command is idempotent).
    call_command("createcachetable", "ensamien_cache", verbosity=0)


class Migration(migrations.Migration):
    dependencies = []

    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
