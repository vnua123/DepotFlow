from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction

from core.scoping import get_visible_depots, get_visible_territories, user_can_access_depot
from .models import Territory, Depot
from .forms import TerritoryForm, DepotForm


def _is_global_depot_admin(user):
    """Global depot administrator; scoped managers are never global admins."""
    role = getattr(user, "role", "")
    if role in ("TERRITORY_MANAGER", "DEPOT_OWNER"):
        return False
    return bool(user.is_staff or role == "SUPER_ADMIN")


def _can_manage_depots(user):
    """Super Admins manage all depots; Commercial Managers manage their territory."""
    return _is_global_depot_admin(user) or (
        getattr(user, "role", "") == "TERRITORY_MANAGER"
        and bool(getattr(user, "territory_id", None))
    )


def _depot_form(request, *args, **kwargs):
    return DepotForm(*args, user=request.user, **kwargs)


@login_required
def territory_list(request):
    territories = get_visible_territories(request.user).order_by("name")
    return render(request, "depots/territory_list.html", {
        "territories": territories,
        "can_manage_territories": _is_global_depot_admin(request.user),
    })


@login_required
def territory_create(request):
    if not _is_global_depot_admin(request.user):
        messages.error(request, "Only Super Admins can create territories.")
        return redirect("depots:territory_list")

    if request.method == "POST":
        form = TerritoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Territory created.")
            return redirect("depots:territory_list")
    else:
        form = TerritoryForm()

    return render(request, "depots/territory_form.html", {"form": form, "title": "New Territory"})


@login_required
def territory_update(request, pk):
    if not _is_global_depot_admin(request.user):
        messages.error(request, "Only Super Admins can edit territories.")
        return redirect("depots:territory_list")
    territory = get_object_or_404(Territory, pk=pk)

    if request.method == "POST":
        form = TerritoryForm(request.POST, instance=territory)
        if form.is_valid():
            form.save()
            messages.success(request, "Territory updated.")
            return redirect("depots:territory_list")
    else:
        form = TerritoryForm(instance=territory)

    return render(request, "depots/territory_form.html", {"form": form, "title": "Edit Territory"})


@login_required
def depot_list(request):
    depots = get_visible_depots(request.user).select_related("territory").order_by("name")
    can_manage = _can_manage_depots(request.user)
    return render(request, "depots/depot_list.html", {
        "depots": depots,
        "can_manage_depots": can_manage,
        "can_manage_territories": _is_global_depot_admin(request.user),
    })


@login_required
def depot_detail(request, pk):
    depot = get_object_or_404(Depot.objects.select_related("territory"), pk=pk)

    if not user_can_access_depot(request.user, depot):
        messages.error(request, "You do not have access to that depot.")
        return redirect("depots:depot_list")

    can_edit = _can_manage_depots(request.user) and (
        _is_global_depot_admin(request.user)
        or depot.territory_id == getattr(request.user, "territory_id", None)
    )
    return render(request, "depots/depot_detail.html", {"depot": depot, "can_edit_depot": can_edit})


@login_required
@transaction.atomic
def depot_create(request):
    if not _can_manage_depots(request.user):
        messages.error(request, "You do not have permission to create depots.")
        return redirect("depots:depot_list")

    if request.method == "POST":
        form = _depot_form(request, request.POST)
        if form.is_valid():
            depot = form.save(commit=False)
            if not _is_global_depot_admin(request.user):
                # Do not trust a submitted territory value, even if a
                # crafted request bypasses the rendered form.
                depot.territory_id = request.user.territory_id
            depot.save()
            initial_category = form.cleaned_data.get('initial_nbc_category')
            if initial_category:
                from rebates.services import assign_initial_placement
                assign_initial_placement(depot, initial_category, request.user, form.cleaned_data.get('initial_nbc_reason', '').strip())
            messages.success(request, "Depot created.")
            return redirect("depots:depot_list")
    else:
        form = _depot_form(request)

    return render(request, "depots/depot_form.html", {"form": form, "title": "New Depot"})


@login_required
def depot_update(request, pk):
    if _is_global_depot_admin(request.user):
        depot = get_object_or_404(Depot, pk=pk)
    elif getattr(request.user, "role", "") == "TERRITORY_MANAGER" and request.user.territory_id:
        depot = get_object_or_404(
            Depot.objects.filter(territory_id=request.user.territory_id), pk=pk
        )
    else:
        messages.error(request, "You do not have permission to edit depots.")
        return redirect("depots:depot_list")

    if request.method == "POST":
        form = _depot_form(request, request.POST, instance=depot)
        if form.is_valid():
            updated_depot = form.save(commit=False)
            if getattr(request.user, "role", "") == "TERRITORY_MANAGER":
                updated_depot.territory_id = request.user.territory_id
            updated_depot.save()
            messages.success(request, "Depot updated.")
            return redirect("depots:depot_list")
    else:
        form = _depot_form(request, instance=depot)

    return render(request, "depots/depot_form.html", {"form": form, "title": "Edit Depot"})
