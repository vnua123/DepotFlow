"""
Depot Owner overview: the figures an owner of one depot wants in front of
them, each marked as either live (calculated from the app right now) or
"as of" a saved date (taken from the last monthly health check or the
last rebate calculation).

Read-only: nothing here writes to the database.
"""

from datetime import date as date_cls
from decimal import Decimal

from django.db.models import Sum

from finance.models import Expense
from operations.models import VehicleLoad
from rebates.models import MonthlyHealthCheck, MonthlyProfitability, MonthlyRebateAccrual

from . import services

ZERO = Decimal("0.00")
DEFAULT_REINVESTMENT_PERCENT = Decimal("20.00")


def _stock_on_open_loads(depot):
    """Value (at current acquisition cost) of what is still on the trucks."""
    value = ZERO
    units = 0
    for load in VehicleLoad.objects.filter(depot=depot, is_closed=False):
        items = {item.product_id: item for item in load.items.all()}
        for row in load.reconciliation_status():
            remaining = row["remaining"]
            if remaining > 0:
                units += remaining
                value += Decimal(remaining) * items[row["product"].pk].effective_cost_price
    return {"value": value, "units": units}


def _months_between(year_a, month_a, year_b, month_b):
    return (year_b * 12 + month_b) - (year_a * 12 + month_a)


def _working_capital(depot, today, live_stock_value):
    check = MonthlyHealthCheck.objects.filter(depot=depot).order_by("-year", "-month").first()
    if check is None:
        return None

    previous = check.previous_month_health_check
    return {
        "check": check,
        "period": date_cls(check.year, check.month, 1),
        "recorded_on": check.completed_at,
        "total": check.total_working_capital,
        "operator_owned": check.operator_owned_working_capital,
        "equity_percent": check.operator_equity_percent,
        "stock_value": check.grand_total_stock_value,
        "stock_cases": check.grand_total_stock_cases,
        "cash": check.cash_at_hand,
        "git": check.git_order_released,
        "git_cases": check.git_order_released_cases,
        "credit_exposure": check.credit_exposure_balance,
        "credit_limit": check.nbc_credit_limit,
        "credit_utilization": check.nbc_credit_utilization_percent,
        "empties_quantity": check.empties_quantity,
        "plastic_quantity": check.plastic_quantity,
        "change": (check.total_working_capital - previous.total_working_capital) if previous else None,
        "previous_period": date_cls(previous.year, previous.month, 1) if previous else None,
        # Live stock now compared with the stock the health check recorded.
        "stock_change_since_check": live_stock_value - check.grand_total_stock_value,
        # A check for month M should exist by early M+1; two months behind is overdue.
        "is_stale": _months_between(check.year, check.month, today.year, today.month) >= 2,
    }


def _reinvestment_target_percent(depot, today):
    record = (
        MonthlyProfitability.objects.filter(depot=depot, year=today.year, month=today.month).first()
        or MonthlyProfitability.objects.filter(depot=depot).order_by("-year", "-month").first()
    )
    return record.target_reinvestment_percent if record else DEFAULT_REINVESTMENT_PERCENT


def _reinvestment_history(depot, limit=4):
    rows = []
    for record in MonthlyProfitability.objects.filter(depot=depot).order_by("-year", "-month")[:limit]:
        observed = record.observed_reinvestment
        if not record.has_working_capital_baseline:
            status = "pending"          # the following month's health check is not in yet
        elif record.net_profit <= 0:
            status = "no_profit"        # nothing to reinvest that month
        elif observed >= record.required_reinvestment:
            status = "met"
        else:
            status = "below"
        rows.append({
            "status": status,
            "period": date_cls(record.year, record.month, 1),
            "net_profit": record.net_profit,
            "target_percent": record.target_reinvestment_percent,
            "required": record.required_reinvestment,
            "observed": observed,
            "actual_percent": record.actual_reinvestment_percent,
            "pending": not record.has_working_capital_baseline,
            "flagged": record.is_flagged,
        })
    return rows


def get_owner_overview(depot, today=None):
    today = today or date_cls.today()
    month_start = today.replace(day=1)

    # ---- live, right now -------------------------------------------------
    inventory = services.get_current_inventory_report(depot)["products"]
    stock_value = sum((r["inventory_value"] for r in inventory), ZERO)
    stock_units = sum((r["stock_balance"] for r in inventory if r["stock_balance"] > 0), 0)

    open_loads = VehicleLoad.objects.filter(depot=depot, is_closed=False)
    pending = Expense.objects.filter(depot=depot, approved=False, is_reversed=False)
    pending_totals = pending.aggregate(total=Sum("amount"))

    on_trucks = _stock_on_open_loads(depot)

    live = {
        "stock_value": stock_value,
        "stock_units": stock_units,
        "stock_skus": sum(1 for r in inventory if r["stock_balance"] > 0),
        "on_trucks": on_trucks,
        "total_stock_value": stock_value + on_trucks["value"],
        "open_loads": open_loads.count(),
        "overdue_loads": open_loads.filter(load_date__lt=today).count(),
        "pending_expense_count": pending.count(),
        "pending_expense_total": pending_totals["total"] or ZERO,
    }

    # ---- month to date ---------------------------------------------------
    sales = services.get_sales_summary_for_range(depot, month_start, today)
    profit = services.get_net_profit_report(depot, month_start, today)
    expenses = services.get_expense_report(depot, month_start, today)

    accruals = MonthlyRebateAccrual.objects.filter(
        depot=depot, year=today.year, month=today.month,
    ).exclude(status=MonthlyRebateAccrual.Status.VOID)
    accrual_total = accruals.aggregate(total=Sum("estimated_amount"))["total"]
    last_accrual = accruals.order_by("-updated_at").first()

    target_percent = _reinvestment_target_percent(depot, today)
    net_profit = profit["net_profit"]
    required_to_date = (
        (net_profit * target_percent / Decimal("100")).quantize(Decimal("0.01"))
        if net_profit > 0 else ZERO
    )

    month = {
        "start": month_start,
        "revenue": sales["total_revenue"],
        "units_sold": sales["total_quantity"],
        "gross_margin": sales["total_profit"],
        "expenses": profit["total_expenses"],
        "rebates_received": profit["total_rebates"],
        "net_profit": net_profit,
        "expected_rebate": accrual_total,            # None when nobody has calculated it yet
        "expected_rebate_as_of": last_accrual.updated_at if last_accrual else None,
        "reinvestment_target_percent": target_percent,
        "required_reinvestment_to_date": required_to_date,
        "top_expense_categories": expenses["by_category"][:5],
    }

    working_capital = _working_capital(depot, today, stock_value)

    alerts = []
    if live["pending_expense_count"]:
        alerts.append(f'{live["pending_expense_count"]} expense'
                      f'{"s" if live["pending_expense_count"] != 1 else ""} waiting for approval')
    if live["overdue_loads"]:
        alerts.append(f'{live["overdue_loads"]} vehicle load'
                      f'{"s" if live["overdue_loads"] != 1 else ""} still open from an earlier day')
    if working_capital is None:
        alerts.append("No monthly health check has been recorded yet")
    elif working_capital["is_stale"]:
        alerts.append("The last monthly health check is more than a month old")

    return {
        "as_of": today,
        "live": live,
        "month": month,
        "working_capital": working_capital,
        "reinvestment": _reinvestment_history(depot),
        "alerts": alerts,
    }
