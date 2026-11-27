from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from reports.services import get_salesman_target_progress
from sales.models import Sale, SaleItem
from core.scoping import get_visible_depots, user_can_access_depot

from .models import Vehicle, VehicleSalesman, VehicleLoad, VehicleReturn, VehicleReturnItem, SalesTarget
from .forms import (
    VehicleForm, VehicleReassignForm, VehicleSalesmanForm, VehicleLoadForm, VehicleLoadItemFormSet,
    VehicleReturnForm, VehicleReturnItemFormSet, SalesTargetForm, LoadCloseForm,
)


def _can_manage_operations(user):
    """
    Staff, SUPER_ADMIN, DEPOT_MANAGER, or DEPOT_OFFICER can manage
    vehicles, salesmen, loads, and returns.
    """

    if getattr(user, "role", "") == "DEPOT_OWNER":
        return False

    return user.is_staff or getattr(user, "role", "") in (
        "SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER",
    )


def _can_set_targets(user):
    """
    Setting a salesman's target is stricter than general operations
    management — only Depot Manager and Super Admin.
    """

    if getattr(user, "role", "") == "DEPOT_OWNER":
        return False

    return user.is_staff or getattr(user, "role", "") in ("SUPER_ADMIN", "DEPOT_MANAGER")


# =========================
# VEHICLES
# =========================
@login_required
def vehicle_list(request):
    vehicles = Vehicle.objects.filter(depot__in=get_visible_depots(request.user)).select_related("depot").order_by("registration_number")
    return render(request, "operations/vehicle_list.html", {"vehicles": vehicles, "can_manage": _can_manage_operations(request.user)})


@login_required
def vehicle_create(request):
    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to create vehicles.")
        return redirect("operations:vehicle_list")

    if request.method == "POST":
        form = VehicleForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehicle created.")
            return redirect("operations:vehicle_list")
    else:
        form = VehicleForm(user=request.user)

    return render(request, "operations/vehicle_form.html", {"form": form, "title": "New Vehicle"})


