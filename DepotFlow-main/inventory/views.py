from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404

from depots.models import Depot
from operations.models import VehicleSalesman
from core.scoping import get_visible_depots, user_can_access_depot
from .models import Product, Supplier, StockReceipt, Promotion
from .scoping import visible_promotions, can_edit_promotion
from .forms import (
    ProductForm, PriceChangeForm, SupplierForm,
    StockReceiptForm, StockReceiptItemFormSet, PromotionForm,
)
from .services import (
    get_current_selling_price, get_current_cost_reference, record_price_change,
    get_stock_balance,
)


def _can_manage_inventory(user):
    """
    Staff, SUPER_ADMIN, DEPOT_MANAGER, or DEPOT_OFFICER can manage
    day-to-day inventory (products, suppliers, receiving stock).
    """

    if getattr(user, "role", "") == "DEPOT_OWNER":
        return False

    return user.is_staff or getattr(user, "role", "") in (
        "SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER",
    )


def _can_manage_pricing(user):
    """
    Pricing and promotions are more sensitive than day-to-day
    receiving, so this is deliberately stricter than
    _can_manage_inventory().
    """

    if getattr(user, "role", "") == "DEPOT_OWNER":
        return False

    return user.is_staff or getattr(user, "role", "") in ("SUPER_ADMIN", "DEPOT_MANAGER")


# =========================
# STOCK LOOKUP (AJAX)
# =========================
@login_required
def stock_balance_lookup(request):
    """
    Small JSON endpoint backing the "available stock" hint shown
    next to the product field when adding vehicle load items — not
    a page of its own, just data for that one bit of UI.

    Accepts either ?depot=<id> or ?salesman=<id> — the load form no
    longer has its own depot field (it's derived from the picked
    salesman), so the hint resolves the depot from the salesman
    instead when that's what's available.
    """

    product_id = request.GET.get("product")
    depot_id = request.GET.get("depot")
    salesman_id = request.GET.get("salesman")

    if not product_id or not (depot_id or salesman_id):
        return JsonResponse(
            {"error": "product and (depot or salesman) query params are required"}, status=400
        )

    product = get_object_or_404(Product, pk=product_id)

    if salesman_id:
        salesman = get_object_or_404(VehicleSalesman, pk=salesman_id)
        depot = salesman.depot
    else:
        depot = get_object_or_404(Depot, pk=depot_id)

    if not user_can_access_depot(request.user, depot):
        return JsonResponse({"error": "You do not have access to that depot."}, status=403)

    balance = get_stock_balance(depot, product)

    return JsonResponse({"product_id": product.id, "depot_id": depot.id, "stock_balance": balance})


# =========================
# PRODUCTS
# =========================
@login_required
def product_list(request):
    products = Product.objects.all().order_by("name")
    return render(request, "inventory/product_list.html", {"products": products, "can_manage": _can_manage_inventory(request.user)})


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)

    context = {
        "product": product,
        "current_selling_price": get_current_selling_price(product),
        "current_cost_reference": get_current_cost_reference(product),
        "price_history": product.price_history.all()[:20],
        "can_manage_pricing": _can_manage_pricing(request.user),
    }

    return render(request, "inventory/product_detail.html", context)


@login_required
def product_create(request):
    if not _can_manage_inventory(request.user):
        messages.error(request, "You do not have permission to create products.")
        return redirect("inventory:product_list")

    if request.method == "POST":
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Product created.")
            return redirect("inventory:product_list")
    else:
        form = ProductForm()

    return render(request, "inventory/product_form.html", {"form": form, "title": "New Product"})


@login_required
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if not _can_manage_inventory(request.user):
        messages.error(request, "You do not have permission to edit products.")
        return redirect("inventory:product_detail", pk=pk)

    if request.method == "POST":
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "Product updated.")
            return redirect("inventory:product_detail", pk=pk)
    else:
        form = ProductForm(instance=product)

    return render(request, "inventory/product_form.html", {"form": form, "title": "Edit Product"})


@login_required
def product_delete(request, pk):
    """
    Hard-deletes a product if nothing actually references it yet.
    Every real transactional link to Product (inventory transactions,
    sale items, vehicle load items, vehicle return items, stock
    receipt items) is on_delete=PROTECT, so this simply fails with a
    clear explanation for any product that's ever actually moved —
    at that point it's business history, not a mistake to erase, and
    the existing is_active toggle on the edit form is the right way
    to retire it instead.
    """

    product = get_object_or_404(Product, pk=pk)

    if not _can_manage_inventory(request.user):
        messages.error(request, "You do not have permission to delete products.")
        return redirect("inventory:product_detail", pk=pk)

    if request.method == "POST":
        try:
            product.delete()
            messages.success(request, "Product deleted.")
            return redirect("inventory:product_list")
        except ProtectedError:
            messages.error(
                request,
                f"'{product.name}' can't be deleted — it already has stock "
                "receipts, loads, sales, or returns recorded against it, and "
                "deleting it would break that history. Edit it and turn off "
                "\"Is active\" instead to retire it from use."
            )

    return redirect("inventory:product_detail", pk=pk)


