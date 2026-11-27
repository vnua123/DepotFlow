from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from depots.models import Depot, Territory
from finance.models import (
    BusinessLedger, Expense, ExpenseCategory, SupplierRebate,
)
from inventory.models import Product, Supplier
from operations.models import Vehicle, VehicleLoad, VehicleLoadItem, VehicleSalesman
from sales.models import Sale, SaleItem
from . import services


class ReportServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        territory = Territory.objects.create(name="Reports Territory")
        cls.depot = Depot.objects.create(
            territory=territory, name="Reports Depot", code="RPT-01"
        )
        cls.vehicle = Vehicle.objects.create(
            depot=cls.depot, registration_number="RPT-001", vehicle_name="Report Van"
        )
        cls.salesman = VehicleSalesman.objects.create(
            name="Report Salesman", employee_id="REPORT-SM-001", depot=cls.depot,
            vehicle=cls.vehicle,
        )
        cls.product = Product.objects.create(
            sku="RPT-SKU-001", name="Report Beverage", category="Sparkling",
            package_type="CRATE", volume="50cl", pack_size=24,
        )

    def setUp(self):
        self.load = VehicleLoad.objects.create(
            salesman=self.salesman, vehicle=self.vehicle, depot=self.depot,
            load_date=date(2026, 11, 20),
        )
        VehicleLoadItem.objects.bulk_create([
            VehicleLoadItem(vehicle_load=self.load, product=self.product, quantity=20)
        ])

    def make_sale(self, *, finalized=True, sale_date=date(2026, 11, 20), quantity=4):
        sale = Sale.objects.create(
            vehicle_load=self.load, salesman=self.salesman, sale_date=sale_date
        )
        with patch("sales.models.get_current_acquisition_cost", return_value=Decimal("60.00")), \
             patch("sales.models.get_current_selling_price", return_value=Decimal("100.00")):
            SaleItem.objects.create(
                sale=sale, product=self.product, quantity=quantity,
                discount_applied=Decimal("5.00"),
            )
        if finalized:
            sale.finalize()
            sale.refresh_from_db()
        return sale

    def test_daily_sales_report_uses_finalized_sales_only(self):
        self.make_sale(finalized=True, quantity=4)
        self.make_sale(finalized=False, quantity=3)

        report = services.get_daily_sales_report(self.depot, date(2026, 11, 20))

        self.assertEqual(report["total_quantity"], 4)
        self.assertEqual(report["total_revenue"], Decimal("380.00"))
        self.assertEqual(report["total_cost"], Decimal("240.00"))
        self.assertEqual(report["total_profit"], Decimal("140.00"))
        self.assertEqual(len(report["by_product"]), 1)
        self.assertEqual(report["by_product"][0]["quantity"], 4)

    def test_sales_summary_respects_date_range(self):
        self.make_sale(finalized=True, sale_date=date(2026, 11, 20), quantity=4)
        self.make_sale(finalized=True, sale_date=date(2026, 11, 21), quantity=2)

        report = services.get_sales_summary_for_range(
            self.depot, date(2026, 11, 20), date(2026, 11, 20)
        )

        self.assertEqual(report["total_quantity"], 4)
        self.assertEqual(report["total_revenue"], Decimal("380.00"))

    def test_net_profit_is_supplier_rebates_received_less_expenses(self):
        self.make_sale(finalized=True, quantity=4)
        category = ExpenseCategory.objects.create(name="Rent")
        Expense.objects.create(
            depot=self.depot, category=category,
            expense_date=date(2026, 11, 20), description="Depot rent",
            amount=Decimal("250.00"), payment_method=Expense.PaymentMethod.CASH,
        )
        supplier = Supplier.objects.create(name="NBC")
        SupplierRebate.objects.create(
            depot=self.depot, supplier=supplier, rebate_date=date(2026, 11, 20),
            amount=Decimal("600.00"), description="Monthly NBC rebate",
        )

        report = services.get_net_profit_report(
            self.depot, date(2026, 11, 1), date(2026, 11, 30)
        )

        self.assertEqual(report["revenue"], Decimal("380.00"))
        self.assertEqual(report["cost"], Decimal("240.00"))
        self.assertEqual(report["gross_profit"], Decimal("140.00"))
        self.assertEqual(report["total_expenses"], Decimal("250.00"))
        self.assertEqual(report["total_rebates"], Decimal("600.00"))
        self.assertEqual(report["net_profit"], Decimal("350.00"))

    def test_reversed_expense_and_rebate_are_excluded_from_reports(self):
        category = ExpenseCategory.objects.create(name="Utilities")
        expense = Expense.objects.create(
            depot=self.depot, category=category,
            expense_date=date(2026, 11, 20), description="Power bill",
            amount=Decimal("100.00"), payment_method=Expense.PaymentMethod.CASH,
        )
        supplier = Supplier.objects.create(name="NBC")
        rebate = SupplierRebate.objects.create(
            depot=self.depot, supplier=supplier, rebate_date=date(2026, 11, 20),
            amount=Decimal("400.00"), description="Rebate",
        )
        expense.reverse(reason="Incorrect expense")
        rebate.reverse(reason="Incorrect rebate")

        self.assertEqual(services.get_expense_report(self.depot)["total_expenses"], Decimal("0.00"))
        self.assertEqual(services.get_supplier_rebate_report(self.depot)["total_rebates"], Decimal("0.00"))

    def test_business_ledger_summary_groups_transaction_types(self):
        BusinessLedger.objects.create(
            depot=self.depot, transaction_type=BusinessLedger.TransactionType.INCOME,
            transaction_date=date(2026, 11, 20), description="Sales",
            amount=Decimal("300.00"), reference="IN-1",
        )
        BusinessLedger.objects.create(
            depot=self.depot, transaction_type=BusinessLedger.TransactionType.EXPENSE,
            transaction_date=date(2026, 11, 20), description="Expense",
            amount=Decimal("100.00"), reference="EX-1",
        )

        report = services.get_business_ledger_summary(
            depot=self.depot, date_from=date(2026, 11, 20), date_to=date(2026, 11, 20)
        )
        totals = {row["transaction_type"]: row["total"] for row in report["by_type"]}
        self.assertEqual(totals[BusinessLedger.TransactionType.INCOME], Decimal("300.00"))
        self.assertEqual(totals[BusinessLedger.TransactionType.EXPENSE], Decimal("100.00"))

    def test_salesman_target_progress_counts_finalized_sales_only(self):
        from operations.models import SalesTarget

        SalesTarget.objects.create(
            salesman=self.salesman, year=2026, month=11, target_quantity=100
        )
        self.make_sale(finalized=True, quantity=4)
        self.make_sale(finalized=False, quantity=3)

        progress = services.get_salesman_target_progress(self.salesman, 2026, 11)

        self.assertTrue(progress["has_target"])
        self.assertEqual(progress["target_quantity"], 100)
        self.assertEqual(progress["sold_quantity"], 4)
        self.assertEqual(progress["balance"], 96)


@override_settings(SECURE_SSL_REDIRECT=False)
class ReportAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.territory = Territory.objects.create(name="Access Territory")
        cls.depot_a = Depot.objects.create(
            territory=cls.territory, name="Depot A", code="ACC-A"
        )
        cls.depot_b = Depot.objects.create(
            territory=cls.territory, name="Depot B", code="ACC-B"
        )
        cls.user = User.objects.create_user(
            username="report-manager", password="test-pass-123",
            role=User.Role.DEPOT_MANAGER, depot=cls.depot_a,
        )

    def test_depot_report_rejects_access_to_another_depot(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("reports:daily_sales_report", args=[self.depot_b.pk]),
            {"date": "2026-11-20"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "You do not have access to that depot.")

    def test_depot_report_allows_access_to_assigned_depot(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("reports:daily_sales_report", args=[self.depot_a.pk]),
            {"date": "2026-11-20"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["depot"], self.depot_a.name)
