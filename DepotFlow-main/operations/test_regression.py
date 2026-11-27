from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from depots.models import Depot, Territory
from finance.models import BusinessLedger
from inventory.models import Product, Supplier, StockReceipt, StockReceiptItem
from inventory.services import record_price_change, get_stock_balance
from sales.models import Sale, SaleItem

from .models import (
    Vehicle, VehicleSalesman, VehicleLoad, VehicleLoadItem,
    VehicleReturn, VehicleReturnItem, SalesTarget,
)

R = User.Role
PASSWORD = "S0me-long-pass-123"
TODAY = timezone.localdate()


def make_user(username, role, depot=None, territory=None, **extra):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=role,
        depot=depot, territory=territory, **extra,
    )


def receive_stock(depot, supplier, product, quantity, cost_price=600):
    """Posts a RECEIPT inventory transaction so a load has something to draw from."""
    receipt = StockReceipt.objects.create(supplier=supplier, depot=depot)
    return StockReceiptItem.objects.create(
        stock_receipt=receipt, product=product, quantity=quantity, cost_price=cost_price,
    )


class OperationsTestCase(TestCase):
    """Shared fixtures for every test class below."""

    @classmethod
    def setUpTestData(cls):
        cls.territory = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=cls.territory, name="Main", code="MN")
        cls.other_depot = Depot.objects.create(territory=cls.territory, name="Other", code="OT")

        cls.manager = make_user("dm", R.DEPOT_MANAGER, depot=cls.depot)
        cls.other_manager = make_user("dm2", R.DEPOT_MANAGER, depot=cls.other_depot)
        cls.viewer = make_user("viewer", R.VIEWER, depot=cls.depot)

        cls.vehicle = Vehicle.objects.create(depot=cls.depot, registration_number="V-1", vehicle_name="Truck 1")
        cls.other_vehicle = Vehicle.objects.create(
            depot=cls.other_depot, registration_number="V-2", vehicle_name="Truck 2"
        )

        cls.salesman = VehicleSalesman.objects.create(
            name="Sam Salesman", employee_id="E-1", depot=cls.depot, vehicle=cls.vehicle,
        )

        cls.supplier = Supplier.objects.create(name="Acme Bottling")
        cls.product = Product.objects.create(
            sku="SKU-1", name="Cola 50cl", category="Soft Drinks",
            package_type="BOTTLE", volume="50cl", pack_size=24,
        )
        record_price_change(cls.product, selling_price=1000, cost_price=600)

    def make_load(self, salesman=None, load_date=None):
        return VehicleLoad.objects.create(
            salesman=salesman or self.salesman,
            vehicle=(salesman or self.salesman).vehicle,
            depot=(salesman or self.salesman).depot,
            load_date=load_date or TODAY,
        )

    def load_item(self, load, quantity, product=None):
        return VehicleLoadItem.objects.create(
            vehicle_load=load, product=product or self.product, quantity=quantity,
        )


