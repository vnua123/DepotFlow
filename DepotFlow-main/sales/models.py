from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.models import TimeStampedModel
from core.utils import generate_document_number, next_sequence
from depots.models import Depot
from inventory.models import Product, Promotion
from inventory.services import get_current_acquisition_cost, get_current_selling_price
from operations.models import VehicleLoad, VehicleSalesman, VehicleReturnItem


class Customer(TimeStampedModel):
    """
    A customer/outlet a depot sells to. Kept intentionally simple
    for now — richer fields (credit terms, route, etc.) can be
    added later without disrupting Sale/SaleItem, which only
    reference this by FK.
    """

    class OutletType(models.TextChoices):
        RETAIL = "RETAIL", "Retail Shop"
        WHOLESALE = "WHOLESALE", "Wholesale"
        SUPERMARKET = "SUPERMARKET", "Supermarket"
        KIOSK = "KIOSK", "Kiosk"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=150)

    outlet_type = models.CharField(
        max_length=20,
        choices=OutletType.choices,
        default=OutletType.RETAIL,
    )

    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="customers",
        null=True,
        blank=True,
    )

    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Sale(TimeStampedModel):
    """
    The actual sale detail behind a VehicleLoad: which products, in
    what quantity, to which customer, at what price were actually
    sold.

    This does NOT move inventory a second time — the depot ->
    vehicle stock movement was already recorded when the
    VehicleLoad/VehicleLoadItem was created. A Sale is a revenue/
    customer-attribution layer on top of that, used to calculate
    ACTUAL (not expected) profit.

    Recording individual sales is optional (per the original
    project spec, section 10) — a vehicle load/return can be
    reconciled without one. When sales ARE recorded, the sum of
    sold + returned quantities for a product on a load cannot
    exceed what was loaded (see SaleItem.clean()).
    """

    vehicle_load = models.ForeignKey(
        VehicleLoad,
        on_delete=models.PROTECT,
        related_name="sales",
    )

    salesman = models.ForeignKey(
        VehicleSalesman,
        on_delete=models.PROTECT,
        related_name="sales",
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
        help_text="Leave blank for a cash/walk-in sale with no specific outlet.",
    )

    sale_number = models.CharField(max_length=50, unique=True, blank=True)
    sale_date = models.DateField(default=timezone.now)

    is_finalized = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-sale_date", "-created_at"]

    def __str__(self):
        return self.sale_number or f"Sale ({self.pk})"

    def clean(self):
        if (
            self.vehicle_load_id
            and self.salesman_id
            and self.vehicle_load.salesman_id != self.salesman_id
        ):
            raise ValidationError(
                "The salesman does not match the salesman on the "
                "selected vehicle load."
            )

    def save(self, *args, **kwargs):
        if self.vehicle_load_id and not self.salesman_id:
            self.salesman = self.vehicle_load.salesman

        if not self.sale_number:
            self.sale_number = generate_document_number(
                prefix="SALE",
                depot_code=self.vehicle_load.depot.code,
                sequence=next_sequence(Sale, "sale_number"),
            )

        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def total_revenue(self):
        return sum(
            (item.line_revenue for item in self.items.all()),
            Decimal("0.00"),
        )

    @property
    def total_cost(self):
        return sum(
            (item.line_cost for item in self.items.all()),
            Decimal("0.00"),
        )

    @property
    def total_profit(self):
        return self.total_revenue - self.total_cost

    def finalize(self):
        """
        Lock the sale and post its total revenue to BusinessLedger
        as INCOME. Once finalized, items cannot be added, changed,
        or removed (see SaleItem.clean()).
        """

        if self.is_finalized:
            raise ValidationError("This sale has already been finalized.")

        if not self.items.exists():
            raise ValidationError("Cannot finalize a sale with no items.")

        from finance.models import BusinessLedger

        with transaction.atomic():
            BusinessLedger.objects.create(
                depot=self.vehicle_load.depot,
                transaction_type=BusinessLedger.TransactionType.INCOME,
                transaction_date=self.sale_date,
                description=(
                    f"Sale {self.sale_number}"
                    + (f" to {self.customer.name}" if self.customer else "")
                ),
                amount=self.total_revenue,
                reference=self.sale_number,
            )

            self.is_finalized = True
            self.finalized_at = timezone.now()
            self.save(update_fields=["is_finalized", "finalized_at", "updated_at"])


class SaleItem(TimeStampedModel):
    """
    A single product line within a Sale. Prices are captured as a
    permanent, frozen snapshot of what was actually charged/cost at
    the moment of sale — unlike VehicleLoadItem (which tracks
    unsold stock and deliberately floats with price changes), this
    IS the actual transaction, so historical truth is preserved
    here per the finalized pricing decision.
    """

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="sale_items",
    )

    quantity = models.PositiveIntegerField()

    # Frozen at creation — the actual cost/price/discount used.
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_applied = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    promotion = models.ForeignKey(
        Promotion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sale_items",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sale", "product"],
                name="unique_product_per_sale",
            )
        ]

    def __str__(self):
        return f"{self.product.name} ({self.quantity})"

    @property
    def line_revenue(self):
        return (self.unit_price - self.discount_applied) * self.quantity

    @property
    def line_cost(self):
        return self.unit_cost * self.quantity

    @property
    def line_profit(self):
        return self.line_revenue - self.line_cost

    def clean(self):
        if self.sale.is_finalized:
            raise ValidationError(
                "This sale has already been finalized and cannot be modified."
            )

        if self.quantity <= 0:
            raise ValidationError("Quantity must be greater than zero.")

        try:
            load_item = self.sale.vehicle_load.items.get(product=self.product)
        except self.sale.vehicle_load.items.model.DoesNotExist:
            raise ValidationError(
                f"{self.product.name} was not part of this vehicle load."
            )

        already_sold = (
            SaleItem.objects
            .filter(sale__vehicle_load=self.sale.vehicle_load, product=self.product)
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum("quantity"))["total"]
            or 0
        )

        already_returned = (
            VehicleReturnItem.objects
            .filter(
                vehicle_return__vehicle_load=self.sale.vehicle_load,
                vehicle_return__is_confirmed=True,
                product=self.product,
            )
            .aggregate(total=models.Sum("quantity"))["total"]
            or 0
        )

        accounted_for = already_sold + already_returned + self.quantity

        if accounted_for > load_item.quantity:
            available = load_item.quantity - already_sold - already_returned
            raise ValidationError(
                f"Cannot sell {self.quantity} of {self.product.name}: only "
                f"{available} remain unaccounted for on this load "
                f"(loaded {load_item.quantity}, already sold {already_sold}, "
                f"already returned {already_returned})."
            )

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            depot = self.sale.vehicle_load.depot
            self.unit_cost = get_current_acquisition_cost(depot, self.product)
            self.unit_price = get_current_selling_price(self.product)

            if self.promotion:
                self.discount_applied = self.promotion.calculate_discount_per_unit(
                    self.unit_price
                )

        self.full_clean()
        super().save(*args, **kwargs)