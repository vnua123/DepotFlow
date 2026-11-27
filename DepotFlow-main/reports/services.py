"""
Report calculations for DepotFlow.

This module contains the actual business logic for every report;
views.py should stay a thin layer that parses request parameters
and calls these functions, never computing report figures itself
(see project spec section 20 — services contain business
operations, views just coordinate).

All money figures use Decimal throughout, and DB-side aggregation
(Sum/ExpressionWrapper) is used wherever the result set could be
large, to avoid pulling thousands of rows into Python.
"""

from decimal import Decimal

from django.db.models import Sum, Count, F, DecimalField, ExpressionWrapper

from depots.models import Depot
from inventory.models import Product, InventoryTransaction
from inventory.services import (
    get_stock_balance,
    get_current_acquisition_cost,
    get_current_selling_price,
)
from operations.models import VehicleLoad, get_expected_profit_for_load, SalesTarget
from finance.models import Expense, BusinessLedger, SupplierRebate
from sales.models import Sale, SaleItem


# Reusable DB-side expressions for revenue/cost on a SaleItem
# queryset. Kept in one place so every report computes actual
# revenue/cost the same way.
#
# NOTE: these must be attached to a queryset via .annotate(revenue=...,
# cost=...) BEFORE being summed. Django 5.2 rejects Sum(REVENUE_EXPR)
# directly — an ExpressionWrapper passed straight into Sum() is treated
# as an aggregate itself, which raises FieldError ("... is an
# aggregate"). Summing the annotation by name (Sum("revenue")) is the
# correct two-step form. Use _with_revenue_cost() below rather than
# applying these inline so every call site does it the same way.
REVENUE_EXPR = ExpressionWrapper(
    (F("unit_price") - F("discount_applied")) * F("quantity"),
    output_field=DecimalField(max_digits=14, decimal_places=2),
)

COST_EXPR = ExpressionWrapper(
    F("unit_cost") * F("quantity"),
    output_field=DecimalField(max_digits=14, decimal_places=2),
)


def _with_revenue_cost(sale_item_queryset):
    """Annotate a SaleItem queryset with per-row revenue/cost, ready to Sum("revenue")/Sum("cost")."""
    return sale_item_queryset.annotate(revenue=REVENUE_EXPR, cost=COST_EXPR)


def _date_range_filter(queryset, date_field, date_from=None, date_to=None):
    if date_from:
        queryset = queryset.filter(**{f"{date_field}__gte": date_from})
    if date_to:
        queryset = queryset.filter(**{f"{date_field}__lte": date_to})
    return queryset


# =========================
# DEPOT REPORTS
# =========================
def get_daily_sales_report(depot, report_date):
    """
    Actual sales for a depot on a single day, from finalized Sales
    only (unfinalized/draft sales are excluded — they haven't
    posted revenue yet).
    """

    items = _with_revenue_cost(SaleItem.objects.filter(
        sale__vehicle_load__depot=depot,
        sale__sale_date=report_date,
        sale__is_finalized=True,
    ))

    totals = items.aggregate(
        total_quantity=Sum("quantity"),
        total_revenue=Sum("revenue"),
        total_cost=Sum("cost"),
    )

    by_product = (
        items.values("product__sku", "product__name")
        .annotate(
            quantity=Sum("quantity"),
            revenue=Sum("revenue"),
            cost=Sum("cost"),
        )
        .order_by("-revenue")
    )

    total_revenue = totals["total_revenue"] or Decimal("0.00")
    total_cost = totals["total_cost"] or Decimal("0.00")

    return {
        "depot": depot.name,
        "date": report_date,
        "total_quantity": totals["total_quantity"] or 0,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "total_profit": total_revenue - total_cost,
        "by_product": list(by_product),
    }


def get_sales_summary_for_range(depot, date_from, date_to):
    """
    Same shape as get_daily_sales_report, but for an arbitrary date
    range instead of a single day — powers the dashboard's timeframe
    picker (Today, This Week, Month to Date, or a custom range all
    call this one function; get_daily_sales_report is left exactly
    as-is rather than rewritten on top of this, since its JSON report
    endpoint's output shape is an existing external contract).
    """

    items = _with_revenue_cost(SaleItem.objects.filter(
        sale__vehicle_load__depot=depot,
        sale__is_finalized=True,
    ))
    items = _date_range_filter(items, "sale__sale_date", date_from, date_to)

    totals = items.aggregate(
        total_quantity=Sum("quantity"),
        total_revenue=Sum("revenue"),
        total_cost=Sum("cost"),
    )

    by_product = (
        items.values("product__sku", "product__name")
        .annotate(
            quantity=Sum("quantity"),
            revenue=Sum("revenue"),
            cost=Sum("cost"),
        )
        .order_by("-revenue")
    )

    total_revenue = totals["total_revenue"] or Decimal("0.00")
    total_cost = totals["total_cost"] or Decimal("0.00")

    return {
        "depot": depot.name,
        "date_from": date_from,
        "date_to": date_to,
        "total_quantity": totals["total_quantity"] or 0,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "total_profit": total_revenue - total_cost,
        "by_product": list(by_product),
    }


