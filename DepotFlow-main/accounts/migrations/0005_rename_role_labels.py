from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_migrate_role_values'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('SUPER_ADMIN', 'Super Admin'),
                    ('TERRITORY_MANAGER', 'Commercial Manager'),
                    ('DEPOT_MANAGER', 'Distribution Manager'),
                    ('DEPOT_OFFICER', 'Depot Manager'),
                    ('SALESMAN', 'Salesman'),
                    ('FINANCE_OFFICER', 'Finance Officer'),
                    ('VIEWER', 'Viewer'),
                ],
                default='DEPOT_OFFICER',
                max_length=30,
            ),
        ),
    ]
