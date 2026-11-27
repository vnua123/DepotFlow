"""
Promotion visibility/edit rules.

Unlike Product/Supplier, promotions are NOT purely company-wide:
Promotion.depot is optional - blank means "applies at every depot",
set means "this depot only" (inventory.services.get_applicable_promotions
matches on exactly that). So they need depot scoping like other
depot-owned data, with one extra rule for the company-wide ones:

- visible : company-wide promotions + those for the user's own depots
            (Super Admin / staff see everything)
- editable: depot-specific -> only within the user's own depots;
            company-wide  -> only unrestricted users (a depot-level
            manager must not be able to change terms that apply to
            every other depot too)
"""

from django.db.models import Q

from core.scoping import get_visible_depots, is_unrestricted, user_can_access_depot

from .models import Promotion


def visible_promotions(user):
    if is_unrestricted(user):
        return Promotion.objects.all()
    return Promotion.objects.filter(
        Q(depot__isnull=True) | Q(depot__in=get_visible_depots(user))
    )


def can_edit_promotion(user, promotion):
    if promotion.depot_id is None:
        return is_unrestricted(user)
    return user_can_access_depot(user, promotion.depot)
