from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from core.utils import generate_document_number, next_sequence
from core.models import TimeStampedModel
from depots.models import Depot
from .landing_cost import landing_cost_breakdown


# =========================
# PRODUCT
# =========================
class Product(TimeStampedModel):
    sku = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=50)

    package_type = models.CharField(
        max_length=20,
        choices=[
            ("CRATE", "Crate"),
            ("CARTON", "Carton"),
            ("PACK", "Pack"),
            ("PET", "PET"),
            ("RGB", "RGB"),
            ("CAN", "Can"),
            ("BOTTLE", "Bottle"),
        ],
    )

    volume = models.CharField(max_length=20)
    pack_size = models.PositiveIntegerField()

    # NOTE: These two fields are a convenience cache for admin/list
    # display ONLY (e.g. "what's the last known price for this SKU").
    # They are NOT the authoritative source for any transactional or
    # reporting calculation. Selling price must be read from
    # PriceHistory (see inventory.services.get_current_selling_price)
    # and acquisition cost must be read from the relevant
    # StockReceiptItem/inventory transaction
    # (see inventory.services.get_current_acquisition_cost).
    base_cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    base_selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.sku} - {self.name}"

    def update_prices(self, cost_price, selling_price, user=None, reason="", effective_from=None):
        """
        Record a new effective-dated price in PriceHistory (the
        authoritative pricing source) and refresh the display-cache
        fields on Product for convenience.

        Prefer calling inventory.services.record_price_change()
        directly; this method is kept for backward compatibility.
        """

        effective_from = effective_from or timezone.now()

        with transaction.atomic():
            price_history = PriceHistory.objects.create(
                product=self,
                cost_price=cost_price,
                selling_price=selling_price,
                effective_from=effective_from,
                changed_by=user,
                reason=reason,
            )

            self.base_cost_price = cost_price
            self.base_selling_price = selling_price
            self.save(update_fields=["base_cost_price", "base_selling_price", "updated_at"])

        return price_history

# =========================
# PRICE HISTORY
# =========================
class PriceHistory(TimeStampedModel):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="price_history"
    )

    cost_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)

    effective_from = models.DateTimeField()

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.product.name} - {self.effective_from}"


# =========================
# SUPPLIER
# =========================
class Supplier(TimeStampedModel):
    name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

