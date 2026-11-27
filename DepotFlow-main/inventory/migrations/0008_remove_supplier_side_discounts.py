from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0007_alter_stockreceipt_receipt_date'),
    ]

    operations = [
        # The invoiced cost_price already reflects whatever discount,
        # rebate, or other adjustment the supplier applied before
        # billing us, so these were always redundant with it.
        migrations.RemoveField(
            model_name='stockreceiptitem',
            name='supplier_discount',
        ),
        migrations.RemoveField(
            model_name='stockreceiptitem',
            name='supplier_rebate',
        ),
        migrations.AlterField(
            model_name='promotion',
            name='level',
            field=models.CharField(
                choices=[('DEPOT_TO_CUSTOMER', 'Depot -> Customer')],
                max_length=20,
            ),
        ),
    ]
