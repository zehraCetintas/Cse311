from django.db import migrations, models


def assign_defaults(apps, schema_editor):
    Student = apps.get_model("main", "Student")
    Student.objects.filter(models.Q(faculty__isnull=True) | models.Q(faculty="")).update(faculty="Engineering")
    Student.objects.filter(models.Q(department__isnull=True) | models.Q(department="")).update(department="Computer Engineering")


class Migration(migrations.Migration):
    dependencies = [("main", "0004_user_profile_picture")]
    operations = [
        migrations.AlterField(model_name="student", name="faculty", field=models.CharField(blank=True, default="Engineering", max_length=255)),
        migrations.AlterField(model_name="student", name="department", field=models.CharField(blank=True, default="Computer Engineering", max_length=255)),
        migrations.RunPython(assign_defaults, migrations.RunPython.noop),
    ]
