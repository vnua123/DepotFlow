# Generated for DepotFlow NBC rebate and health-check workflows.
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('depots', '0001_initial'),
        ('inventory', '0009_stockreceiptitem_rebate_landing_cost'),
    ]
    operations = [
        migrations.CreateModel(
            name='NBCQuarterlyPlacement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('year', models.PositiveSmallIntegerField()),
                ('quarter', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(4)])),
                ('qualifying_cases', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('category', models.CharField(choices=[('STANDARD', 'Standard'), ('MAXI', 'Maxi'), ('MEGA', 'Mega')], default='STANDARD', max_length=12)),
                ('calculated_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('notes', models.TextField(blank=True)),
                ('calculated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('depot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='nbc_placements', to='depots.depot')),
            ],
            options={'ordering': ['-year', '-quarter', 'depot__name']},
        ),
        migrations.CreateModel(
            name='MonthlyHealthCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('year', models.PositiveSmallIntegerField()),
                ('month', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)])),
                ('grand_total_stock_value', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('cash_at_hand', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('git_order_released', models.DecimalField(decimal_places=2, default=0, max_digits=16, help_text='Goods in transit / order released value.')),
                ('credit_exposure_balance', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('nbc_credit_limit', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('nbc_permanent_credit', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('operator_equity_contribution_percent', models.DecimalField(decimal_places=2, default=0, max_digits=7)),
                ('empties_quantity', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('plastic_quantity', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('empties_value', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('bank_balance', models.DecimalField(decimal_places=2, default=0, max_digits=16, help_text="Manually entered from the monthly Distribution Manager health check.")),
                ('notes', models.TextField(blank=True)),
                ('completed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('completed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('depot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_health_checks', to='depots.depot')),
            ],
            options={'ordering': ['-year', '-month', 'depot__name']},
        ),
        migrations.CreateModel(
            name='MonthlyRebateAccrual',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('year', models.PositiveSmallIntegerField()),
                ('month', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)])),
                ('product_category', models.CharField(max_length=80)),
                ('qualifying_cases', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('landing_cost_total', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('rebate_rate', models.DecimalField(decimal_places=4, default=0, help_text='Percentage, e.g. 8.0000 means 8%.', max_digits=7)),
                ('estimated_amount', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('status', models.CharField(choices=[('ESTIMATED', 'Estimated'), ('CONFIRMED', 'Confirmed by NBC'), ('PAID', 'Paid'), ('VOID', 'Voided')], default='ESTIMATED', max_length=12)),
                ('calculation_notes', models.TextField(blank=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('depot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_rebate_accruals', to='depots.depot')),
                ('placement', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='monthly_accruals', to='rebates.nbcquarterlyplacement')),
                ('supplier', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='monthly_rebate_accruals', to='inventory.supplier')),
            ],
            options={'ordering': ['-year', '-month', 'product_category']},
        ),
        migrations.AddConstraint(model_name='nbcquarterlyplacement', constraint=models.UniqueConstraint(fields=('depot', 'year', 'quarter'), name='uniq_nbc_depot_year_quarter')),
        migrations.AddConstraint(model_name='monthlyhealthcheck', constraint=models.UniqueConstraint(fields=('depot', 'year', 'month'), name='uniq_health_check_depot_month')),
        migrations.AddConstraint(model_name='monthlyrebateaccrual', constraint=models.UniqueConstraint(fields=('depot', 'year', 'month', 'product_category'), name='uniq_monthly_rebate_category')),
    ]
