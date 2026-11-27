"""Depot Owner overview: live figures, month-to-date figures and the saved health-check figures."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from depots.models import Depot, Territory
from finance.models import Expense, ExpenseCategory, SupplierRebate
from inventory.models import Product, StockReceipt, StockReceiptItem, Supplier
from operations.models import Vehicle, VehicleLoad, VehicleLoadItem, VehicleSalesman
from rebates.models import MonthlyHealthCheck, MonthlyProfitability, MonthlyRebateAccrual
from sales.models import Sale, SaleItem

from . import owner_overview

R = User.Role
PASSWORD = "S0me-long-pass-123"
D = Decimal


class OwnerOverviewBase(TestCase):
    TODAY = date(2026, 11, 25)

    @classmethod
    def setUpTestData(cls):
        territory = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=territory, name="Mine", code="MI")
        cls.other_depot = Depot.objects.create(territory=territory, name="Theirs", code="TH")
        cls.owner = User.objects.create_user("owner", password=PASSWORD, role=R.DEPOT_OWNER, depot=cls.depot)
        cls.manager = User.objects.create_user("dm", password=PASSWORD, role=R.DEPOT_MANAGER, depot=cls.depot)

        cls.nbc = Supplier.objects.create(name="NBC")
        cls.product = Product.objects.create(
            sku="SKU-1", name="Cola 50cl", category="Sparkling",
            package_type="CRATE", volume="50cl", pack_size=24,
        )
        cls.category, _ = ExpenseCategory.objects.get_or_create(name="Fuel")

        receipt = StockReceipt.objects.create(
            supplier=cls.nbc, depot=cls.depot, invoice_number="INV-1",
            receipt_date=date(2026, 11, 1), total_amount=D("6000.00"),
        )
        StockReceiptItem.objects.create(
            stock_receipt=receipt, product=cls.product, quantity=100, cost_price=D("60.00"),
        )

        cls.vehicle = Vehicle.objects.create(depot=cls.depot, registration_number="V-1", vehicle_name="Van")
        cls.salesman = VehicleSalesman.objects.create(
            name="Sam", employee_id="E-1", depot=cls.depot, vehicle=cls.vehicle,
        )

    def make_load(self, load_date, quantity=20):
        load = VehicleLoad.objects.create(
            salesman=self.salesman, vehicle=self.vehicle, depot=self.depot, load_date=load_date,
        )
        VehicleLoadItem.objects.create(vehicle_load=load, product=self.product, quantity=quantity)
        return load

    def make_expense(self, amount, day, approved=True, depot=None):
        return Expense.objects.create(
            depot=depot or self.depot, category=self.category, expense_date=day,
            description="x", amount=D(amount), payment_method=Expense.PaymentMethod.CASH,
            approved=approved,
        )

    def make_rebate(self, amount, day, depot=None):
        return SupplierRebate.objects.create(
            depot=depot or self.depot, supplier=self.nbc, rebate_date=day,
            amount=D(amount), description="NBC rebate",
        )

    def check(self, year, month, stock="0", cash="0", git="0", exposure="0", depot=None, **extra):
        return MonthlyHealthCheck.objects.create(
            depot=depot or self.depot, year=year, month=month,
            grand_total_stock_value=D(stock), cash_at_hand=D(cash),
            git_order_released=D(git), credit_exposure_balance=D(exposure), **extra,
        )


class LiveFigureTests(OwnerOverviewBase):
    def test_stock_in_the_warehouse_and_on_the_trucks(self):
        self.make_load(date(2026, 11, 25), quantity=20)
        live = owner_overview.get_owner_overview(self.depot, self.TODAY)["live"]
        self.assertEqual(live["stock_units"], 80)
        self.assertEqual(live["stock_value"], D("4800.00"))
        self.assertEqual(live["on_trucks"], {"value": D("1200.00"), "units": 20})
        self.assertEqual(live["total_stock_value"], D("6000.00"))
        self.assertEqual(live["open_loads"], 1)
        self.assertEqual(live["overdue_loads"], 0)

    def test_sold_stock_leaves_the_trucks_and_old_open_loads_are_flagged(self):
        load = self.make_load(date(2026, 11, 20), quantity=20)
        sale = Sale.objects.create(vehicle_load=load, salesman=self.salesman, sale_date=date(2026, 11, 20))
        with patch("sales.models.get_current_acquisition_cost", return_value=D("60.00")), \
             patch("sales.models.get_current_selling_price", return_value=D("100.00")):
            SaleItem.objects.create(sale=sale, product=self.product, quantity=5)
        sale.finalize()

        overview = owner_overview.get_owner_overview(self.depot, self.TODAY)
        self.assertEqual(overview["live"]["on_trucks"]["units"], 15)
        self.assertEqual(overview["live"]["on_trucks"]["value"], D("900.00"))
        self.assertEqual(overview["live"]["overdue_loads"], 1)
        self.assertTrue(any("still open from an earlier day" in a for a in overview["alerts"]))

    def test_pending_expenses_are_counted_and_reversed_or_approved_ones_are_not(self):
        self.make_expense("100.00", self.TODAY, approved=False)
        self.make_expense("50.50", self.TODAY, approved=False)
        self.make_expense("999.00", self.TODAY, approved=True)
        self.make_expense("70.00", self.TODAY, approved=False, depot=self.other_depot)
        overview = owner_overview.get_owner_overview(self.depot, self.TODAY)
        self.assertEqual(overview["live"]["pending_expense_count"], 2)
        self.assertEqual(overview["live"]["pending_expense_total"], D("150.50"))
        self.assertTrue(any("2 expenses waiting for approval" in a for a in overview["alerts"]))

    def test_an_empty_depot_shows_zeros_not_errors(self):
        overview = owner_overview.get_owner_overview(self.other_depot, self.TODAY)
        self.assertEqual(overview["live"]["stock_value"], D("0.00"))
        self.assertEqual(overview["live"]["on_trucks"]["units"], 0)
        self.assertIsNone(overview["working_capital"])
        self.assertEqual(overview["reinvestment"], [])


class MonthToDateTests(OwnerOverviewBase):
    def test_net_profit_is_rebates_received_less_expenses_this_month_only(self):
        self.make_expense("250.00", date(2026, 11, 10))
        self.make_expense("900.00", date(2026, 10, 30))          # last month: excluded
        self.make_rebate("600.00", date(2026, 11, 12))
        self.make_rebate("5000.00", date(2026, 10, 12))          # last month: excluded
        month = owner_overview.get_owner_overview(self.depot, self.TODAY)["month"]
        self.assertEqual(month["expenses"], D("250.00"))
        self.assertEqual(month["rebates_received"], D("600.00"))
        self.assertEqual(month["net_profit"], D("350.00"))
        self.assertEqual(month["required_reinvestment_to_date"], D("70.00"))   # default 20%
        self.assertEqual(month["top_expense_categories"][0]["category__name"], "Fuel")

    def test_required_reinvestment_uses_the_recorded_target_and_is_zero_when_not_profitable(self):
        self.make_expense("250.00", date(2026, 11, 10))
        self.make_rebate("600.00", date(2026, 11, 12))
        MonthlyProfitability.objects.create(
            depot=self.depot, year=2026, month=11, target_reinvestment_percent=D("30.00"))
        month = owner_overview.get_owner_overview(self.depot, self.TODAY)["month"]
        self.assertEqual(month["required_reinvestment_to_date"], D("105.00"))

        self.make_expense("5000.00", date(2026, 11, 11))
        month = owner_overview.get_owner_overview(self.depot, self.TODAY)["month"]
        self.assertLess(month["net_profit"], 0)
        self.assertEqual(month["required_reinvestment_to_date"], D("0.00"))

    def test_expected_rebate_is_shown_only_once_it_has_been_calculated(self):
        self.assertIsNone(owner_overview.get_owner_overview(self.depot, self.TODAY)["month"]["expected_rebate"])
        MonthlyRebateAccrual.objects.create(
            depot=self.depot, supplier=self.nbc, year=2026, month=11,
            product_category="SPARKLING", estimated_amount=D("1234.50"),
        )
        month = owner_overview.get_owner_overview(self.depot, self.TODAY)["month"]
        self.assertEqual(month["expected_rebate"], D("1234.50"))
        self.assertIsNotNone(month["expected_rebate_as_of"])


class WorkingCapitalTests(OwnerOverviewBase):
    def test_uses_the_latest_health_check_and_compares_with_the_one_before(self):
        self.check(2026, 9, stock="1000", cash="500")
        self.check(2026, 10, stock="4000", cash="1000", git="500", exposure="-100",
                   grand_total_stock_cases=D("40"), git_order_released_cases=D("5"))
        wc = owner_overview.get_owner_overview(self.depot, self.TODAY)["working_capital"]
        self.assertEqual(wc["period"], date(2026, 10, 1))
        self.assertEqual(wc["total"], D("5500.00"))
        self.assertEqual(wc["operator_owned"], D("5600.00"))
        self.assertEqual(wc["change"], D("4000.00"))             # 5,500 - 1,500
        self.assertEqual(wc["previous_period"], date(2026, 9, 1))
        self.assertIsNone(wc["credit_utilization"])              # no credit limit recorded
        self.assertFalse(wc["is_stale"])

    def test_live_stock_is_compared_with_the_stock_the_health_check_recorded(self):
        self.check(2026, 10, stock="4000")
        wc = owner_overview.get_owner_overview(self.depot, self.TODAY)["working_capital"]
        self.assertEqual(wc["stock_change_since_check"], D("2000.00"))       # 100 x 60 = 6,000 now - 4,000 then

    def test_an_old_health_check_is_marked_stale_and_flagged(self):
        self.check(2026, 8, stock="1000")
        overview = owner_overview.get_owner_overview(self.depot, self.TODAY)
        self.assertTrue(overview["working_capital"]["is_stale"])
        self.assertTrue(any("more than a month old" in a for a in overview["alerts"]))

    def test_no_health_check_is_flagged(self):
        overview = owner_overview.get_owner_overview(self.depot, self.TODAY)
        self.assertTrue(any("No monthly health check" in a for a in overview["alerts"]))

    def test_other_depots_health_checks_are_not_used(self):
        self.check(2026, 10, stock="9999", depot=self.other_depot)
        self.assertIsNone(owner_overview.get_owner_overview(self.depot, self.TODAY)["working_capital"])


class ReinvestmentTests(OwnerOverviewBase):
    def test_reinvestment_is_the_rise_in_working_capital_to_the_next_health_check(self):
        self.make_expense("100.00", date(2026, 10, 5))
        self.make_rebate("600.00", date(2026, 10, 20))
        MonthlyProfitability.objects.create(depot=self.depot, year=2026, month=10,
                                            target_reinvestment_percent=D("20.00"))
        self.check(2026, 10, stock="800", cash="200")            # total 1,000
        self.check(2026, 11, stock="1000", cash="300")           # total 1,300
        row = owner_overview.get_owner_overview(self.depot, self.TODAY)["reinvestment"][0]
        self.assertEqual(row["net_profit"], D("500.00"))
        self.assertEqual(row["required"], D("100.00"))
        self.assertEqual(row["observed"], D("300.00"))
        self.assertEqual(row["actual_percent"], D("60.00"))
        self.assertFalse(row["pending"])
        self.assertFalse(row["flagged"])
        self.assertEqual(row["status"], "met")

    def test_below_target_and_waiting_for_the_next_check(self):
        self.make_rebate("1000.00", date(2026, 10, 20))
        MonthlyProfitability.objects.create(depot=self.depot, year=2026, month=10,
                                            target_reinvestment_percent=D("50.00"))
        self.check(2026, 10, stock="1000")
        row = owner_overview.get_owner_overview(self.depot, self.TODAY)["reinvestment"][0]
        self.assertTrue(row["pending"])                          # November's check is not in yet
        self.assertEqual(row["status"], "pending")
        self.assertIsNone(row["observed"])

        self.check(2026, 11, stock="1100")                        # only +100 against 500 required
        row = owner_overview.get_owner_overview(self.depot, self.TODAY)["reinvestment"][0]
        self.assertFalse(row["pending"])
        self.assertTrue(row["flagged"])
        self.assertEqual(row["status"], "below")

    def test_a_month_without_profit_has_nothing_to_reinvest(self):
        MonthlyProfitability.objects.create(depot=self.depot, year=2026, month=10)
        self.check(2026, 10, stock="1000")
        self.check(2026, 11, stock="5000")
        row = owner_overview.get_owner_overview(self.depot, self.TODAY)["reinvestment"][0]
        self.assertEqual(row["status"], "no_profit")


class OwnerDashboardViewTests(OwnerOverviewBase):
    def test_owner_sees_the_overview_and_others_do_not(self):
        today = date.today()
        self.check(today.year, today.month, stock="4000", cash="1000", git="500")
        self.make_expense("100.00", today, approved=False)

        self.client.login(username="owner", password=PASSWORD)
        response = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("owner_overview", response.context)
        self.assertContains(response, "Working capital")
        self.assertContains(response, "5,500.00")                   # total working capital
        self.assertContains(response, "Expenses awaiting approval")
        self.assertContains(response, "Reinvestment")
        self.assertContains(response, "Sales by Product")           # the existing section is still there

        self.client.logout()
        self.client.login(username="dm", password=PASSWORD)
        response = self.client.get(reverse("reports:dashboard"))
        self.assertNotIn("owner_overview", response.context)
        self.assertNotContains(response, "Working capital")

    def test_owner_without_any_data_still_gets_a_page(self):
        owner = User.objects.create_user("owner2", password=PASSWORD, role=R.DEPOT_OWNER, depot=self.other_depot)
        self.client.login(username="owner2", password=PASSWORD)
        response = self.client.get(reverse("reports:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No monthly health check has been recorded")
