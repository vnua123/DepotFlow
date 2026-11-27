from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('inventory', '0008_remove_supplier_side_discounts')]
    operations = [
        migrations.AddField(
            model_name='stockreceiptitem',
            name='rebate_landing_cost',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Optional NBC rebate basis per case, excluding tax add-ons. If blank, rebate calculations use cost_price without adding tax.', max_digits=12, null=True),
        ),
        migrations.AlterField(
            model_name='stockreceiptitem',
            name='cost_price',
            field=models.DecimalField(decimal_places=2, help_text='Recorded acquisition/receipt cost. Do not add tax again if the entered cost is already tax-inclusive.', max_digits=12),
        ),
    ]
