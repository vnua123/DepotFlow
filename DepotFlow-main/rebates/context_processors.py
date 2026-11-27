"""Compatibility context processors for DepotFlow rebate navigation.

Some existing installations reference ``rebates.context_processors.rebate_visibility``
while newer settings use ``accounts.context_processors.nav_visibility``. Keep both
entry points available and preserve the existing role-based navigation rules.
"""

from accounts.context_processors import nav_visibility


def rebate_visibility(request):
    """Return existing navigation flags plus rebate-specific visibility flags.

    This is a presentation helper only; views must continue enforcing permissions.
    """
    context = nav_visibility(request)
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        context.update({"nav_show_rebates": False, "can_manage_rebates": False})
        return context

    role = getattr(user, "role", "")
    is_admin = bool(getattr(user, "is_staff", False)) or role == "SUPER_ADMIN"
    can_manage = is_admin or role in ("DEPOT_MANAGER", "FINANCE_OFFICER")
    # Authenticated users may view the rebate dashboard; only authorised roles
    # can perform management actions, which are independently checked in views.
    context.update({"nav_show_rebates": True, "can_manage_rebates": can_manage})
    return context


__all__ = ["nav_visibility", "rebate_visibility"]
