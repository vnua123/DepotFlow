from django.db import migrations


ROLE_RENAMES = {
    "ADMIN": "SUPER_ADMIN",
    "COMMERCIAL_MANAGER": "TERRITORY_MANAGER",
}


def rename_roles_forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")

    for old_value, new_value in ROLE_RENAMES.items():
        User.objects.filter(role=old_value).update(role=new_value)

    # Existing Django superusers should also carry the business-level
    # SUPER_ADMIN role, since createsuperuser never touches this
    # custom field and only sets is_staff/is_superuser.
    User.objects.filter(is_superuser=True).exclude(role="SUPER_ADMIN").update(role="SUPER_ADMIN")


def rename_roles_backward(apps, schema_editor):
    User = apps.get_model("accounts", "User")

    for old_value, new_value in ROLE_RENAMES.items():
        User.objects.filter(role=new_value).update(role=old_value)

    # Note: the superuser role backfill above is not reversed here,
    # since we can't reliably know what each affected user's role
    # was before the forward migration ran.


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(rename_roles_forward, rename_roles_backward),
    ]