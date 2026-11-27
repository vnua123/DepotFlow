from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from datetime import date

from inventory.models import StockReceiptItem, Supplier

from . import scheme
from .models import NBCQuarterlyPlacement, MonthlyRebateAccrual

_TWO_PLACES = Decimal('0.01')


def classify_product_category(value):
    """
    Which rebate category a product belongs to, or None if it is outside
    the scheme. Works on the product category plus name, and goes by brand,
    not packaging words like CAN/PET/RGB (those say nothing about the drink).
    Schweppes counts as sparkling, as in NBC's workbook.
    """

    text = (value or '').strip().upper()
    if 'PREDATOR' in text:
        return scheme.PREDATOR
    if 'MONSTER' in text:
        return scheme.MONSTER
    if any(k in text for k in ('FIVE ALIVE', 'F/ALIVE', 'ALIVE', 'PULPY', 'JUICE')):
        return scheme.JUICE
    if any(k in text for k in ('COCA', 'COKE', 'FANTA', 'SPRITE', 'LIMCA', 'SCHWEPPES', 'SSD', 'SPARKLING', 'CARBONATED')):
        return scheme.SPARKLING
    if 'WATER' in text or 'EVA' in text:
        return scheme.WATER
    return None


def quarter_for_month(month):
    return ((int(month) - 1) // 3) + 1


def _next_quarter(year, quarter):
    return (year + 1, 1) if quarter == 4 else (year, quarter + 1)


def _quarter_volume(depot, year, quarter):
    months = list(range((quarter - 1) * 3 + 1, quarter * 3 + 1))
    rows = StockReceiptItem.objects.filter(
        stock_receipt__depot=depot,
        stock_receipt__supplier__name__iexact='NBC',
        stock_receipt__receipt_date__year=year,
        stock_receipt__receipt_date__month__in=months,
    ).aggregate(total=Sum('quantity'))
    return Decimal(rows['total'] or 0)


@transaction.atomic
def assign_initial_placement(depot, category, user, reason=''):
    """One-time setup for depots with no placement or qualifying-volume history."""
    from django.core.exceptions import PermissionDenied, ValidationError
    role = getattr(user, 'role', '')
    if role == 'DEPOT_OWNER' or (role not in ('DEPOT_MANAGER', 'DEPOT_OFFICER', 'TERRITORY_MANAGER', 'SUPER_ADMIN') and not getattr(user, 'is_superuser', False)):
        raise PermissionDenied('Only Depot Manager and above may assign an initial NBC placement.')
    from core.scoping import user_can_access_depot
    if not user_can_access_depot(user, depot):
        raise PermissionDenied('You cannot manage placement for this depot.')
    if not (reason or '').strip():
        raise ValidationError('A reason is required for the initial placement.')
    if category not in NBCQuarterlyPlacement.Category.values:
        raise ValidationError('Select a valid NBC placement category.')
    if NBCQuarterlyPlacement.objects.filter(depot=depot).exists():
        raise ValidationError('Initial placement is locked because this depot already has placement history.')
    if StockReceiptItem.objects.filter(stock_receipt__depot=depot, stock_receipt__supplier__name__iexact='NBC').exists():
        raise ValidationError('Initial placement is locked because qualifying NBC volume data already exists. Run the quarter-end assessment instead.')
    today = timezone.localdate()
    quarter = ((today.month - 1) // 3) + 1
    placement = NBCQuarterlyPlacement.objects.create(
        depot=depot, year=today.year, quarter=quarter, qualifying_cases=0,
        category=category, calculated_category=category, is_initial=True,
        is_manual_initial=True, calculated_by=user, approved_by=user,
        approved_at=timezone.now(), reason=reason,
        notes='Initial manual placement; no previous placement or qualifying NBC volume history.',
    )
    return placement


@transaction.atomic
def calculate_quarterly_placement(depot, year, quarter, user=None):
    """Assess a completed calendar quarter; placement takes effect next quarter."""
    from django.core.exceptions import ValidationError
    if quarter not in (1, 2, 3, 4):
        raise ValidationError('Quarter must be between 1 and 4.')
    today = timezone.localdate()
    quarter_end_month = quarter * 3
    quarter_end = date(year, quarter_end_month, 1)
    if quarter_end_month == 12:
        quarter_end = date(year + 1, 1, 1)
    else:
        quarter_end = date(year, quarter_end_month + 1, 1)
    if today < quarter_end:
        raise ValidationError('Placement can only be assessed after the calendar quarter has ended.')

    volume = _quarter_volume(depot, year, quarter)
    category = NBCQuarterlyPlacement.category_for_volume(volume)
    effective_year, effective_quarter = _next_quarter(year, quarter)
    existing = NBCQuarterlyPlacement.objects.filter(depot=depot, year=effective_year, quarter=effective_quarter).first()
    if existing:
        # Never rewrite an already-effective placement or any historical row.
        if existing.is_initial or existing.assessment_year == year and existing.assessment_quarter == quarter:
            return existing
        raise ValidationError('A placement already exists for the next quarter. Existing placement history will not be overwritten.')

    return NBCQuarterlyPlacement.objects.create(
        depot=depot, year=effective_year, quarter=effective_quarter,
        assessment_year=year, assessment_quarter=quarter,
        qualifying_cases=volume, category=category, calculated_category=category,
        calculated_by=user, approved_by=user, approved_at=timezone.now(),
        reason='Quarter-end NBC volume assessment.',
        notes=f'Assessed {year} Q{quarter}; effective {effective_year} Q{effective_quarter}.',
    )


@transaction.atomic
def calculate_monthly_rebates(depot, year, month, user=None):
    """
    Monthly rebate estimate per category.

    The quarter's placement picks the rate table; the category's cases for
    this month pick the rate inside it; the rate is applied to the rebate-based
    (tax-free landing) cost of those cases. Estimates already CONFIRMED or PAID
    are left alone so a recalculation cannot overwrite them.
    """
    quarter = quarter_for_month(month)
    placement = NBCQuarterlyPlacement.objects.filter(depot=depot, year=year, quarter=quarter).first()
    if placement is None:
        raise ValueError(f'No NBC placement is effective for {year} Q{quarter}. Assign an initial placement or complete the prior quarter-end assessment first.')

    items = StockReceiptItem.objects.filter(
        stock_receipt__depot=depot,
        stock_receipt__supplier__name__iexact='NBC',
        stock_receipt__receipt_date__year=year,
        stock_receipt__receipt_date__month=month,
    ).select_related('product', 'stock_receipt')

    grouped = defaultdict(lambda: {'qty': Decimal('0'), 'cost': Decimal('0'), 'review': set()})
    for item in items:
        category = classify_product_category(f'{item.product.category} {item.product.name}')
        if category is None:
            continue
        qty = Decimal(item.quantity or 0)
        grouped[category]['qty'] += qty
        grouped[category]['cost'] += qty * Decimal(item.effective_rebate_landing_cost or 0)
        if item.rebate_cost_needs_review:
            grouped[category]['review'].add(item.product.name)

    supplier = Supplier.objects.filter(name__iexact='NBC').first()
    if supplier is None:
        raise ValueError('Create the NBC supplier record before calculating rebates. Historical suppliers are not deleted.')

    results = []
    for category in scheme.CATEGORY_ORDER:
        values = grouped.get(category)
        if values is None:
            continue
        qty, landing_cost = values['qty'], values['cost']
        rate = scheme.get_rate(placement.category, category, qty)
        amount = (landing_cost * rate / Decimal('100')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        note = (
            f"{placement.get_category_display()} placement; {qty} cases this month at {rate}% "
            f"of landing cost (tax removed)."
        )
        if values['review']:
            note += ' Pack size unreadable, excise not deducted for: ' + ', '.join(sorted(values['review'])) + '. Enter the landing cost on the receipt line.'

        existing = MonthlyRebateAccrual.objects.filter(
            depot=depot, year=year, month=month, product_category=category,
        ).first()
        if existing and existing.status in (MonthlyRebateAccrual.Status.CONFIRMED, MonthlyRebateAccrual.Status.PAID):
            results.append(existing)
            continue

        record, _ = MonthlyRebateAccrual.objects.update_or_create(
            depot=depot, year=year, month=month, product_category=category,
            defaults={
                'supplier': supplier,
                'qualifying_cases': qty,
                'landing_cost_total': landing_cost.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP),
                'rebate_rate': rate,
                'estimated_amount': amount,
                'placement': placement,
                'calculation_notes': note,
                'created_by': user,
            },
        )
        results.append(record)
    return results
