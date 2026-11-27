"""
Who may create which kinds of user through the app (not Django admin).

Hierarchy (a role can create the roles BELOW it, never its own level
or above):

    Super Admin / staff  ->  Territory Manager, Depot Owner, Depot Manager,
                             Depot Officer, Finance Officer, Viewer
    Territory Manager    ->  Depot Owner, Depot Manager, Depot Officer,
                             Finance Officer, Viewer   (own territory's depots)
    Depot Manager        ->  Depot Officer, Finance Officer, Viewer
                             (own depot only)
    everyone else        ->  nobody

SALESMAN is deliberately not creatable here: a salesman login must be
linked to a VehicleSalesman profile, which Operations > Salesmen
already creates together with the login. A bare SALESMAN user made
from this page would have no profile and nothing to see in "My Loads".

Creating another Super Admin (or anyone with is_staff/is_superuser)
stays in Django admin on purpose, so the app can never be used to
escalate privileges.

To change the hierarchy, edit the tuples below - nothing else needs to
change.
"""

from core.scoping import is_unrestricted

from .models import User

_R = User.Role

_BELOW_DEPOT_MANAGER = (_R.DEPOT_OFFICER, _R.FINANCE_OFFICER, _R.VIEWER)
_BELOW_TERRITORY_MANAGER = (_R.DEPOT_OWNER, _R.DEPOT_MANAGER) + _BELOW_DEPOT_MANAGER
_BELOW_SUPER_ADMIN = (_R.TERRITORY_MANAGER,) + _BELOW_TERRITORY_MANAGER


def creatable_roles(user):
    """Role values this user may assign when creating a new user."""

    if is_unrestricted(user):
        return tuple(_BELOW_SUPER_ADMIN)

    role = getattr(user, "role", "")

    # A manager with no territory/depot has nothing to create users
    # *for* (core.scoping would show them no depots), so no rights.
    if role == _R.TERRITORY_MANAGER and user.territory_id:
        return tuple(_BELOW_TERRITORY_MANAGER)

    if role == _R.DEPOT_MANAGER and user.depot_id:
        return tuple(_BELOW_DEPOT_MANAGER)

    return ()


def can_create_users(user):
    return bool(creatable_roles(user))
