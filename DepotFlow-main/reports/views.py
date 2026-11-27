"""
Thin JSON views for reports. All calculation logic lives in
services.py -- views here only parse request parameters, fetch the
relevant object, call the matching service function, and return it
as JSON.

Every view requires login for now, as a baseline. Full role-based
scoping (e.g. a Territory Manager only seeing their own territory)
is handled in the broader views/permissions pass, not here.
"""

from datetime import date as date_cls, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from depots.models import Depot, Territory
from operations.models import VehicleSalesman
from core.scoping import get_visible_depots, user_can_access_depot, user_can_access_territory, is_unrestricted
from . import owner_overview, services


def _parse_date(value):
    if not value:
        return None
    return date_cls.fromisoformat(value)


def _get_accessible_depot_or_403(request, depot_id):
    """
    Shared by every depot_id-based JSON report endpoint below: fetch
    the depot, and refuse (403) if this user isn't allowed to see
    it — a filtered list view doesn't stop someone from requesting a
    specific depot_id directly, so every one of these needs the same
    object-level check core.scoping.user_can_access_depot() provides.
    Returns (depot, None) on success, or (None, error_response) to
    return directly from the calling view.
    """

    depot = get_object_or_404(Depot, pk=depot_id)

    if not user_can_access_depot(request.user, depot):
        return None, JsonResponse({"error": "You do not have access to that depot."}, status=403)

    return depot, None


@login_required
@require_GET
def daily_sales_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    report_date = _parse_date(request.GET.get("date")) or date_cls.today()
    return JsonResponse(services.get_daily_sales_report(depot, report_date))


@login_required
@require_GET
def daily_stock_movement_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    report_date = _parse_date(request.GET.get("date")) or date_cls.today()
    return JsonResponse(services.get_daily_stock_movement_report(depot, report_date))


@login_required
@require_GET
def current_inventory_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    return JsonResponse(services.get_current_inventory_report(depot))


@login_required
@require_GET
def expense_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    return JsonResponse(services.get_expense_report(depot, date_from, date_to))


@login_required
@require_GET
def net_profit_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    return JsonResponse(services.get_net_profit_report(depot, date_from, date_to))


@login_required
@require_GET
def top_selling_skus_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    limit = int(request.GET.get("limit", 10))
    return JsonResponse(
        {"skus": services.get_top_selling_skus(depot, date_from, date_to, limit)}
    )


@login_required
@require_GET
def slow_moving_skus_report(request, depot_id):
    depot, error = _get_accessible_depot_or_403(request, depot_id)
    if error:
        return error
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    limit = int(request.GET.get("limit", 10))
    return JsonResponse(
        {"skus": services.get_slow_moving_skus(depot, date_from, date_to, limit)}
    )


@login_required
@require_GET
def salesman_load_return_report(request, salesman_id):
    salesman = get_object_or_404(VehicleSalesman, pk=salesman_id)

    if not user_can_access_depot(request.user, salesman.depot):
        return JsonResponse({"error": "You do not have access to that salesman."}, status=403)

    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    return JsonResponse(services.get_salesman_load_return_report(salesman, date_from, date_to))


@login_required
@require_GET
def territory_comparison_report(request, territory_id):
    territory = get_object_or_404(Territory, pk=territory_id)

    if not user_can_access_territory(request.user, territory):
        return JsonResponse({"error": "You do not have access to that territory."}, status=403)

    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    return JsonResponse(services.get_territory_depot_comparison(territory, date_from, date_to))


@login_required
@require_GET
def business_ledger_summary_report(request):
    depot_id = request.GET.get("depot_id")
    territory_id = request.GET.get("territory_id")
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

    depot = None
    territory = None

    if depot_id:
        depot = get_object_or_404(Depot, pk=depot_id)
        if not user_can_access_depot(request.user, depot):
            return JsonResponse({"error": "You do not have access to that depot."}, status=403)
    elif territory_id:
        territory = get_object_or_404(Territory, pk=territory_id)
        if not user_can_access_territory(request.user, territory):
            return JsonResponse({"error": "You do not have access to that territory."}, status=403)
    elif not is_unrestricted(request.user):
        # Neither param given, and this user isn't unrestricted —
        # default to their own depot rather than falling back to
        # every depot, which get_business_ledger_summary() would
        # otherwise return for depot=None, territory=None.
        if request.user.depot_id:
            depot = request.user.depot
        else:
            return JsonResponse({"error": "No depot is assigned to your account."}, status=403)

    return JsonResponse(
        services.get_business_ledger_summary(depot, territory, date_from, date_to)
    )