class VehicleLoadValidationTests(OperationsTestCase):
    """VehicleLoad.clean() -- the consistency and same-day-reload rules."""

    def test_salesman_must_belong_to_the_load_depot(self):
        load = VehicleLoad(
            salesman=self.salesman, vehicle=self.vehicle, depot=self.other_depot,
        )
        with self.assertRaises(ValidationError):
            load.save()

    def test_vehicle_must_belong_to_the_load_depot(self):
        load = VehicleLoad(
            salesman=self.salesman, vehicle=self.other_vehicle, depot=self.depot,
        )
        with self.assertRaises(ValidationError):
            load.save()

    def test_vehicle_must_match_salesmans_assigned_vehicle(self):
        unassigned_vehicle = Vehicle.objects.create(
            depot=self.depot, registration_number="V-3", vehicle_name="Truck 3",
        )
        load = VehicleLoad(
            salesman=self.salesman, vehicle=unassigned_vehicle, depot=self.depot,
        )
        with self.assertRaises(ValidationError):
            load.save()

    def test_load_number_is_auto_generated_and_unique(self):
        load1 = self.make_load()
        load2_salesman = VehicleSalesman.objects.create(
            name="Other Sam", employee_id="E-2", depot=self.depot,
            vehicle=Vehicle.objects.create(depot=self.depot, registration_number="V-4", vehicle_name="Truck 4"),
        )
        load2 = self.make_load(salesman=load2_salesman)

        self.assertTrue(load1.load_number)
        self.assertNotEqual(load1.load_number, load2.load_number)

    def test_same_day_reload_is_allowed(self):
        self.make_load()  # first load, open, dated today
        second = self.make_load()  # should not raise
        self.assertIsNotNone(second.pk)

    def test_stale_open_load_blocks_a_new_one(self):
        yesterday = TODAY - timedelta(days=1)
        self.make_load(load_date=yesterday)  # still open

        with self.assertRaises(ValidationError):
            self.make_load(load_date=TODAY)

    def test_closing_the_stale_load_unblocks_new_loads(self):
        yesterday = TODAY - timedelta(days=1)
        old_load = self.make_load(load_date=yesterday)
        old_load.close_load()  # no items -- nothing to reconcile, closes trivially

        new_load = self.make_load(load_date=TODAY)
        self.assertIsNotNone(new_load.pk)


class VehicleLoadItemTests(OperationsTestCase):
    """Stock checks, discount validation, and the closed-load lock."""

    def test_cannot_load_more_than_available_stock(self):
        load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=10)

        with self.assertRaises(ValidationError):
            self.load_item(load, quantity=11)

    def test_loading_within_stock_succeeds_and_posts_inventory_transaction(self):
        load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=50)

        item = self.load_item(load, quantity=20)

        self.assertEqual(get_stock_balance(self.depot, self.product), 30)  # 50 received - 20 loaded
        self.assertEqual(item.cost_price, 600)
        self.assertEqual(item.selling_price, 1000)

    def test_quantity_must_be_positive(self):
        load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=50)

        with self.assertRaises(ValidationError):
            VehicleLoadItem.objects.create(vehicle_load=load, product=self.product, quantity=0)

    def test_promo_discount_cannot_exceed_selling_price(self):
        load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=50)

        with self.assertRaises(ValidationError):
            VehicleLoadItem.objects.create(
                vehicle_load=load, product=self.product, quantity=5, promo_discount=1001,
            )

    def test_cannot_add_items_to_a_closed_load(self):
        load = self.make_load()
        load.close_load()  # empty load closes trivially
        receive_stock(self.depot, self.supplier, self.product, quantity=50)

        with self.assertRaises(ValidationError):
            self.load_item(load, quantity=5)


class VehicleReturnTests(OperationsTestCase):
    """confirm_return()'s inventory posting, and the one-time-confirm rule."""

    def setUp(self):
        self.load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=50)
        self.load_item(self.load, quantity=50)

    def test_confirming_a_good_return_adds_stock_back(self):
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)
        VehicleReturnItem.objects.create(
            vehicle_return=vehicle_return, product=self.product, quantity=10, condition="GOOD",
        )

        before = get_stock_balance(self.depot, self.product)
        vehicle_return.confirm_return()
        after = get_stock_balance(self.depot, self.product)

        self.assertEqual(after, before + 10)

    def test_confirming_a_damaged_return_does_not_change_depot_stock(self):
        """Damaged returned units are received and written off exactly once."""
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)
        VehicleReturnItem.objects.create(
            vehicle_return=vehicle_return, product=self.product, quantity=10, condition="DAMAGED",
        )

        before = get_stock_balance(self.depot, self.product)
        vehicle_return.confirm_return()
        after = get_stock_balance(self.depot, self.product)

        self.assertEqual(after, before)

    def test_cannot_confirm_the_same_return_twice(self):
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)
        VehicleReturnItem.objects.create(
            vehicle_return=vehicle_return, product=self.product, quantity=5, condition="GOOD",
        )
        vehicle_return.confirm_return()

        with self.assertRaises(ValidationError):
            vehicle_return.confirm_return()

    def test_return_item_quantity_is_validated_on_plain_save(self):
        """Direct ORM writes must enforce the same positive-quantity rule."""
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)

        with self.assertRaises(ValidationError):
            VehicleReturnItem.objects.create(
                vehicle_return=vehicle_return, product=self.product,
                quantity=0, condition="GOOD",
            )

    def test_confirmed_return_cannot_receive_new_items(self):
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)
        vehicle_return.confirm_return()

        with self.assertRaises(ValidationError):
            VehicleReturnItem.objects.create(
                vehicle_return=vehicle_return, product=self.product,
                quantity=1, condition="GOOD",
            )


