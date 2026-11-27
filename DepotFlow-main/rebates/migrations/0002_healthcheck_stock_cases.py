from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rebates', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyhealthcheck',
            name='grand_total_stock_cases',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Stock quantity in cases, as shown beside the stock value on the health-check sheet.',
                max_digits=14,
            ),
        ),
        migrations.AlterField(
            model_name='monthlyhealthcheck',
            name='credit_exposure_balance',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Enter exactly as it appears on the health-check sheet (a negative figure is allowed).',
                max_digits=16,
            ),
        ),
    ]
