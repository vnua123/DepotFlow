from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ('rebates', '0003_monthlyprofitability'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='assessment_year',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='assessment_quarter',
            field=models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(4)]),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='calculated_category',
            field=models.CharField(blank=True, choices=[('STANDARD', 'Standard'), ('MAXI', 'Maxi'), ('MEGA', 'Mega')], max_length=12, null=True),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='is_initial',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='is_manual_initial',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='reason',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='approved_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='nbcquarterlyplacement', name='approved_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_nbc_placements', to=settings.AUTH_USER_MODEL),
        ),
    ]