@login_required
def change_price(request, pk):
    product = get_object_or_404(Product, pk=pk)

    if not _can_manage_pricing(request.user):
        messages.error(request, "You do not have permission to change pricing.")
        return redirect("inventory:product_detail", pk=pk)

    if request.method == "POST":
        form = PriceChangeForm(request.POST)
        if form.is_valid():
            record_price_change(
                product,
                selling_price=form.cleaned_data["selling_price"],
                cost_price=form.cleaned_data["cost_price"],
                user=request.user,
                reason=form.cleaned_data["reason"],
            )
            messages.success(request, "Price updated.")
            return redirect("inventory:product_detail", pk=pk)
    else:
        form = PriceChangeForm(initial={
            "selling_price": get_current_selling_price(product),
            "cost_price": get_current_cost_reference(product),
        })

    return render(request, "inventory/price_change_form.html", {"form": form, "product": product})


# =========================
# SUPPLIERS
# =========================
@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all().order_by("name")
    return render(request, "inventory/supplier_list.html", {"suppliers": suppliers, "can_manage": _can_manage_inventory(request.user)})


@login_required
def supplier_create(request):
    if not _can_manage_inventory(request.user):
        messages.error(request, "You do not have permission to create suppliers.")
        return redirect("inventory:supplier_list")

    if request.method == "POST":
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier created.")
            return redirect("inventory:supplier_list")
    else:
        form = SupplierForm()

    return render(request, "inventory/supplier_form.html", {"form": form, "title": "New Supplier"})


@login_required
def supplier_update(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)

    if not _can_manage_inventory(request.user):
        messages.error(request, "You do not have permission to edit suppliers.")
        return redirect("inventory:supplier_list")

    if request.method == "POST":
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier updated.")
            return redirect("inventory:supplier_list")
    else:
        form = SupplierForm(instance=supplier)

    return render(request, "inventory/supplier_form.html", {"form": form, "title": "Edit Supplier"})


# =========================
# STOCK RECEIPTS
# =========================
@login_required
def stock_receipt_list(request):
    receipts = (
        StockReceipt.objects.filter(depot__in=get_visible_depots(request.user))
        .select_related("supplier", "depot").order_by("-receipt_date")
    )
    return render(request, "inventory/stock_receipt_list.html", {"receipts": receipts, "can_manage": _can_manage_inventory(request.user)})


@login_required
def stock_receipt_detail(request, pk):
    receipt = get_object_or_404(
        StockReceipt.objects.select_related("supplier", "depot"), pk=pk
    )

    if not user_can_access_depot(request.user, receipt.depot):
        messages.error(request, "You do not have access to that stock receipt.")
        return redirect("inventory:stock_receipt_list")

    items = receipt.items.select_related("product").all()
    return render(request, "inventory/stock_receipt_detail.html", {"receipt": receipt, "items": items})


@login_required
def stock_receipt_create(request):
    if not _can_manage_inventory(request.user):
        messages.error(request, "You do not have permission to record stock receipts.")
        return redirect("inventory:stock_receipt_list")

    if request.method == "POST":
        form = StockReceiptForm(request.POST)
        formset = StockReceiptItemFormSet(request.POST, instance=StockReceipt())

        if form.is_valid() and formset.is_valid():
            receipt = form.save()
            formset.instance = receipt
            formset.save()
            messages.success(request, f"Stock receipt {receipt.invoice_number} recorded.")
            return redirect("inventory:stock_receipt_detail", pk=receipt.pk)
    else:
        form = StockReceiptForm()
        formset = StockReceiptItemFormSet(instance=StockReceipt())

    return render(
        request,
        "inventory/stock_receipt_form.html",
        {"form": form, "formset": formset, "title": "New Stock Receipt"},
    )


# =========================
# PROMOTIONS
# =========================
@login_required
def promotion_list(request):
    promotions = visible_promotions(request.user).order_by("-start_date")
    return render(request, "inventory/promotion_list.html", {"promotions": promotions, "can_manage": _can_manage_pricing(request.user)})


@login_required
def promotion_create(request):
    if not _can_manage_pricing(request.user):
        messages.error(request, "You do not have permission to create promotions.")
        return redirect("inventory:promotion_list")

    if request.method == "POST":
        form = PromotionForm(request.POST, user=request.user)
        if form.is_valid():
            promotion = form.save(commit=False)
            promotion.created_by = request.user
            promotion.save()
            form.save_m2m()
            messages.success(request, "Promotion created.")
            return redirect("inventory:promotion_list")
    else:
        form = PromotionForm(user=request.user)

    return render(request, "inventory/promotion_form.html", {"form": form, "title": "New Promotion"})


@login_required
def promotion_update(request, pk):
    promotion = get_object_or_404(Promotion, pk=pk)

    if not _can_manage_pricing(request.user):
        messages.error(request, "You do not have permission to edit promotions.")
        return redirect("inventory:promotion_list")

    if not can_edit_promotion(request.user, promotion):
        messages.error(request, "You do not have access to that promotion.")
        return redirect("inventory:promotion_list")

    if request.method == "POST":
        form = PromotionForm(request.POST, instance=promotion, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Promotion updated.")
            return redirect("inventory:promotion_list")
    else:
        form = PromotionForm(instance=promotion, user=request.user)

    return render(request, "inventory/promotion_form.html", {"form": form, "title": "Edit Promotion"})