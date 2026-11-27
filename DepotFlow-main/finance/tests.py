from django.test import TestCase

from .models import ExpenseCategory


class ExpenseCategorySeedTests(TestCase):
    def test_spreadsheet_expense_categories_are_available(self):
        expected_categories = {
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
        }

        actual_categories = set(
            ExpenseCategory.objects.filter(name__in=expected_categories)
            .values_list("name", flat=True)
        )

        self.assertSetEqual(actual_categories, expected_categories)
