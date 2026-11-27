from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User
from depots.models import Depot, Territory
from finance.models import BusinessLedger
from inventory.models import Product
from operations.models import Vehicle, VehicleLoad, VehicleLoadItem, VehicleSalesman
from .models import Customer, Sale, SaleItem


class SalesModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        territory = Territory.objects.create(name="Sales Territory")
        cls.depot = Depot.objects.create(
            territory=territory, name="Sales Depot", code="SALE-01"
        )
        cls.vehicle = Vehicle.objects.create(
            depot=cls.depot, registration_number="SAL-001", vehicle_name="Sales Van"
        )
        cls.salesman = VehicleSalesman.objects.create(
            name="Test Salesman", employee_id="SALESMAN-001", depot=cls.depot,
            vehicle=cls.vehicle,
        )
        cls.other_salesman = VehicleSalesman.objects.create(
            name="Other Salesman", employee_id="SALESMAN-002", depot=cls.depot,
        )
        cls.product = Product.objects.create(
            sku="SALE-SKU-001", name="Test Beverage", category="Sparkling",
            package_type="CRATE", volume="50cl", pack_size=24,
        )

    def setUp(self):
        self.load = VehicleLoad.objects.create(
            salesman=self.salesman, vehicle=self.vehicle, depot=self.depot
        )
        # The sale tests concern sales validation, not stock issue. Creating the
        # load line directly avoids duplicating inventory transaction tests.
        VehicleLoadItem.objects.bulk_create([
            VehicleLoadItem(vehicle_load=self.load, product=self.product, quantity=10)
        ])

    def make_sale(self, **kwargs):
        return Sale.objects.create(
            vehicle_load=kwargs.pop("vehicle_load", self.load),
            salesman=kwargs.pop("salesman", self.salesman),
            sale_date=kwargs.pop("sale_date", "2026-11-20"),
            **kwargs,
        )

    def add_item(self, sale, quantity=3):
        with patch("sales.models.get_current_acquisition_cost", return_value=Decimal("60.00")), \
             patch("sales.models.get_current_selling_price", return_value=Decimal("100.00")):
            return SaleItem.objects.create(
                sale=sale, product=self.product, quantity=quantity,
                discount_applied=Decimal("10.00"),
            )

    def test_customer_defaults_and_string_representation(self):
        customer = Customer.objects.create(name="Corner Shop", depot=self.depot)
        self.assertEqual(customer.outlet_type, Customer.OutletType.RETAIL)
        self.assertTrue(customer.is_active)
        self.assertEqual(str(customer), "Corner Shop")

    def test_sale_generates_number_and_defaults_salesman_from_load(self):
        sale = Sale.objects.create(vehicle_load=self.load, salesman=None)

        self.assertTrue(sale.sale_number.startswith("SALE-SALE-01-"))
        self.assertEqual(sale.salesman, self.salesman)
        self.assertFalse(sale.is_finalized)
        self.assertIsNone(sale.finalized_at)

    def test_sale_rejects_salesman_who_does_not_match_load(self):
        sale = Sale(vehicle_load=self.load, salesman=self.other_salesman)

        with self.assertRaises(ValidationError):
            sale.save()

    def test_sale_item_captures_prices_and_calculates_totals(self):
        sale = self.make_sale()
        item = self.add_item(sale, quantity=3)

        sale.refresh_from_db()
        self.assertEqual(item.unit_cost, Decimal("60.00"))
        self.assertEqual(item.unit_price, Decimal("100.00"))
        self.assertEqual(item.line_revenue, Decimal("270.00"))
        self.assertEqual(item.line_cost, Decimal("180.00"))
        self.assertEqual(item.line_profit, Decimal("90.00"))
        self.assertEqual(sale.total_revenue, Decimal("270.00"))
        self.assertEqual(sale.total_cost, Decimal("180.00"))
        self.assertEqual(sale.total_profit, Decimal("90.00"))

    def test_sale_item_cannot_exceed_loaded_quantity(self):
        sale = self.make_sale()

        with patch("sales.models.get_current_acquisition_cost", return_value=Decimal("60.00")), \
             patch("sales.models.get_current_selling_price", return_value=Decimal("100.00")):
            with self.assertRaises(ValidationError):
                SaleItem.objects.create(sale=sale, product=self.product, quantity=11)

    def test_sold_quantity_across_sales_cannot_exceed_load_quantity(self):
        first_sale = self.make_sale()
        second_sale = self.make_sale()
        self.add_item(first_sale, quantity=6)

        with patch("sales.models.get_current_acquisition_cost", return_value=Decimal("60.00")), \
             patch("sales.models.get_current_selling_price", return_value=Decimal("100.00")):
            with self.assertRaises(ValidationError):
                SaleItem.objects.create(
                    sale=second_sale, product=self.product, quantity=5
                )

    def test_sale_cannot_be_finalized_without_items(self):
        sale = self.make_sale()

        with self.assertRaisesMessage(ValidationError, "Cannot finalize a sale with no items."):
            sale.finalize()

        self.assertFalse(sale.is_finalized)
        self.assertFalse(BusinessLedger.objects.filter(reference=sale.sale_number).exists())

    def test_finalize_posts_revenue_once_and_locks_sale_items(self):
        sale = self.make_sale()
        item = self.add_item(sale, quantity=3)

        sale.finalize()
        sale.refresh_from_db()

        self.assertTrue(sale.is_finalized)
        self.assertIsNotNone(sale.finalized_at)
        ledger = BusinessLedger.objects.get(reference=sale.sale_number)
        self.assertEqual(ledger.depot, self.depot)
        self.assertEqual(ledger.transaction_type, BusinessLedger.TransactionType.INCOME)
        self.assertEqual(ledger.amount, Decimal("270.00"))

        item.quantity = 4
        with self.assertRaisesMessage(ValidationError, "This sale has already been finalized"):
            item.save()

        with self.assertRaisesMessage(ValidationError, "This sale has already been finalized."):
            sale.finalize()

        self.assertEqual(BusinessLedger.objects.filter(reference=sale.sale_number).count(), 1)
