"""
Inventory & pricing services.

This module is the single authoritative place for:

- Looking up the current effective SELLING price of a product
  (from PriceHistory, effective-date based).
- Looking up the current ACQUISITION COST reference for a product
  at a depot (from the most recently recorded StockReceiptItem —
  i.e. the actual price paid for stock, not a mutable product field).
- Computing current stock balance from the inventory transaction
  ledger.

Per the finalized inventory/pricing decision:

- Product.base_cost_price / Product.base_selling_price are a
  display-only cache and must NEVER be used for transactional or
  reporting calculations.
- Selling price is dynamic and effective-date based (PriceHistory).
- Acquisition cost is preserved per stock receipt and is NOT
  recalculated when supplier prices change later.
- There is no InventoryBatch / FIFO layer. "Current acquisition
  cost" for existing depot stock is the cost recorded on the most
  recent stock receipt for that product/depot, consistent with the
  system's existing no-FIFO approach.
- Any code that needs "the price to use right now" must call these
  functions rather than reading Product fields directly.
"""

from decimal import Decimal

from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone


def get_current_price_history(product, as_of=None):
    """
    Return the PriceHistory row that is effective as of the given
    datetime (defaults to now), or None if no price has ever been
    recorded for this product.
    """

    as_of = as_of or timezone.now()

    return (
        product.price_history
        .filter(effective_from__lte=as_of)
        .order_by("-effective_from")
        .first()
    )


def get_current_selling_price(product, as_of=None):
    """
    Return the current effective selling price for a product, based
    on PriceHistory. Falls back to Product.base_selling_price only
    if no PriceHistory record exists yet (e.g. a brand-new product
    that hasn't had a price set through the pricing workflow).
    """

    price_history = get_current_price_history(product, as_of=as_of)

    if price_history:
        return price_history.selling_price

    return product.base_selling_price


def get_current_cost_reference(product, as_of=None):
    """
    Return the current supplier/commercial cost reference recorded
    in PriceHistory. This is informational (e.g. for anticipating
    the cost of the NEXT receipt) and must NOT be used to value
    existing stock — use get_current_acquisition_cost() for that.
    """

    price_history = get_current_price_history(product, as_of=as_of)

    if price_history:
        return price_history.cost_price

    return product.base_cost_price


def get_current_acquisition_cost(depot, product):
    """
    Return the acquisition cost to use for valuing/expected-profit
    calculations on EXISTING depot stock: the effective cost price
    (after supplier discount/rebate) recorded on the most recent
    StockReceiptItem for this product at this depot.

    This deliberately does not use FIFO/batch tracking. If the
    depot has never received this product, returns Decimal("0.00").
    """

    # Imported locally to avoid a circular import at module load time.
    from inventory.models import StockReceiptItem

    latest_item = (
        StockReceiptItem.objects
        .filter(
            stock_receipt__depot=depot,
            product=product,
        )
        .order_by("-stock_receipt__receipt_date", "-created_at")
        .first()
    )

    if not latest_item:
        return Decimal("0.00")

    return latest_item.effective_cost_price


def get_stock_balance(depot, product):
    """
    Return the current physical stock balance for a product at a
    specific depot, derived from the inventory transaction ledger.
    """

    from inventory.models import InventoryTransaction

    balance = (
        InventoryTransaction.objects
        .filter(depot=depot, product=product)
        .aggregate(total=Sum("quantity"))["total"]
    )

    return balance or 0


