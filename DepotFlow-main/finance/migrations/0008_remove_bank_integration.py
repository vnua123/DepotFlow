from django.db import migrations


class Migration(migrations.Migration):
    """Drops the bank integration tables. Back up the database before applying."""

    dependencies = [
        ('finance', '0007_bank_sync_fields_and_webhook_events'),
    ]

    operations = [
        migrations.DeleteModel(name='BankTransaction'),
        migrations.DeleteModel(name='BankWebhookEvent'),
        migrations.DeleteModel(name='BankConnection'),
    ]