@login_required
def stock_view(request):
    """
    Human-facing "what's actually in stock right now" page — the
    HTML counterpart to current_inventory_report's JSON, with a
    depot switcher instead of requiring a depot_id in the URL.

    Scoped the same way as everywhere else via core.scoping: Super
    Admin sees every depot, Territory Manager sees every depot in
    their own territory, everyone else only their own single depot.
    A ?depot= query param outside what get_visible_depots() allows
    is rejected (404), not silently honored — this can't be bypassed
    by editing the URL.
    """

    user = request.user
    depots = get_visible_depots(user).order_by("name")
    depot_id = request.GET.get("depot")

    if depot_id:
        depot = get_object_or_404(depots, pk=depot_id)
    elif user.depot_id:
        depot = user.depot
    else:
        depot = depots.first()

    report = services.get_current_inventory_report(depot) if depot else None
    total_value = sum((row["inventory_value"] for row in report["products"]), Decimal("0.00")) if report else Decimal("0.00")

    return render(request, "reports/stock_view.html", {
        "depots": depots,
        "depot": depot,
        "report": report,
        "total_value": total_value,
    })


@login_required
def dashboard(request):
    """
    Role-specific KPI landing page (spec section 22).

    - Depot Manager / Depot Officer / Depot Owner: figures for their own depot
      (units sold, revenue, expenses, net position) over a chosen
      timeframe — defaults to today, plus this month's target
      progress for every salesman at that depot (target periods are
      always calendar-monthly, so that part doesn't move with the
      timeframe picker).
    - Salesman: their own current-month target progress and open
      loads — needs request.user.salesman_profile, the link created
      alongside a VehicleSalesman in operations.forms.VehicleSalesmanForm.
    - Territory Manager: net-profit ranking across every depot in
      their territory, over a chosen timeframe — defaults to
      month-to-date.
    - Super Admin: the same ranking, one table per territory, across
      the whole business — same default.

    Every timeframe above is overridable via ?date_from=&date_to= —
    see templates/partials/date_range_form.html, included with quick
    links for Today/This Week/Month to Date plus a manual range. A
    single day of net profit ranks depots almost arbitrarily (a depot
    with zero activity today just sits at the bottom), which is why
    the ranking views default to month-to-date rather than today —
    they can still be pointed at a single day if that's ever useful.

    Finance Officer/Viewer get no KPI cards yet — not specified. They
    still see the existing hub of links below.
    """

    user = request.user
    today = date_cls.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())

    date_from_param = _parse_date(request.GET.get("date_from"))
    date_to_param = _parse_date(request.GET.get("date_to"))

    context = {
        "today": today,
        "month_start": month_start,
        "week_start": week_start,
    }

    if user.is_depot_manager or user.is_depot_officer or user.is_depot_owner:
        date_from = date_from_param or today
        date_to = date_to_param or today
        context["date_from"] = date_from
        context["date_to"] = date_to

        if user.depot_id:
            if user.is_depot_owner:
                context["owner_overview"] = owner_overview.get_owner_overview(user.depot, today)
            context["depot_sales"] = services.get_sales_summary_for_range(user.depot, date_from, date_to)
            context["depot_net_profit"] = services.get_net_profit_report(user.depot, date_from, date_to)
            context["salesmen_progress"] = [
                services.get_salesman_target_progress(salesman, today.year, today.month)
                for salesman in VehicleSalesman.objects.filter(
                    depot=user.depot, is_active=True
                ).order_by("name")
            ]
        else:
            context["no_depot_assigned"] = True

    elif user.is_salesman:
        salesman = getattr(user, "salesman_profile", None)
        if salesman is not None:
            context["my_target_progress"] = services.get_salesman_target_progress(
                salesman, today.year, today.month
            )
            context["my_open_loads"] = salesman.vehicle_loads.filter(is_closed=False).order_by("-load_date")
        else:
            context["no_salesman_profile"] = True

    elif user.is_territory_manager:
        date_from = date_from_param or month_start
        date_to = date_to_param or today
        context["date_from"] = date_from
        context["date_to"] = date_to

        if user.territory_id:
            context["territory_comparison"] = services.get_territory_depot_comparison(
                user.territory, date_from, date_to
            )
        else:
            context["no_territory_assigned"] = True

    elif user.is_super_admin:
        date_from = date_from_param or month_start
        date_to = date_to_param or today
        context["date_from"] = date_from
        context["date_to"] = date_to

        context["all_territory_comparisons"] = [
            services.get_territory_depot_comparison(territory, date_from, date_to)
            for territory in Territory.objects.all().order_by("name")
        ]

    return render(request, "reports/dashboard.html", context)