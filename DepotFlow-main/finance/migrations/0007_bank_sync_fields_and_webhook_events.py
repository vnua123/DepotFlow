from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0006_bank_connections_and_transactions'),
    ]

    operations = [
        migrations.AddField(
            model_name='bankconnection',
            name='current_balance',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=16, null=True),
        ),
        migrations.AddField(
            model_name='bankconnection',
            name='balance_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='BankWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('provider', models.CharField(default='MONO', max_length=20)),
                ('event_id', models.CharField(max_length=180)),
                ('event_type', models.CharField(blank=True, max_length=120)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('processing_error', models.CharField(blank=True, max_length=500)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='bankwebhookevent',
            constraint=models.UniqueConstraint(fields=('provider', 'event_id'), name='uniq_bank_webhook_event'),
        ),
    ]
