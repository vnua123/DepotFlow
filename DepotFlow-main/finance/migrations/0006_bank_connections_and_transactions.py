# Generated for DepotFlow bank feeds and reconciliation.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('depots', '0001_initial'),
        ('finance', '0005_alter_expense_expense_date_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BankConnection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('provider', models.CharField(choices=[('MONO', 'Mono'), ('OTHER', 'Other provider')], default='MONO', max_length=20)),
                ('bank_name', models.CharField(max_length=100)),
                ('account_name', models.CharField(blank=True, max_length=160)),
                ('account_number_masked', models.CharField(blank=True, max_length=30)),
                ('currency', models.CharField(default='NGN', max_length=3)),
                ('provider_connection_id', models.CharField(blank=True, max_length=160)),
                ('provider_account_id', models.CharField(blank=True, max_length=160)),
                ('status', models.CharField(choices=[('PENDING', 'Pending setup'), ('ACTIVE', 'Connected'), ('NEEDS_REAUTH', 'Reauthorisation required'), ('ERROR', 'Connection error'), ('DISCONNECTED', 'Disconnected')], default='PENDING', max_length=20)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('last_sync_error', models.CharField(blank=True, max_length=500)),
                ('disconnected_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_bank_connections', to=settings.AUTH_USER_MODEL)),
                ('depot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bank_connections', to='depots.depot')),
            ],
            options={'ordering': ['depot__name', 'bank_name', 'created_at']},
        ),
        migrations.CreateModel(
            name='BankTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('provider_transaction_id', models.CharField(max_length=180)),
                ('transaction_date', models.DateTimeField()),
                ('description', models.TextField(blank=True)),
                ('reference', models.CharField(blank=True, max_length=180)),
                ('direction', models.CharField(choices=[('CREDIT', 'Money in'), ('DEBIT', 'Money out')], max_length=10)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=16)),
                ('currency', models.CharField(default='NGN', max_length=3)),
                ('balance_after', models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True)),
                ('reconciliation_status', models.CharField(choices=[('UNMATCHED', 'Unmatched'), ('SUGGESTED', 'Suggested match'), ('MATCHED', 'Reconciled'), ('IGNORED', 'Ignored')], default='UNMATCHED', max_length=12)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_note', models.CharField(blank=True, max_length=500)),
                ('connection', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='finance.bankconnection')),
                ('matched_ledger_entry', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='bank_transactions', to='finance.businessledger')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_bank_transactions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-transaction_date', '-id']},
        ),
        migrations.AddConstraint(
            model_name='bankconnection',
            constraint=models.UniqueConstraint(condition=~models.Q(provider_account_id=''), fields=('provider', 'provider_account_id'), name='uniq_bank_provider_account_ref'),
        ),
        migrations.AddIndex(
            model_name='bankconnection',
            index=models.Index(fields=['depot', 'status'], name='finance_ban_depot_i_72a1a9_idx'),
        ),
        migrations.AddConstraint(
            model_name='banktransaction',
            constraint=models.UniqueConstraint(fields=('connection', 'provider_transaction_id'), name='uniq_bank_tx_provider_id_per_connection'),
        ),
        migrations.AddIndex(
            model_name='banktransaction',
            index=models.Index(fields=['reconciliation_status', 'transaction_date'], name='finance_ba_reconci_4d7e3d_idx'),
        ),
        migrations.AddIndex(
            model_name='banktransaction',
            index=models.Index(fields=['connection', 'transaction_date'], name='finance_ba_connect_2d7d6b_idx'),
        ),
    ]
