from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404

from operations.models import VehicleLoad
from core.scoping import get_visible_depots, user_can_access_depot
from .models import Customer, Sale
from .forms import CustomerForm, SaleForm, SaleItemFormSet


def _can_manage_sales(user):
    """
    Staff, SUPER_ADMIN, DEPOT_MANAGER, DEPOT_OFFICER, or SALESMAN can
    record sales (salesmen recording their own sales is explicitly
    part of the original spec's permission table).
    """

    if getattr(user, "role", "") == "DEPOT_OWNER":
        return False

    return user.is_staff or getattr(user, "role", "") in (
        "SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER", "SALESMAN",
    )


# =========================
# CUSTOMERS
# =========================
@login_required
def customer_list(request):
    customers = Customer.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot").order_by("name")
    return render(request, "sales/customer_list.html", {"customers": customers, "can_manage": _can_manage_sales(request.user)})


@login_required
def customer_create(request):
    if not _can_manage_sales(request.user):
        messages.error(request, "You do not have permission to create customers.")
        return redirect("sales:customer_list")

    if request.method == "POST":
        form = CustomerForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer created.")
            return redirect("sales:customer_list")
    else:
        form = CustomerForm(user=request.user)

    return render(request, "sales/customer_form.html", {"form": form, "title": "New Customer"})


@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if not _can_manage_sales(request.user):
        messages.error(request, "You do not have permission to edit customers.")
        return redirect("sales:customer_list")

    if not user_can_access_depot(request.user, customer.depot):
        messages.error(request, "You do not have access to that customer.")
        return redirect("sales:customer_list")

    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer updated.")
            return redirect("sales:customer_list")
    else:
        form = CustomerForm(instance=customer, user=request.user)

    return render(request, "sales/customer_form.html", {"form": form, "title": "Edit Customer"})


# =========================
# SALES
# =========================
@login_required
def sale_list(request):
    sales = Sale.objects.filter(
        vehicle_load__depot__in=get_visible_depots(request.user)
    ).select_related("vehicle_load", "salesman", "customer").order_by("-sale_date")
    return render(request, "sales/sale_list.html", {"sales": sales, "can_manage": _can_manage_sales(request.user)})


@login_required
def sale_detail(request, pk):
    sale = get_object_or_404(
        Sale.objects.select_related("vehicle_load", "vehicle_load__depot", "salesman", "customer"), pk=pk
    )

    if not user_can_access_depot(request.user, sale.vehicle_load.depot):
        messages.error(request, "You do not have access to that sale.")
        return redirect("sales:sale_list")

    items = sale.items.select_related("product", "promotion").all()

    return render(request, "sales/sale_detail.html", {
        "sale": sale,
        "items": items,
        "can_manage": _can_manage_sales(request.user),
    })


@login_required
def sale_create(request, load_pk):
    load = get_object_or_404(VehicleLoad, pk=load_pk)

    if not _can_manage_sales(request.user):
        messages.error(request, "You do not have permission to record sales.")
        return redirect("operations:load_detail", pk=load_pk)

    if not user_can_access_depot(request.user, load.depot):
        messages.error(request, "You do not have access to that vehicle load.")
        return redirect("operations:load_list")

    if request.method == "POST":
        form = SaleForm(request.POST, vehicle_load=load)

        if form.is_valid():
            sale = form.save(commit=False)
            formset = SaleItemFormSet(request.POST, instance=sale)

            if formset.is_valid():
                try:
                    with transaction.atomic():
                        sale.save()
                        formset.instance = sale
                        formset.save()
                except Exception as exc:
                    messages.error(request, f"Could not save sale: {exc}")
                else:
                    messages.success(request, f"Sale {sale.sale_number} recorded.")
                    return redirect("sales:sale_detail", pk=sale.pk)
        else:
            formset = SaleItemFormSet(request.POST, instance=Sale())
    else:
        form = SaleForm(vehicle_load=load)
        formset = SaleItemFormSet(instance=Sale())

    return render(request, "sales/sale_form.html", {
        "form": form, "formset": formset, "load": load, "title": "New Sale",
    })


@login_required
def sale_finalize(request, pk):
    sale = get_object_or_404(Sale.objects.select_related("vehicle_load", "vehicle_load__depot"), pk=pk)

    if not _can_manage_sales(request.user):
        messages.error(request, "You do not have permission to finalize sales.")
        return redirect("sales:sale_detail", pk=pk)

    if not user_can_access_depot(request.user, sale.vehicle_load.depot):
        messages.error(request, "You do not have access to that sale.")
        return redirect("sales:sale_list")

    if request.method == "POST":
        try:
            sale.finalize()
            messages.success(request, "Sale finalized.")
        except Exception as exc:
            messages.error(request, str(exc))

    return redirect("sales:sale_detail", pk=pk)