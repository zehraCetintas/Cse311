from django.db import migrations


def assign_head_role_to_superusers(apps, schema_editor):
    User = apps.get_model("main", "User")
    User.objects.filter(is_superuser=True).update(role="HEAD")


class Migration(migrations.Migration):

    dependencies = [
        ("main", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            assign_head_role_to_superusers,
            migrations.RunPython.noop,
        ),
    ]