def get_daily_stock_movement_report(depot, report_date):
    """
    Every inventory transaction posted at a depot on a single day,
    grouped by transaction type.
    """

    transactions = (
        InventoryTransaction.objects
        .filter(depot=depot, transaction_date__date=report_date)
        .select_related("product")
        .order_by("transaction_type", "product__name")
    )

    by_type = (
        transactions.values("transaction_type")
        .annotate(total_quantity=Sum("quantity"), count=Count("id"))
        .order_by("transaction_type")
    )

    return {
        "depot": depot.name,
        "date": report_date,
        "by_type": list(by_type),
        "transactions": list(
            transactions.values(
                "product__sku",
                "product__name",
                "transaction_type",
                "quantity",
                "unit_cost",
                "reference",
            )
        ),
    }


def get_current_inventory_report(depot):
    """
    Current stock balance, acquisition cost, selling price, and
    value for every product that has ever moved at this depot.

    NOTE: this loops per-product to reuse the tested
    get_stock_balance()/get_current_acquisition_cost() helpers
    rather than duplicating their logic here. For depots with a
    very large product catalog this could be optimized into fewer
    aggregate queries later; fine for typical SKU counts today.
    """

    products = (
        Product.objects
        .filter(inventory_transactions__depot=depot)
        .distinct()
    )

    rows = []

    for product in products:
        balance = get_stock_balance(depot, product)
        cost = get_current_acquisition_cost(depot, product)
        price = get_current_selling_price(product)

        rows.append({
            "sku": product.sku,
            "name": product.name,
            "stock_balance": balance,
            "acquisition_cost": cost,
            "selling_price": price,
            "inventory_value": Decimal(balance) * cost,
        })

    rows.sort(key=lambda r: r["name"])

    return {"depot": depot.name, "products": rows}


def get_expense_report(depot, date_from=None, date_to=None):
    """
    Non-reversed expenses for a depot, grouped by category.
    """

    expenses = Expense.objects.filter(depot=depot, is_reversed=False)
    expenses = _date_range_filter(expenses, "expense_date", date_from, date_to)

    by_category = (
        expenses.values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("-total")
    )

    total = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    return {
        "depot": depot.name,
        "total_expenses": total,
        "by_category": list(by_category),
    }


def get_supplier_rebate_report(depot, date_from=None, date_to=None):
    """
    Non-reversed supplier rebates for a depot. This is real cash the
    business received back from a supplier, so — unlike the
    discount/rebate a supplier applies before invoicing us, which is
    already inside cost_price and never a separate figure — this
    amount is additional income that get_net_profit_report() folds
    in below.
    """

    rebates = SupplierRebate.objects.filter(depot=depot, is_reversed=False)
    rebates = _date_range_filter(rebates, "rebate_date", date_from, date_to)

    total = rebates.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    return {
        "depot": depot.name,
        "total_rebates": total,
    }


def get_net_profit_report(depot, date_from=None, date_to=None):
    """
    Net profit under the user's business model: recognised rebates minus
    non-reversed expenses. Sales revenue/cost remain operational metrics.
    """

    sales = Sale.objects.filter(vehicle_load__depot=depot, is_finalized=True)
    sales = _date_range_filter(sales, "sale_date", date_from, date_to)

    items = _with_revenue_cost(SaleItem.objects.filter(sale__in=sales))

    totals = items.aggregate(total_revenue=Sum("revenue"), total_cost=Sum("cost"))
    revenue = totals["total_revenue"] or Decimal("0.00")
    cost = totals["total_cost"] or Decimal("0.00")
    gross_profit = revenue - cost

    expense_report = get_expense_report(depot, date_from, date_to)
    total_expenses = expense_report["total_expenses"]

    rebate_report = get_supplier_rebate_report(depot, date_from, date_to)
    total_rebates = rebate_report["total_rebates"]

    return {
        "depot": depot.name,
        "revenue": revenue,
        "cost": cost,
        "gross_profit": gross_profit,
        "total_expenses": total_expenses,
        "total_rebates": total_rebates,
        # Business rule: NBC rebates actually received are the sole source of
        # profit. Sales turnover and gross margin are operational figures only.
        "net_profit": total_rebates - total_expenses,
    }


def get_top_selling_skus(depot, date_from=None, date_to=None, limit=10):
    items = _with_revenue_cost(SaleItem.objects.filter(
        sale__vehicle_load__depot=depot,
        sale__is_finalized=True,
    ))
    items = _date_range_filter(items, "sale__sale_date", date_from, date_to)

    ranked = (
        items.values("product__sku", "product__name")
        .annotate(quantity_sold=Sum("quantity"), revenue=Sum("revenue"))
        .order_by("-quantity_sold")[:limit]
    )

    return list(ranked)