class ReconciliationAndCloseTests(OperationsTestCase):
    """The core rule: a load can only close once every product is fully sold or returned."""

    def setUp(self):
        self.load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=100)
        self.item = self.load_item(self.load, quantity=50)

    def sell(self, quantity):
        sale = Sale.objects.create(vehicle_load=self.load, sale_date=TODAY)
        SaleItem.objects.create(sale=sale, product=self.product, quantity=quantity)
        sale.finalize()
        return sale

    def return_items(self, quantity, condition="GOOD"):
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)
        VehicleReturnItem.objects.create(
            vehicle_return=vehicle_return, product=self.product, quantity=quantity, condition=condition,
        )
        vehicle_return.confirm_return()
        return vehicle_return

    def test_reconciliation_status_reflects_sold_and_returned(self):
        self.sell(30)
        self.return_items(10)

        rows = self.load.reconciliation_status()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["loaded"], 50)
        self.assertEqual(row["sold"], 30)
        self.assertEqual(row["returned"], 10)
        self.assertEqual(row["remaining"], 10)

    def test_cannot_close_with_stock_unaccounted_for(self):
        self.sell(30)  # 20 still unaccounted for -- no return recorded

        with self.assertRaises(ValidationError):
            self.load.close_load()

        self.load.refresh_from_db()
        self.assertFalse(self.load.is_closed)

    def test_closes_once_fully_sold_and_returned(self):
        self.sell(30)
        self.return_items(20)

        self.load.close_load()

        self.load.refresh_from_db()
        self.assertTrue(self.load.is_closed)
        self.assertIsNotNone(self.load.closed_at)

    def test_closes_when_fully_sold_with_no_return_needed(self):
        self.sell(50)
        self.load.close_load()
        self.load.refresh_from_db()
        self.assertTrue(self.load.is_closed)

    def test_cannot_close_an_already_closed_load(self):
        self.sell(50)
        self.load.close_load()

        with self.assertRaises(ValidationError):
            self.load.close_load()

    def test_unfinalized_sale_does_not_count_toward_reconciliation(self):
        sale = Sale.objects.create(vehicle_load=self.load, sale_date=TODAY)
        SaleItem.objects.create(sale=sale, product=self.product, quantity=30)
        # deliberately not finalized

        row = self.load.reconciliation_status()[0]
        self.assertEqual(row["sold"], 0)
        self.assertEqual(row["remaining"], 50)

    def test_unconfirmed_return_does_not_count_toward_reconciliation(self):
        vehicle_return = VehicleReturn.objects.create(vehicle_load=self.load)
        VehicleReturnItem.objects.create(
            vehicle_return=vehicle_return, product=self.product, quantity=20, condition="GOOD",
        )
        # deliberately not confirmed

        row = self.load.reconciliation_status()[0]
        self.assertEqual(row["returned"], 0)
        self.assertEqual(row["remaining"], 50)


