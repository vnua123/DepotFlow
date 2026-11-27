from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('depots', '0001_initial'),
        ('rebates', '0002_healthcheck_stock_cases'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyProfitability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('year', models.PositiveSmallIntegerField()),
                ('month', models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])),
                ('target_reinvestment_percent', models.DecimalField(decimal_places=2, default=Decimal('20.00'), help_text='Minimum percentage of positive monthly net profit to reinvest.', max_digits=5, validators=[MinValueValidator(0), MaxValueValidator(100)])),
                ('amount_reinvested', models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Amount actually put back into the business during this month.', max_digits=16, validators=[MinValueValidator(0)])),
                ('notes', models.TextField(blank=True)),
                ('depot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_profitability_records', to='depots.depot')),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-year', '-month', 'depot__name']},
        ),
        migrations.AddConstraint(
            model_name='monthlyprofitability',
            constraint=models.UniqueConstraint(fields=('depot', 'year', 'month'), name='uniq_profitability_depot_month'),
        ),
    ]