def get_slow_moving_skus(depot, date_from=None, date_to=None, limit=10):
    """
    Products currently holding stock at this depot with the least
    (or no) sales activity in the given period.
    """

    sold = SaleItem.objects.filter(
        sale__vehicle_load__depot=depot,
        sale__is_finalized=True,
    )
    sold = _date_range_filter(sold, "sale__sale_date", date_from, date_to)

    sold_map = {
        row["product_id"]: row["quantity_sold"]
        for row in sold.values("product_id").annotate(quantity_sold=Sum("quantity"))
    }

    products_with_stock = (
        Product.objects
        .filter(inventory_transactions__depot=depot)
        .distinct()
    )

    rows = []

    for product in products_with_stock:
        balance = get_stock_balance(depot, product)

        if balance <= 0:
            continue

        rows.append({
            "sku": product.sku,
            "name": product.name,
            "stock_balance": balance,
            "quantity_sold": sold_map.get(product.id, 0),
        })

    rows.sort(key=lambda r: r["quantity_sold"])

    return rows[:limit]


# =========================
# SALESMAN REPORTS
# =========================
def get_salesman_load_return_report(salesman, date_from=None, date_to=None):
    """
    Per-load reconciliation for a salesman: what was loaded,
    returned, sold, and left unaccounted for, plus both expected
    profit (from VehicleLoadItem, tracks current pricing) and
    actual profit (from finalized Sales, frozen at sale time).
    """

    loads = VehicleLoad.objects.filter(salesman=salesman)
    loads = _date_range_filter(loads, "load_date", date_from, date_to)
    loads = loads.prefetch_related("items", "returns__items", "sales__items")

    rows = []

    for load in loads:
        loaded_qty = sum(item.quantity for item in load.items.all())

        returned_qty = sum(
            return_item.quantity
            for vehicle_return in load.returns.filter(is_confirmed=True)
            for return_item in vehicle_return.items.all()
        )

        finalized_sales = list(load.sales.filter(is_finalized=True))

        sold_qty = sum(
            sale_item.quantity
            for sale in finalized_sales
            for sale_item in sale.items.all()
        )

        rows.append({
            "load_number": load.load_number,
            "load_date": load.load_date,
            "loaded_quantity": loaded_qty,
            "returned_quantity": returned_qty,
            "sold_quantity": sold_qty,
            "unaccounted_quantity": loaded_qty - returned_qty - sold_qty,
            "expected_profit": get_expected_profit_for_load(load),
            "actual_revenue": sum((s.total_revenue for s in finalized_sales), Decimal("0.00")),
            "actual_profit": sum((s.total_profit for s in finalized_sales), Decimal("0.00")),
        })

    return {"salesman": salesman.name, "loads": rows}


def get_salesman_target_progress(salesman, year, month):
    """
    A salesman's target vs. actual for one calendar month: how many
    units they were expected to sell (SalesTarget.target_quantity,
    plus its derived daily/weekly figures), how many finalized sale
    units have actually posted so far, and the remaining balance.

    balance = target_quantity - sold_quantity. It shrinks as more
    sales are finalized and grows if the target itself is raised —
    always computed live from SalesTarget/SaleItem rather than
    stored, so it can never drift out of sync with either one.

    Returns has_target=False (with everything else zeroed out) if no
    SalesTarget has been set for this salesman/year/month yet, so
    callers can distinguish "no target set" from "target of 0".
    """

    try:
        target = SalesTarget.objects.get(salesman=salesman, year=year, month=month)
    except SalesTarget.DoesNotExist:
        target = None

    sold_quantity = SaleItem.objects.filter(
        sale__vehicle_load__salesman=salesman,
        sale__is_finalized=True,
        sale__sale_date__year=year,
        sale__sale_date__month=month,
    ).aggregate(total=Sum("quantity"))["total"] or 0

    target_quantity = target.target_quantity if target else 0

    return {
        "salesman": salesman.name,
        "year": year,
        "month": month,
        "has_target": target is not None,
        "target_quantity": target_quantity,
        "daily_target": target.daily_target if target else 0,
        "weekly_target": target.weekly_target if target else 0,
        "sold_quantity": sold_quantity,
        "balance": target_quantity - sold_quantity,
    }


# =========================
# TERRITORY REPORTS
# =========================
def get_territory_depot_comparison(territory, date_from=None, date_to=None):
    """
    Net profit comparison across every depot in a territory,
    ranked highest to lowest.
    """

    depots = Depot.objects.filter(territory=territory)

    rows = [
        get_net_profit_report(depot, date_from, date_to)
        for depot in depots
    ]

    rows.sort(key=lambda r: r["net_profit"], reverse=True)

    return {"territory": territory.name, "depots": rows}


# =========================
# FINANCE REPORTS
# =========================
def get_business_ledger_summary(depot=None, territory=None, date_from=None, date_to=None):
    """
    BusinessLedger totals grouped by transaction type, optionally
    scoped to a single depot or an entire territory.
    """

    ledger = BusinessLedger.objects.all()

    if depot is not None:
        ledger = ledger.filter(depot=depot)
    elif territory is not None:
        ledger = ledger.filter(depot__territory=territory)

    ledger = _date_range_filter(ledger, "transaction_date", date_from, date_to)

    by_type = (
        ledger.values("transaction_type")
        .annotate(total=Sum("amount"))
        .order_by("transaction_type")
    )

    return {"by_type": list(by_type)}