class SalesTargetTests(OperationsTestCase):
    def test_daily_and_weekly_targets_are_derived_from_quantity_and_month_length(self):
        target = SalesTarget.objects.create(
            salesman=self.salesman, year=2026, month=4, target_quantity=300,  # April = 30 days
        )
        self.assertEqual(target.days_in_month, 30)
        self.assertEqual(target.daily_target, 10)
        self.assertEqual(target.weekly_target, 70)

    def test_only_one_target_per_salesman_per_month(self):
        SalesTarget.objects.create(salesman=self.salesman, year=2026, month=5, target_quantity=100)

        with self.assertRaises(IntegrityError), transaction.atomic():
            SalesTarget.objects.create(salesman=self.salesman, year=2026, month=5, target_quantity=200)


class LoadCloseViewTests(OperationsTestCase):
    """End-to-end: the combined sold+returned form that creates the Sale/Return and closes the load."""

    def setUp(self):
        self.load = self.make_load()
        receive_stock(self.depot, self.supplier, self.product, quantity=100)
        self.item = self.load_item(self.load, quantity=50)
        self.url = reverse("operations:load_close", args=[self.load.pk])

    def post_close(self, sold, returned, condition="GOOD"):
        return self.client.post(self.url, {
            f"sold_{self.product.id}": sold,
            f"returned_{self.product.id}": returned,
            f"condition_{self.product.id}": condition,
        })

    def test_full_reconciliation_creates_sale_and_return_and_closes_load(self):
        self.client.force_login(self.manager)
        response = self.post_close(sold=30, returned=20)

        self.assertRedirects(response, reverse("operations:load_detail", args=[self.load.pk]))

        self.load.refresh_from_db()
        self.assertTrue(self.load.is_closed)

        sale = Sale.objects.get(vehicle_load=self.load)
        self.assertTrue(sale.is_finalized)
        self.assertEqual(sale.items.get(product=self.product).quantity, 30)

        vehicle_return = VehicleReturn.objects.get(vehicle_load=self.load)
        self.assertTrue(vehicle_return.is_confirmed)
        self.assertEqual(vehicle_return.items.get(product=self.product).quantity, 20)

        ledger_entry = BusinessLedger.objects.get(reference=sale.sale_number)
        self.assertEqual(ledger_entry.transaction_type, BusinessLedger.TransactionType.INCOME)
        self.assertEqual(ledger_entry.amount, 30 * 1000)  # 30 units at the 1000 selling price

    def test_mismatched_total_is_rejected_and_load_stays_open(self):
        self.client.force_login(self.manager)
        response = self.post_close(sold=10, returned=10)  # only 20 of 50 accounted for

        self.assertEqual(response.status_code, 200)  # form re-rendered with an error, no redirect
        self.load.refresh_from_db()
        self.assertFalse(self.load.is_closed)
        self.assertFalse(Sale.objects.filter(vehicle_load=self.load).exists())
        self.assertFalse(VehicleReturn.objects.filter(vehicle_load=self.load).exists())

    def test_user_without_permission_is_blocked(self):
        self.client.force_login(self.viewer)
        response = self.post_close(sold=50, returned=0)

        self.assertRedirects(response, reverse("operations:load_detail", args=[self.load.pk]))
        self.load.refresh_from_db()
        self.assertFalse(self.load.is_closed)

    def test_manager_from_another_depot_is_blocked(self):
        self.client.force_login(self.other_manager)
        response = self.post_close(sold=50, returned=0)

        self.assertRedirects(response, reverse("operations:load_list"))
        self.load.refresh_from_db()
        self.assertFalse(self.load.is_closed)

    def test_cannot_close_an_already_closed_load_via_the_view(self):
        self.client.force_login(self.manager)
        self.post_close(sold=50, returned=0)  # closes it

        response = self.post_close(sold=0, returned=0)
        self.assertRedirects(response, reverse("operations:load_detail", args=[self.load.pk]))