@login_required
def vehicle_update(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to edit vehicles.")
        return redirect("operations:vehicle_list")

    if not user_can_access_depot(request.user, vehicle.depot):
        messages.error(request, "You do not have access to that vehicle.")
        return redirect("operations:vehicle_list")

    if request.method == "POST":
        form = VehicleForm(request.POST, instance=vehicle, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Vehicle updated.")
            return redirect("operations:vehicle_list")
    else:
        form = VehicleForm(instance=vehicle, user=request.user)

    return render(request, "operations/vehicle_form.html", {"form": form, "title": "Edit Vehicle"})


@login_required
def vehicle_delete(request, pk):
    """
    Hard-deletes a vehicle if nothing protects it. Vehicle.loads is
    on_delete=PROTECT — real load history can never be deleted out
    from under it, reassignment or not. VehicleSalesman.vehicle is
    also PROTECT but nullable, and reassigning every salesman off
    this vehicle first genuinely clears that blocker — so that case
    gets a proper reassignment flow instead of just a dead end.
    """

    vehicle = get_object_or_404(Vehicle, pk=pk)

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to delete vehicles.")
        return redirect("operations:vehicle_list")

    if not user_can_access_depot(request.user, vehicle.depot):
        messages.error(request, "You do not have access to that vehicle.")
        return redirect("operations:vehicle_list")

    if request.method != "POST":
        return redirect("operations:vehicle_list")

    try:
        vehicle.delete()
        messages.success(request, "Vehicle deleted.")
        return redirect("operations:vehicle_list")
    except ProtectedError:
        if vehicle.loads.exists():
            messages.error(
                request,
                f"'{vehicle.registration_number}' can't be deleted — it has vehicle "
                "loads recorded against it, and that history can't be removed even "
                "after reassigning any salesmen. Turn off \"Is active\" instead to "
                "retire it from use."
            )
            return redirect("operations:vehicle_list")

        if VehicleSalesman.objects.filter(vehicle=vehicle).exists():
            return redirect("operations:vehicle_reassign_and_delete", pk=pk)

        messages.error(request, f"'{vehicle.registration_number}' can't be deleted right now.")
        return redirect("operations:vehicle_list")


@login_required
def vehicle_reassign_and_delete(request, pk):
    """
    Reached when deleting a vehicle failed only because it's still
    assigned to one or more salesmen. Pick a replacement (existing or
    brand new) for each of them, and this reassigns everyone, then
    deletes the original vehicle in one step.
    """

    vehicle = get_object_or_404(Vehicle, pk=pk)

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to delete vehicles.")
        return redirect("operations:vehicle_list")

    if not user_can_access_depot(request.user, vehicle.depot):
        messages.error(request, "You do not have access to that vehicle.")
        return redirect("operations:vehicle_list")

    if vehicle.loads.exists():
        messages.error(
            request,
            f"'{vehicle.registration_number}' has vehicle loads recorded against "
            "it and can't be deleted, even after reassigning salesmen."
        )
        return redirect("operations:vehicle_list")

    assigned_salesmen = VehicleSalesman.objects.filter(vehicle=vehicle)

    if not assigned_salesmen.exists():
        # Nothing left to reassign (e.g. someone else already moved
        # them) — the plain delete should just work now.
        return redirect("operations:vehicle_delete", pk=pk)

    if request.method == "POST":
        form = VehicleReassignForm(request.POST, vehicle=vehicle, user=request.user)

        if form.is_valid():
            assigned_count = assigned_salesmen.count()

            with transaction.atomic():
                for assignment in form.get_assignments():
                    salesman = assignment["salesman"]

                    if assignment["vehicle"] is not None:
                        replacement = assignment["vehicle"]
                    else:
                        replacement = Vehicle.objects.create(**assignment["new_vehicle_data"])

                    salesman.vehicle = replacement
                    salesman.save(update_fields=["vehicle", "updated_at"])

                vehicle.delete()

            messages.success(
                request,
                f"Reassigned {assigned_count} salesman/salesmen and deleted "
                f"'{vehicle.registration_number}'."
            )
            return redirect("operations:vehicle_list")
    else:
        form = VehicleReassignForm(vehicle=vehicle, user=request.user)

    return render(request, "operations/vehicle_reassign_and_delete.html", {
        "vehicle": vehicle,
        "form": form,
    })


# =========================
# SALESMEN
# =========================
@login_required
def salesman_list(request):
    salesmen = VehicleSalesman.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot", "vehicle").order_by("name")
    return render(request, "operations/salesman_list.html", {"salesmen": salesmen, "can_manage": _can_manage_operations(request.user)})


@login_required
def salesman_create(request):
    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to create salesmen.")
        return redirect("operations:salesman_list")

    if request.method == "POST":
        form = VehicleSalesmanForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Salesman created.")
            return redirect("operations:salesman_list")
    else:
        form = VehicleSalesmanForm(user=request.user)

    return render(request, "operations/salesman_form.html", {"form": form, "title": "New Salesman"})


@login_required
def salesman_update(request, pk):
    salesman = get_object_or_404(VehicleSalesman, pk=pk)

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to edit salesmen.")
        return redirect("operations:salesman_list")

    if not user_can_access_depot(request.user, salesman.depot):
        messages.error(request, "You do not have access to that salesman.")
        return redirect("operations:salesman_list")

    if request.method == "POST":
        form = VehicleSalesmanForm(request.POST, instance=salesman, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Salesman updated.")
            return redirect("operations:salesman_list")
    else:
        form = VehicleSalesmanForm(instance=salesman, user=request.user)

    return render(request, "operations/salesman_form.html", {"form": form, "title": "Edit Salesman"})


# =========================
# VEHICLE LOADS
# =========================
@login_required
def load_list(request):
    loads = VehicleLoad.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot", "vehicle", "salesman").order_by("-load_date")
    return render(request, "operations/load_list.html", {"loads": loads, "can_manage": _can_manage_operations(request.user)})


@login_required
def load_detail(request, pk):
    load = get_object_or_404(
        VehicleLoad.objects.select_related("depot", "vehicle", "salesman"), pk=pk
    )

    if not user_can_access_depot(request.user, load.depot):
        messages.error(request, "You do not have access to that vehicle load.")
        return redirect("operations:load_list")

    items = load.items.select_related("product").all()
    returns = load.returns.all()

    return render(request, "operations/load_detail.html", {
        "load": load,
        "items": items,
        "returns": returns,
        "reconciliation": load.reconciliation_status() if not load.is_closed else None,
        "is_overdue": (not load.is_closed) and load.load_date < timezone.now().date(),
        "can_manage": _can_manage_operations(request.user),
    })


@login_required
def load_create(request):
    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to create vehicle loads.")
        return redirect("operations:load_list")

    if request.method == "POST":
        form = VehicleLoadForm(request.POST, user=request.user)

        if form.is_valid():
            load = form.save(commit=False)
            formset = VehicleLoadItemFormSet(request.POST, instance=load)

            if formset.is_valid():
                try:
                    with transaction.atomic():
                        load.save()
                        formset.instance = load
                        formset.save()
                except Exception as exc:
                    messages.error(request, f"Could not save load: {exc}")
                else:
                    messages.success(request, f"Vehicle load {load.load_number} recorded.")
                    return redirect("operations:load_detail", pk=load.pk)
        else:
            formset = VehicleLoadItemFormSet(request.POST, instance=VehicleLoad())
    else:
        form = VehicleLoadForm(user=request.user)
        formset = VehicleLoadItemFormSet(instance=VehicleLoad())

    return render(request, "operations/load_form.html", {
        "form": form, "formset": formset, "title": "New Vehicle Load",
    })

@login_required
def load_close(request, pk):
    """
    Records the day's result and closes the load in one step: for
    every product still unaccounted for, how much was sold and how
    much was returned. See forms.LoadCloseForm for the validation
    (sold + returned must exactly account for what's remaining).

    This is now the only way sales get recorded against a load —
    there is deliberately no per-customer sale entry point here,
    since day-to-day this business doesn't track sales by customer.
    sales.views.sale_create still exists for anyone who wants to
    attribute a sale to a specific Customer by going there directly;
    it's just no longer linked from the load page.
    """

    load = get_object_or_404(VehicleLoad, pk=pk)

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to close vehicle loads.")
        return redirect("operations:load_detail", pk=pk)

    if not user_can_access_depot(request.user, load.depot):
        messages.error(request, "You do not have access to that vehicle load.")
        return redirect("operations:load_list")

    if load.is_closed:
        messages.error(request, "This vehicle load is already closed.")
        return redirect("operations:load_detail", pk=pk)

    if request.method == "POST":
        form = LoadCloseForm(request.POST, load=load)

        if form.is_valid():
            results = form.get_results()
            today = timezone.now().date()

            try:
                with transaction.atomic():
                    sold_rows = [row for row in results if row["sold"] > 0]
                    returned_rows = [row for row in results if row["returned"] > 0]

                    if sold_rows:
                        sale = Sale(vehicle_load=load, sale_date=today)
                        sale.save()

                        for row in sold_rows:
                            SaleItem.objects.create(
                                sale=sale, product=row["product"], quantity=row["sold"],
                            )

                        sale.finalize()

                    if returned_rows:
                        vehicle_return = VehicleReturn(vehicle_load=load, return_date=today)
                        vehicle_return.save()

                        for row in returned_rows:
                            VehicleReturnItem.objects.create(
                                vehicle_return=vehicle_return,
                                product=row["product"],
                                quantity=row["returned"],
                                condition=row["condition"],
                            )

                        vehicle_return.confirm_return()

                    load.close_load()

                messages.success(request, "Sales and returns recorded — vehicle load closed.")
                return redirect("operations:load_detail", pk=pk)
            except Exception as exc:
                messages.error(request, str(exc))
    else:
        form = LoadCloseForm(load=load)

    return render(request, "operations/load_close.html", {"load": load, "form": form})


# =========================
# VEHICLE RETURNS
# =========================
@login_required
def return_create(request, load_pk):
    load = get_object_or_404(VehicleLoad, pk=load_pk)

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to record vehicle returns.")
        return redirect("operations:load_detail", pk=load_pk)

    if not user_can_access_depot(request.user, load.depot):
        messages.error(request, "You do not have access to that vehicle load.")
        return redirect("operations:load_list")

    if request.method == "POST":
        form = VehicleReturnForm(request.POST, vehicle_load=load)

        if form.is_valid():
            vehicle_return = form.save(commit=False)
            formset = VehicleReturnItemFormSet(request.POST, instance=vehicle_return)

            if formset.is_valid():
                try:
                    with transaction.atomic():
                        vehicle_return.save()
                        formset.instance = vehicle_return
                        formset.save()
                except Exception as exc:
                    messages.error(request, f"Could not save return: {exc}")
                else:
                    messages.success(request, f"Vehicle return {vehicle_return.return_number} recorded.")
                    return redirect("operations:return_detail", pk=vehicle_return.pk)
        else:
            formset = VehicleReturnItemFormSet(request.POST, instance=VehicleReturn())
    else:
        form = VehicleReturnForm(vehicle_load=load)
        formset = VehicleReturnItemFormSet(instance=VehicleReturn())

    return render(request, "operations/return_form.html", {
        "form": form, "formset": formset, "load": load, "title": "New Vehicle Return",
    })

@login_required
def return_detail(request, pk):
    vehicle_return = get_object_or_404(
        VehicleReturn.objects.select_related("vehicle_load", "vehicle_load__depot"), pk=pk
    )

    if not user_can_access_depot(request.user, vehicle_return.vehicle_load.depot):
        messages.error(request, "You do not have access to that vehicle return.")
        return redirect("operations:load_list")

    items = vehicle_return.items.select_related("product").all()

    return render(request, "operations/return_detail.html", {
        "vehicle_return": vehicle_return,
        "items": items,
        "can_manage": _can_manage_operations(request.user),
    })


@login_required
def return_confirm(request, pk):
    vehicle_return = get_object_or_404(
        VehicleReturn.objects.select_related("vehicle_load", "vehicle_load__depot"), pk=pk
    )

    if not _can_manage_operations(request.user):
        messages.error(request, "You do not have permission to confirm vehicle returns.")
        return redirect("operations:return_detail", pk=pk)

    if not user_can_access_depot(request.user, vehicle_return.vehicle_load.depot):
        messages.error(request, "You do not have access to that vehicle return.")
        return redirect("operations:load_list")

    if request.method == "POST":
        try:
            vehicle_return.confirm_return()
            messages.success(request, "Vehicle return confirmed.")
        except Exception as exc:
            messages.error(request, str(exc))

    return redirect("operations:return_detail", pk=pk)


# =========================
# MY LOADS (SALESMAN SELF-SERVICE)
# =========================
@login_required
def my_loads(request):
    """
    A logged-in salesman's own loads and current-month target
    progress. Needs request.user.salesman_profile — the link created
    alongside a VehicleSalesman in VehicleSalesmanForm — so an
    account with no linked salesman record just sees a message
    explaining that, rather than an error.
    """

    salesman = getattr(request.user, "salesman_profile", None)

    if salesman is None:
        return render(request, "operations/my_loads.html", {"salesman": None})

    today = timezone.now().date()

    loads = salesman.vehicle_loads.select_related("depot", "vehicle").order_by("-load_date")
    target_progress = get_salesman_target_progress(salesman, today.year, today.month)

    return render(request, "operations/my_loads.html", {
        "salesman": salesman,
        "loads": loads,
        "target_progress": target_progress,
    })


# =========================
# SALES TARGETS
# =========================
@login_required
def target_list(request):
    targets = SalesTarget.objects.filter(
        salesman__depot__in=get_visible_depots(request.user)
    ).select_related("salesman", "salesman__depot").order_by(
        "-year", "-month", "salesman__name"
    )

    return render(request, "operations/target_list.html", {
        "targets": targets,
        "can_set_targets": _can_set_targets(request.user),
    })


@login_required
def target_create(request):
    if not _can_set_targets(request.user):
        messages.error(request, "You do not have permission to set sales targets.")
        return redirect("operations:target_list")

    if request.method == "POST":
        form = SalesTargetForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Sales target set.")
            return redirect("operations:target_list")
    else:
        form = SalesTargetForm(user=request.user)

    return render(request, "operations/target_form.html", {"form": form, "title": "Set Sales Target"})


@login_required
def target_update(request, pk):
    target = get_object_or_404(SalesTarget.objects.select_related("salesman", "salesman__depot"), pk=pk)

    if not _can_set_targets(request.user):
        messages.error(request, "You do not have permission to edit sales targets.")
        return redirect("operations:target_list")

    if not user_can_access_depot(request.user, target.salesman.depot):
        messages.error(request, "You do not have access to that sales target.")
        return redirect("operations:target_list")

    if request.method == "POST":
        form = SalesTargetForm(request.POST, instance=target, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Sales target updated.")
            return redirect("operations:target_list")
    else:
        form = SalesTargetForm(instance=target, user=request.user)

    return render(request, "operations/target_form.html", {"form": form, "title": "Edit Sales Target"})