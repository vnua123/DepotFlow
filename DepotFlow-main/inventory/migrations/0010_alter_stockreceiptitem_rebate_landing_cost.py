from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_stockreceiptitem_rebate_landing_cost'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stockreceiptitem',
            name='rebate_landing_cost',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Optional rebate-based cost per case with VAT and excise taken out. If blank, it is worked out from the cost price using NBC's workbook formula (VAT 7.5% + N10 per litre excise).",
                max_digits=12,
                null=True,
            ),
        ),
    ]