def record_price_change(product, selling_price, cost_price=None, effective_from=None, user=None, reason=""):
    """
    Record a new effective-dated selling price (and, optionally, an
    informational cost reference) for a product.

    This is the preferred way to change pricing. It does not touch
    physical inventory or stock receipts in any way.
    """

    from inventory.models import PriceHistory

    if selling_price < 0:
        raise ValueError("Selling price cannot be negative.")

    if cost_price is not None and cost_price < 0:
        raise ValueError("Cost price cannot be negative.")

    effective_from = effective_from or timezone.now()

    previous = get_current_price_history(product, as_of=effective_from)

    price_history = PriceHistory.objects.create(
        product=product,
        cost_price=cost_price if cost_price is not None else get_current_cost_reference(product, as_of=effective_from),
        selling_price=selling_price,
        effective_from=effective_from,
        changed_by=user,
        reason=reason,
    )

    # Refresh the display-cache fields on Product for admin/list
    # convenience only — never read back for calculations.
    Product = product.__class__
    Product.objects.filter(pk=product.pk).update(
        base_selling_price=price_history.selling_price,
        base_cost_price=price_history.cost_price,
        updated_at=timezone.now(),
    )

    from core.audit import log_action
    from core.models import AuditLog

    log_action(
        AuditLog.Action.PRICE_CHANGE,
        obj=product,
        user=user,
        old_value={
            "selling_price": str(previous.selling_price) if previous else None,
            "cost_price": str(previous.cost_price) if previous else None,
        },
        new_value={
            "selling_price": str(price_history.selling_price),
            "cost_price": str(price_history.cost_price),
        },
        notes=reason,
    )

    return price_history

def get_applicable_promotions(product, level, quantity=1, depot=None, supplier=None, as_of=None):
    """
    Return the list of Promotions that currently apply to a given
    product/quantity/depot/supplier combination, most recently
    started first.
 
    Does not pick a single "winning" promotion or apply anything —
    it's the caller's responsibility to decide how to record the
    resulting discount on the relevant transaction line
    (StockReceiptItem.supplier_discount/supplier_rebate, or
    VehicleLoadItem.promo_discount), so the original price and the
    applied adjustment both stay visible on that record.
    """
 
    from inventory.models import Promotion
 
    as_of = as_of or timezone.now().date()
 
    candidates = Promotion.objects.filter(
        level=level,
        is_active=True,
        start_date__lte=as_of,
    ).filter(
        models.Q(end_date__isnull=True) | models.Q(end_date__gte=as_of)
    )
 
    if depot is not None:
        candidates = candidates.filter(
            models.Q(depot__isnull=True) | models.Q(depot=depot)
        )
 
    if supplier is not None:
        candidates = candidates.filter(
            models.Q(supplier__isnull=True) | models.Q(supplier=supplier)
        )
 
    applicable = [
        promo for promo in candidates
        if promo.applies_to_product(product) and promo.applies_to_quantity(quantity)
    ]
 
    return applicable

def create_adjustment(depot, product, quantity_delta, reason, user=None):
    """
    The sanctioned way to make a manual stock adjustment (stock
    count correction, expiry write-off not already covered by a
    return, etc). Posts an ADJUSTMENT InventoryTransaction and
    records an AuditLog entry — manual adjustments should never be
    made by editing InventoryTransaction rows directly (they're
    locked from editing in admin for exactly this reason).

    quantity_delta: positive to increase stock, negative to
    decrease it. Cannot be zero.
    """

    from inventory.models import InventoryTransaction
    from core.audit import log_action
    from core.models import AuditLog

    if quantity_delta == 0:
        raise ValueError("quantity_delta cannot be zero.")

    if not reason:
        raise ValueError("A reason is required for every inventory adjustment.")

    with transaction.atomic():
        cost_reference = get_current_acquisition_cost(depot, product)

        adjustment = InventoryTransaction.objects.create(
            depot=depot,
            product=product,
            transaction_type=InventoryTransaction.TransactionType.ADJUSTMENT,
            quantity=quantity_delta,
            unit_cost=cost_reference,
            reference=f"ADJ-{depot.code}-{timezone.now():%Y%m%d%H%M%S}",
            transaction_date=timezone.now(),
        )

        log_action(
            AuditLog.Action.INVENTORY_ADJUSTMENT,
            obj=adjustment,
            user=user,
            new_value={
                "depot": depot.code,
                "product": product.sku,
                "quantity_delta": quantity_delta,
            },
            notes=reason,
        )

    return adjustment