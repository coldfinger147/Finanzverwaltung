from django.db import migrations


def lade(apps, schema_editor):
    from buchhaltung.grunddaten import lade_grunddaten

    lade_grunddaten(
        apps.get_model("buchhaltung", "Mandant"),
        apps.get_model("buchhaltung", "Kategorie"),
        apps.get_model("buchhaltung", "FormularZeile"),
    )


class Migration(migrations.Migration):
    dependencies = [("buchhaltung", "0001_start")]
    operations = [migrations.RunPython(lade, migrations.RunPython.noop)]
