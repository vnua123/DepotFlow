"""
Depot Owner finance access: sees only their own depot, can record, approve
and reverse expenses, manage supplier payments, and view supplier rebates
without recording or reversing them.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from depots.models import Depot, Territory

from inventory.models import Supplier

from .models import BusinessLedger, Expense, ExpenseCategory, SupplierPayment

R = User.Role
PASSWORD = "S0me-long-pass-123"


def make_user(username, role, depot=None, territory=None):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=role, depot=depot, territory=territory,
    )


class OwnerFinanceAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.territory = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=cls.territory, name="Mine", code="MI")
        cls.other_depot = Depot.objects.create(territory=cls.territory, name="Theirs", code="TH")

        cls.owner = make_user("owner", R.DEPOT_OWNER, depot=cls.depot)
        cls.viewer = make_user("viewer", R.VIEWER, depot=cls.depot)
        cls.dm = make_user("dm", R.DEPOT_MANAGER, depot=cls.depot)

        cls.category, _ = ExpenseCategory.objects.get_or_create(name="Fuel")
        cls.nbc = Supplier.objects.create(name="NBC")
        cls.expense = cls.make_expense(cls.depot)
        cls.other_expense = cls.make_expense(cls.other_depot)

    @classmethod
    def make_expense(cls, depot):
        return Expense.objects.create(
            depot=depot, category=cls.category, expense_date=date.today(),
            description="Diesel", amount=Decimal("5000.00"),
            payment_method=Expense.PaymentMethod.CASH,
        )

    # --- approvals ---------------------------------------------------
    def test_owner_can_approve_an_expense_in_their_depot(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("finance:expense_approve", args=[self.expense.pk]))
        self.expense.refresh_from_db()
        self.assertTrue(self.expense.approved)

    def test_owner_cannot_approve_another_depots_expense(self):
        self.client.force_login(self.owner)
        self.client.post(reverse("finance:expense_approve", args=[self.other_expense.pk]))
        self.other_expense.refresh_from_db()
        self.assertFalse(self.other_expense.approved)

    def test_viewer_still_cannot_approve(self):
        self.client.force_login(self.viewer)
        self.client.post(reverse("finance:expense_approve", args=[self.expense.pk]))
        self.expense.refresh_from_db()
        self.assertFalse(self.expense.approved)

    def test_distribution_manager_can_still_approve(self):  # DEPOT_MANAGER value
        self.client.force_login(self.dm)
        self.client.post(reverse("finance:expense_approve", args=[self.expense.pk]))
        self.expense.refresh_from_db()
        self.assertTrue(self.expense.approved)

    # --- expense recording and supplier rebate read-only access ------
    def test_owner_can_open_expense_create_form(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("finance:expense_create"))
        self.assertEqual(response.status_code, 200)

    def test_owner_can_view_supplier_rebates_but_not_create_or_reverse(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("finance:supplier_rebate_list"))
        self.assertEqual(response.status_code, 200)
        create_response = self.client.get(reverse("finance:supplier_rebate_create"))
        self.assertRedirects(create_response, reverse("finance:supplier_rebate_list"))

    def test_owner_can_open_the_supplier_payment_form(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("finance:supplier_payment_create"))
        self.assertEqual(response.status_code, 200)

    def test_owner_can_record_supplier_payment_for_their_depot(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("finance:supplier_payment_create"),
            {
                "depot": self.depot.pk,
                "supplier": self.nbc.pk,
                "stock_receipt": "",
                "payment_date": date.today().isoformat(),
                "amount": "12500.00",
                "notes": "NBC supplier payment",
            },
        )
        self.assertRedirects(response, reverse("finance:supplier_payment_list"))
        self.assertTrue(
            SupplierPayment.objects.filter(
                depot=self.depot, supplier=self.nbc, amount=Decimal("12500.00")
            ).exists()
        )

    def test_owner_can_reverse_supplier_payment_in_their_depot(self):
        payment = SupplierPayment.objects.create(
            depot=self.depot, supplier=self.nbc, payment_date=date.today(),
            amount=Decimal("2500.00"), notes="Test payment",
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("finance:supplier_payment_reverse", args=[payment.pk]),
            {"reason": "Duplicate payment"},
        )
        self.assertRedirects(response, reverse("finance:supplier_payment_list"))
        payment.refresh_from_db()
        self.assertTrue(payment.is_reversed)

    def test_owner_cannot_reverse_another_depots_supplier_payment(self):
        payment = SupplierPayment.objects.create(
            depot=self.other_depot, supplier=self.nbc, payment_date=date.today(),
            amount=Decimal("2500.00"), notes="Other depot payment",
        )
        self.client.force_login(self.owner)
        self.client.post(
            reverse("finance:supplier_payment_reverse", args=[payment.pk]),
            {"reason": "Unauthorized attempt"},
        )
        payment.refresh_from_db()
        self.assertFalse(payment.is_reversed)

    # --- confidentiality ---------------------------------------------
    def test_owner_only_sees_own_depot_in_expense_list(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("finance:expense_list"))
        listed = list(response.context["expenses"])
        self.assertIn(self.expense, listed)
        self.assertNotIn(self.other_expense, listed)

    def test_owner_ledger_is_locked_to_own_depot(self):
        BusinessLedger.objects.create(
            depot=self.other_depot, transaction_type=BusinessLedger.TransactionType.INCOME,
            transaction_date=date.today(), description="theirs", amount=Decimal("1"), reference="T-1",
        )
        self.client.force_login(self.owner)
        # Asking for the other depot is ignored, not honoured.
        response = self.client.get(reverse("finance:ledger_list"), {"depot": self.other_depot.pk})
        self.assertEqual(response.context["depot"], self.depot)
        self.assertFalse(response.context["can_switch"])