# =========================
# PROMOTION
# =========================
class Promotion(TimeStampedModel):
    """
    A date-bounded promotional condition affecting how a depot's
    selling price is reduced for a customer (customer discount,
    volume discount, promotional selling price, buy X get Y).

    There is no supplier-side promotion level: whatever a supplier
    discounts, rebates, or otherwise adjusts is already reflected in
    the invoiced cost_price on StockReceiptItem, so it needs no
    separate record here.

    Applying a promotion must NEVER overwrite Product.base_* or a
    PriceHistory row. It only produces a calculated discount that
    the relevant transaction (VehicleLoadItem.promo_discount) can
    record against itself, preserving both the original price and
    the applied adjustment.

    There is no Customer/outlet model in the system yet (see
    project spec section 12 — future work), so DEPOT_TO_CUSTOMER
    promotions are scoped by depot and/or product only for now.
    """

    class Level(models.TextChoices):
        DEPOT_TO_CUSTOMER = "DEPOT_TO_CUSTOMER", "Depot -> Customer"

    class PromotionType(models.TextChoices):
        PERCENTAGE_DISCOUNT = "PERCENTAGE_DISCOUNT", "Percentage Discount"
        FIXED_DISCOUNT = "FIXED_DISCOUNT", "Fixed Amount Discount"
        VOLUME_REBATE = "VOLUME_REBATE", "Volume Rebate"
        BUY_X_GET_Y = "BUY_X_GET_Y", "Buy X Get Y"
        PROMOTIONAL_PRICE = "PROMOTIONAL_PRICE", "Promotional Price"
        PROMOTIONAL_CREDIT = "PROMOTIONAL_CREDIT", "Promotional Credit"

    name = models.CharField(max_length=150)

    level = models.CharField(
        max_length=20,
        choices=Level.choices,
    )

    promotion_type = models.CharField(
        max_length=25,
        choices=PromotionType.choices,
    )

    description = models.TextField(blank=True)

    # Leave empty to apply to ALL active products.
    products = models.ManyToManyField(
        Product,
        blank=True,
        related_name="promotions",
    )

    # Not currently used — kept only so historical promotions that
    # had a supplier set still display correctly. There is no
    # supplier-side promotion level to attach new ones to.
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="promotions",
    )

    # Optional depot scope. Leave empty to apply to all depots.
    depot = models.ForeignKey(
        Depot,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="promotions",
    )

    start_date = models.DateField()

    # Leave empty for an open-ended promotion.
    end_date = models.DateField(null=True, blank=True)

    # Used by PERCENTAGE_DISCOUNT (e.g. 10.00 = 10%).
    percentage_value = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Used by FIXED_DISCOUNT, PROMOTIONAL_CREDIT, PROMOTIONAL_PRICE.
    fixed_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Used by BUY_X_GET_Y.
    buy_quantity = models.PositiveIntegerField(null=True, blank=True)
    get_quantity = models.PositiveIntegerField(null=True, blank=True)

    minimum_quantity = models.PositiveIntegerField(null=True, blank=True)
    maximum_quantity = models.PositiveIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_promotions",
    )

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.name} ({self.get_promotion_type_display()})"

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")

        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.minimum_quantity > self.maximum_quantity
        ):
            raise ValidationError(
                "Minimum quantity cannot be greater than maximum quantity."
            )

        if self.promotion_type == self.PromotionType.PERCENTAGE_DISCOUNT:
            if self.percentage_value is None:
                raise ValidationError(
                    "Percentage discount promotions require percentage_value."
                )
            if not (0 < self.percentage_value <= 100):
                raise ValidationError(
                    "percentage_value must be between 0 and 100."
                )

        if self.promotion_type in (
            self.PromotionType.FIXED_DISCOUNT,
            self.PromotionType.PROMOTIONAL_CREDIT,
            self.PromotionType.PROMOTIONAL_PRICE,
        ):
            if self.fixed_value is None:
                raise ValidationError(
                    f"{self.get_promotion_type_display()} promotions "
                    "require fixed_value."
                )
            if self.fixed_value < 0:
                raise ValidationError("fixed_value cannot be negative.")

        if self.promotion_type == self.PromotionType.BUY_X_GET_Y:
            if not self.buy_quantity or not self.get_quantity:
                raise ValidationError(
                    "Buy X Get Y promotions require both "
                    "buy_quantity and get_quantity."
                )

    def is_effective_on(self, check_date):
        """
        Whether this promotion is active and within its date range
        on the given date.
        """

        if not self.is_active:
            return False

        if check_date < self.start_date:
            return False

        if self.end_date and check_date > self.end_date:
            return False

        return True

    def applies_to_product(self, product):
        if not self.products.exists():
            return True

        return self.products.filter(pk=product.pk).exists()

    def applies_to_quantity(self, quantity):
        if self.minimum_quantity is not None and quantity < self.minimum_quantity:
            return False

        if self.maximum_quantity is not None and quantity > self.maximum_quantity:
            return False

        return True

    def calculate_discount_per_unit(self, base_unit_price):
        """
        Return the per-unit discount this promotion implies against
        a given base unit price (the selling price, since
        DEPOT_TO_CUSTOMER is the only level there is).

        Does NOT check dates/quantity/product applicability — call
        is_effective_on()/applies_to_product()/applies_to_quantity()
        first, or use get_applicable_promotions() in services.py
        which does all of this for you.
        """

        if self.promotion_type == self.PromotionType.PERCENTAGE_DISCOUNT:
            return (base_unit_price * self.percentage_value / Decimal("100")).quantize(Decimal("0.01"))

        if self.promotion_type == self.PromotionType.FIXED_DISCOUNT:
            return min(self.fixed_value, base_unit_price)

        if self.promotion_type == self.PromotionType.PROMOTIONAL_PRICE:
            return max(base_unit_price - self.fixed_value, Decimal("0.00"))

        # VOLUME_REBATE, BUY_X_GET_Y, PROMOTIONAL_CREDIT need
        # quantity/basket-level context beyond a single unit price;
        # they're calculated at the transaction level, not here.
        return Decimal("0.00")


