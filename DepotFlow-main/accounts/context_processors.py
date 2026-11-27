"""
Role-based navigation visibility.

This intentionally mirrors the role groupings already enforced in
depots/inventory/operations/sales/finance views.py
(_can_manage_depots, _can_manage_inventory, _can_manage_operations,
_can_manage_sales, _can_record_expenses, _can_approve_finance) —
it does not invent new business rules, it just decides which nav
sections are worth showing a given role.

Navigation visibility is a usability layer, not a security boundary.
Sensitive pages such as NBC rebates and team management also enforce
role restrictions in their views, so hiding a link is not the only
protection. Depot Owners retain view-only access to operational sections.
"""


def nav_visibility(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {}

    role = getattr(user, "role", "")
    # DEPOT_OWNER is a deliberately restricted role. Its permissions must
    # take precedence over an accidentally set Django staff flag.
    is_depot_owner = role == "DEPOT_OWNER"
    is_admin = (not is_depot_owner) and (user.is_staff or role == "SUPER_ADMIN")
    can_manage_territories = role == "SUPER_ADMIN" or (
        user.is_staff and role not in ("DEPOT_OWNER", "TERRITORY_MANAGER")
    )

    show_depots = (not is_depot_owner) and (is_admin or role in ("TERRITORY_MANAGER", "VIEWER"))
    show_inventory = is_admin or role in ("DEPOT_OWNER", "DEPOT_MANAGER", "DEPOT_OFFICER", "VIEWER")
    show_operations = is_admin or role in ("DEPOT_OWNER", "DEPOT_MANAGER", "DEPOT_OFFICER", "VIEWER")
    show_sales = is_admin or role in ("DEPOT_OWNER", "DEPOT_MANAGER", "DEPOT_OFFICER", "SALESMAN", "VIEWER")

    # Finance is split three ways because the underlying permissions
    # already are: DEPOT_OFFICER can record expenses but not approve
    # them or touch supplier payments/rebates/ledger; TERRITORY_MANAGER
    # can't record anything but has an oversight reason to see the
    # ledger. Only one of these three should end up true per user.
    show_finance_full = is_admin or role in ("DEPOT_OWNER", "DEPOT_MANAGER", "FINANCE_OFFICER", "VIEWER")
    show_finance_expenses_only = (not show_finance_full) and role == "DEPOT_OFFICER"
    show_finance_ledger_only = (not show_finance_full) and role == "TERRITORY_MANAGER"

    # "My Loads" is a personal page, not a management one — shown
    # only to the Salesman role itself, regardless of show_sales
    # above (which is about managing Sales/Customers, a different
    # permission entirely).
    show_my_loads = role == "SALESMAN"
    show_nbc_rebates = (not is_depot_owner) and (
        role in ("DEPOT_MANAGER", "FINANCE_OFFICER", "SUPER_ADMIN") or user.is_staff
    )
    show_team = not is_depot_owner

    # Setting targets is stricter than general operations management
    # (mirrors operations.views._can_set_targets), but the Targets
    # *list* is visible to anyone who can see Operations at all.
    show_targets = show_operations

    # Territory Manager doesn't get the full Inventory dropdown (they
    # don't run day-to-day receiving/pricing), but they do need to
    # check stock across every depot they oversee — so Stock View
    # gets its own flag rather than riding on show_inventory.
    show_stock_view_standalone = (not show_inventory) and role == "TERRITORY_MANAGER"

    return {
        "nav_is_depot_owner": is_depot_owner,
        "nav_show_depots": show_depots,
        "nav_manage_territories": can_manage_territories,
        "nav_show_inventory": show_inventory,
        "nav_show_operations": show_operations,
        "nav_show_sales": show_sales,
        "nav_show_finance_full": show_finance_full,
        "nav_show_finance_expenses_only": show_finance_expenses_only,
        "nav_show_finance_ledger_only": show_finance_ledger_only,
        "nav_show_any_finance": show_finance_full or show_finance_expenses_only or show_finance_ledger_only,
        "nav_show_my_loads": show_my_loads,
        "nav_show_nbc_rebates": show_nbc_rebates,
        "nav_show_team": show_team,
        "nav_show_targets": show_targets,
        "nav_show_stock_view_standalone": show_stock_view_standalone,
        # A role that sees every operational section gets the full
        # numbered workflow on the home page; everyone else gets a
        # shorter, role-tailored set of quick links instead.
        "nav_full_workflow": show_depots and show_inventory and show_operations and show_sales and show_finance_full,
    }
