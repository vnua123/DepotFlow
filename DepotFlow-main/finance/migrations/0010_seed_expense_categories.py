from django.db import migrations


EXPENSE_CATEGORIES = [
    "Car utility",
    "Mechanic",
    "Fuel",
    "Transportation",
    "Truck boys",
    "Pure water",
    "Feeding",
    "Fish",
    "Stationary",
    "Madam",
    "Salary",
    "Staff Medicals",
    "Police",
    "Miscellaneous",
    "Warehouse maintainance",
    "Electricity",
    "Accident",
]


def seed_expense_categories(apps, schema_editor):
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    for name in EXPENSE_CATEGORIES:
        ExpenseCategory.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0008_remove_bank_integration"),
    ]

    operations = [
        migrations.RunPython(
            seed_expense_categories,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