# =========================
# STOCK RECEIPT
# =========================
class StockReceipt(TimeStampedModel):
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="stock_receipts"
    )

    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="stock_receipts"
    )

    invoice_number = models.CharField(max_length=50)

    receipt_date = models.DateField(default=timezone.now)

    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0
    )

    class Meta:
        ordering = ["-receipt_date"]

    def __str__(self):
        return f"{self.invoice_number} - {self.supplier.name}"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_document_number(
                prefix="GRN",
                depot_code=self.depot.code,
                sequence=next_sequence(StockReceipt, "invoice_number"),
            )

        super().save(*args, **kwargs)


# =========================
# INVENTORY TRANSACTION
# =========================
class InventoryTransaction(TimeStampedModel):
    class TransactionType(models.TextChoices):
        RECEIPT = "RECEIPT", "Stock Receipt"
        VEHICLE_LOAD = "VEHICLE_LOAD", "Vehicle Load"
        VEHICLE_RETURN = "VEHICLE_RETURN", "Vehicle Return"
        ADJUSTMENT = "ADJUSTMENT", "Stock Adjustment"
        DAMAGE = "DAMAGE", "Damaged Stock"

    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="inventory_transactions"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory_transactions"
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )

    quantity = models.IntegerField(
        help_text="Positive for stock in, negative for stock out"
    )

    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    reference = models.CharField(max_length=100)

    transaction_date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-transaction_date", "-created_at"]

    def __str__(self):
        return f"{self.reference} - {self.product.name} ({self.quantity})"


# =========================
# STOCK RECEIPT ITEM
# =========================
class StockReceiptItem(TimeStampedModel):
    stock_receipt = models.ForeignKey(
        StockReceipt,
        on_delete=models.CASCADE,
        related_name="items"
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT
    )

    quantity = models.PositiveIntegerField()

    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Recorded acquisition/receipt cost. Do not add tax again if the entered cost is already tax-inclusive.",
    )

    rebate_landing_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional rebate-based cost per case with VAT and excise taken out. If blank, it is worked out from the cost price using NBC's workbook formula (VAT 7.5% + N10 per litre excise).",
    )

    @property
    def rebate_cost_breakdown(self):
        """Price, VAT, excise and landing cost worked out from cost_price."""
        return landing_cost_breakdown(self.cost_price, self.product)

    @property
    def effective_rebate_landing_cost(self):
        """
        Rebate-based cost per case (no tax). A value typed on the receipt
        line wins; otherwise it comes from the cost price minus VAT and
        excise, exactly as NBC's rebate workbook does it.
        """
        if self.rebate_landing_cost is not None:
            return self.rebate_landing_cost
        return self.rebate_cost_breakdown["landing_cost"]

    @property
    def rebate_cost_needs_review(self):
        """True when the landing cost was estimated without excise (pack size unreadable)."""
        return self.rebate_landing_cost is None and not self.rebate_cost_breakdown["excise_known"]

    @property
    def effective_cost_price(self):
        """
        Kept so callers elsewhere (inventory.services, operations,
        serializers, templates) don't need to change. cost_price is
        what the supplier actually invoiced, which already reflects
        any discount, rebate, or other adjustment they applied — so
        there is nothing left to subtract.
        """
        return self.cost_price

    @property
    def line_total(self):
        return self.effective_cost_price * self.quantity

    def __str__(self):
        return f"{self.product.name} ({self.quantity})"

    def save(self, *args, **kwargs):
        """
        Save the receipt line and, on creation, post the
        corresponding RECEIPT inventory transaction and preserve the
        actual acquisition cost paid for this specific batch of
        stock. This cost is never overwritten by later price changes
        (see finalized inventory/pricing decision).
        """

        is_new = self.pk is None

        with transaction.atomic():
            super().save(*args, **kwargs)

            if is_new:
                InventoryTransaction.objects.create(
                    depot=self.stock_receipt.depot,
                    product=self.product,
                    transaction_type=InventoryTransaction.TransactionType.RECEIPT,
                    quantity=self.quantity,
                    unit_cost=self.effective_cost_price,
                    reference=self.stock_receipt.invoice_number,
                    transaction_date=timezone.now(),
                )


# =========================
# STOCK BALANCE HELPER
# =========================
def get_stock_balance(depot, product):
    """
    Kept for backward compatibility. Prefer importing
    inventory.services.get_stock_balance directly.
    """

    from inventory.services import get_stock_balance as _get_stock_balance

    return _get_stock_balance(depot, product)

