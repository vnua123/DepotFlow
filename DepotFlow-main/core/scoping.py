"""
Depot/territory access scoping, used across every app that has
depot-owned data (vehicles, salesmen, loads, returns, sales targets,
customers, sales, stock receipts, expenses, supplier payments/rebates,
the business ledger).

Super Admin (and Django staff) are unrestricted everywhere — this
module only ever narrows things down for everyone else:

- Territory Manager: everything within their own territory (every
  depot that belongs to it).
- Every other role (Depot Manager, Depot Officer, Finance Officer,
  Salesman, Viewer): only their own single assigned depot.

A user with no depot and no territory assigned sees nothing — that's
a deliberate fail-closed default, not a bug: an unconfigured account
should never fall back to "see everything".

Two kinds of helper here:
- get_visible_depots()/get_visible_territories() narrow QUERYSETS for
  list views.
- user_can_access_depot() is for OBJECT-LEVEL checks in detail/edit/
  delete/close/confirm views and JSON report endpoints — a list view
  being filtered doesn't stop someone from requesting a specific
  object's URL directly (by its primary key, or a depot_id query
  param) for something outside their own depot/territory, so every
  view that fetches a single depot-owned object by pk must also call
  this, not just filter the list.

Deliberately NOT scoped by this module: Product, Supplier, and
Promotion. These are shared master/reference data — a product's
price and a supplier's details aren't owned by one depot, they're
the same everywhere in the business — so restricting them per depot
would be incorrect, not just unnecessary. Only genuinely depot-owned
transactional data (the apps listed above) goes through this.
"""

from depots.models import Depot, Territory


def _role(user):
    return getattr(user, "role", "")


def get_default_depot(user):
    """
    If this user has exactly one visible depot, return it — forms
    use this to auto-fill and hide their depot field instead of
    showing a dropdown with a single, forced option. Returns None
    when there's a genuine choice to make (Super Admin, or a
    Territory Manager overseeing more than one depot), or when the
    user has no visible depot at all (in which case the form's
    depot queryset is already empty, so validation will correctly
    block creation regardless).
    """

    depots = list(get_visible_depots(user)[:2])
    return depots[0] if len(depots) == 1 else None


def is_unrestricted(user):
    """Super Admin (or Django staff) — no scoping applies at all."""
    role = _role(user)
    # Scoped managerial roles must remain scoped even if an account was
    # accidentally marked as Django staff.
    if role in ("TERRITORY_MANAGER", "DEPOT_OWNER"):
        return False
    return bool(user.is_staff or role == "SUPER_ADMIN")


def get_visible_depots(user):
    """Depots this user is allowed to see or act within."""

    if is_unrestricted(user):
        return Depot.objects.all()

    if _role(user) == "TERRITORY_MANAGER" and user.territory_id:
        return Depot.objects.filter(territory_id=user.territory_id)

    if user.depot_id:
        return Depot.objects.filter(pk=user.depot_id)

    return Depot.objects.none()


def get_visible_territories(user):
    """Territories this user is allowed to see."""

    if is_unrestricted(user):
        return Territory.objects.all()

    if _role(user) == "TERRITORY_MANAGER" and user.territory_id:
        return Territory.objects.filter(pk=user.territory_id)

    if user.depot_id:
        return Territory.objects.filter(depots__pk=user.depot_id).distinct()

    return Territory.objects.none()


def user_can_access_depot(user, depot):
    """
    Object-level check for detail/edit/delete/close/confirm views and
    JSON report endpoints — whether this user is allowed to see or
    act on something belonging to this depot. depot may be None (an
    object with no depot at all), in which case only Super
    Admin/staff can access it.
    """

    if depot is None:
        return is_unrestricted(user)

    return get_visible_depots(user).filter(pk=depot.pk).exists()


def user_can_access_territory(user, territory):
    """Object-level check for a specific Territory, mirroring user_can_access_depot()."""

    if territory is None:
        return is_unrestricted(user)

    return get_visible_territories(user).filter(pk=territory.pk).exists()
