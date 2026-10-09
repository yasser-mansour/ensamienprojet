from django.db import migrations


def load(apps, schema_editor):
    from games.content import load_experience

    load_experience(
        apps.get_model("games", "Experience"),
        apps.get_model("games", "Mission"),
        apps.get_model("games", "Question"),
        apps.get_model("games", "AnswerOption"),
    )


class Migration(migrations.Migration):
    dependencies = [("games", "0001_initial")]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
