from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_inventorybatch'),
    ]

    operations = [
        migrations.DeleteModel(
            name='InventoryBatch',
        ),
    ]