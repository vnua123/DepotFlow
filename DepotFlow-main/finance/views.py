import datetime as dt
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from core.scoping import get_visible_depots, user_can_access_depot, is_unrestricted
from depots.models import Depot
from . import expense_import as importer
from .models import (
    BusinessLedger, Expense, ExpenseCategory, ExpenseImportBatch,
    SupplierPayment, SupplierRebate,
)
from .forms import (
    ExpenseForm, ExpenseImportForm, SupplierPaymentForm, SupplierRebateForm, ReversalForm,
)


def _can_record_expenses(user):
    """
    Staff, SUPER_ADMIN, DEPOT_OWNER, DEPOT_MANAGER, or DEPOT_OFFICER can
    record expenses. Depot Owners remain scoped to their own depot.
    """

    return user.is_staff or getattr(user, "role", "") in (
        "SUPER_ADMIN", "DEPOT_OWNER", "DEPOT_MANAGER", "DEPOT_OFFICER",
    )


def _can_approve_finance(user):
    """
    Expense approval/reversal and supplier-payment management are
    available to Super Admin, Depot Owner, Distribution Manager and
    Finance Officer. Depot scoping still limits Depot Owner to their
    assigned depot. Supplier rebates use the separate rule below.
    """
    return user.is_staff or getattr(user, "role", "") in (
        "SUPER_ADMIN", "DEPOT_OWNER", "DEPOT_MANAGER", "FINANCE_OFFICER",
    )


def _can_manage_rebates(user):
    """Supplier rebates remain read-only for Depot Owners, including staff-flagged accounts."""
    if getattr(user, "role", "") == "DEPOT_OWNER":
        return False
    return user.is_staff or getattr(user, "role", "") in (
        "SUPER_ADMIN", "DEPOT_MANAGER", "FINANCE_OFFICER",
    )


# =========================
# EXPENSES
# =========================
@login_required
def expense_list(request):
    expenses = Expense.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot", "category").order_by("-expense_date", "-id")
    page = Paginator(expenses, 50).get_page(request.GET.get("page"))
    return render(request, "finance/expense_list.html", {
        "expenses": page,
        "can_approve": _can_approve_finance(request.user),
        "can_record": _can_record_expenses(request.user),
    })


@login_required
def expense_create(request):
    if not _can_record_expenses(request.user):
        messages.error(request, "You do not have permission to record expenses.")
        return redirect("finance:expense_list")

    if request.method == "POST":
        form = ExpenseForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense recorded.")
            return redirect("finance:expense_list")
    else:
        form = ExpenseForm(user=request.user)

    return render(request, "finance/expense_form.html", {"form": form, "title": "New Expense"})


@login_required
def expense_approve(request, pk):
    expense = get_object_or_404(Expense, pk=pk)

    if not _can_approve_finance(request.user):
        messages.error(request, "You do not have permission to approve expenses.")
        return redirect("finance:expense_list")

    if not user_can_access_depot(request.user, expense.depot):
        messages.error(request, "You do not have access to that expense.")
        return redirect("finance:expense_list")

    if request.method == "POST":
        expense.approved = True
        expense.save(update_fields=["approved", "updated_at"])
        messages.success(request, "Expense approved.")

    return redirect("finance:expense_list")


@login_required
def expense_reverse(request, pk):
    expense = get_object_or_404(Expense, pk=pk)

    if not _can_approve_finance(request.user):
        messages.error(request, "You do not have permission to reverse expenses.")
        return redirect("finance:expense_list")

    if not user_can_access_depot(request.user, expense.depot):
        messages.error(request, "You do not have access to that expense.")
        return redirect("finance:expense_list")

    if request.method == "POST":
        form = ReversalForm(request.POST)
        if form.is_valid():
            try:
                expense.reverse(user=request.user, reason=form.cleaned_data["reason"])
                messages.success(request, "Expense reversed.")
                return redirect("finance:expense_list")
            except Exception as exc:
                messages.error(request, str(exc))
    else:
        form = ReversalForm()

    return render(request, "finance/reversal_form.html", {
        "form": form,
        "object_repr": f"{expense.reference_number} — {expense.category.name} — \u20a6{expense.amount}",
        "title": f"Reverse Expense {expense.reference_number}",
    })


# =========================
# EXPENSE IMPORT FROM EXCEL
# =========================
IMPORT_SESSION_KEY = "expense_import"


def _import_depot_or_none(request, state):
    depot = Depot.objects.filter(pk=state["depot_id"]).first()
    if depot is None or not user_can_access_depot(request.user, depot):
        return None
    return depot


@login_required
def expense_import(request):
    """Step 1: choose the depot and the workbook."""
    if not _can_record_expenses(request.user):
        messages.error(request, "You do not have permission to record expenses.")
        return redirect("finance:expense_list")

    can_approve = _can_approve_finance(request.user)

    if request.method == "POST":
        form = ExpenseImportForm(
            request.POST, request.FILES, user=request.user, can_approve=can_approve,
        )
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                parsed = importer.parse_workbook(upload, form.cleaned_data["sheet_name"])
            except importer.SheetImportError as exc:
                form.add_error("file", str(exc))
            else:
                request.session[IMPORT_SESSION_KEY] = {
                    "depot_id": form.cleaned_data["depot"].pk,
                    "file_name": upload.name,
                    "payment_method": form.cleaned_data["payment_method"],
                    "mark_approved": bool(can_approve and form.cleaned_data.get("mark_approved")),
                    **parsed,
                }
                return redirect("finance:expense_import_preview")
    else:
        form = ExpenseImportForm(user=request.user, can_approve=can_approve)

    return render(request, "finance/expense_import.html", {"form": form})


def _mapping_from_request(request, used_headers, suggestions):
    """Read the category dropdowns; fall back to the suggestion for anything invalid."""
    mapping = {}
    for index, header in enumerate(used_headers):
        chosen = request.POST.get(f"map_{index}") if request.method == "POST" else None
        if chosen == "new":
            mapping[header] = None
        elif chosen and chosen.isdigit() and ExpenseCategory.objects.filter(pk=int(chosen)).exists():
            mapping[header] = int(chosen)
        else:
            mapping[header] = suggestions[header]["category_id"]
    return mapping


@login_required
def expense_import_preview(request):
    """Step 2: show exactly what would happen; save only on Confirm."""
    if not _can_record_expenses(request.user):
        messages.error(request, "You do not have permission to record expenses.")
        return redirect("finance:expense_list")

    state = request.session.get(IMPORT_SESSION_KEY)
    if not state:
        messages.error(request, "Upload a workbook first.")
        return redirect("finance:expense_import")

    depot = _import_depot_or_none(request, state)
    if depot is None:
        request.session.pop(IMPORT_SESSION_KEY, None)
        messages.error(request, "You do not have access to that depot.")
        return redirect("finance:expense_import")

    rows = state["rows"]
    used_headers = [h for h in state["headers"] if any(r["header"] == h for r in rows)]
    suggestions = importer.suggest_category_map(used_headers)
    mapping = _mapping_from_request(request, used_headers, suggestions)
    allow_overlap = request.method == "POST" and "allow_overlap" in request.POST

    if request.method == "POST" and request.POST.get("action") == "confirm":
        classified = importer.classify_rows(depot, rows, mapping, allow_overlap=allow_overlap)
        if state["issues"]:
            messages.error(request, "Fix the problems listed below in the sheet, then upload it again.")
        elif not classified["importable"]:
            messages.error(request, "There is nothing new to import.")
        else:
            batch, _ = importer.commit_import(
                user=request.user,
                depot=depot,
                file_name=state["file_name"],
                sheet_name=state["sheet"],
                rows=rows,
                headers=used_headers,
                mapping=mapping,
                payment_method=state["payment_method"],
                auto_approve=state["mark_approved"] and _can_approve_finance(request.user),
                allow_overlap=allow_overlap,
            )
            request.session.pop(IMPORT_SESSION_KEY, None)
            messages.success(
                request,
                f"Imported {batch.expenses_created} expenses totalling \u20a6{batch.total_amount:,.2f}"
                + (f"; {batch.rows_skipped} sheet entries were skipped." if batch.rows_skipped else "."),
            )
            return redirect("finance:expense_import_batch_detail", pk=batch.pk)
    else:
        classified = importer.classify_rows(depot, rows, mapping, allow_overlap=allow_overlap)

    header_stats = {}
    for row in rows:
        stat = header_stats.setdefault(row["header"], {"count": 0, "amount": 0})
        stat["count"] += 1
        stat["amount"] += float(row["amount"])

    categories = list(ExpenseCategory.objects.all())
    mapping_rows = []
    for index, header in enumerate(used_headers):
        mapping_rows.append({
            "index": index,
            "header": header,
            "count": header_stats[header]["count"],
            "amount": header_stats[header]["amount"],
            "selected": mapping[header],
            "match": suggestions[header]["match"],
            "suggested_name": suggestions[header]["category_name"],
        })

    return render(request, "finance/expense_import_preview.html", {
        "state": state,
        "depot": depot,
        "classified": classified,
        "mapping_rows": mapping_rows,
        "categories": categories,
        "allow_overlap": allow_overlap,
        "skipped_total": (
            len(classified[importer.ALREADY_IMPORTED]) + len(classified[importer.ALREADY_IN_APP])
        ),
        "conflicts": classified[importer.CHANGED] + classified[importer.OVERLAP],
        "can_confirm": not state["issues"] and bool(classified["importable"]),
    })


@login_required
def expense_import_cancel(request):
    request.session.pop(IMPORT_SESSION_KEY, None)
    return redirect("finance:expense_list")


@login_required
def expense_import_template(request):
    """A blank workbook in the layout the importer reads."""
    import openpyxl
    from openpyxl.utils import get_column_letter

    if not _can_record_expenses(request.user):
        messages.error(request, "You do not have permission to record expenses.")
        return redirect("finance:expense_list")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expense"
    ws["A1"] = "Expenses"
    ws["A2"] = "Date"
    names = list(ExpenseCategory.objects.order_by("name").values_list("name", flat=True))
    for col, name in enumerate(names, start=2):
        ws.cell(2, col, name)
        ws.column_dimensions[get_column_letter(col)].width = max(14, len(name) + 2)
    ws.column_dimensions["A"].width = 14

    year = timezone.localdate().year
    day = dt.date(year, 1, 1)
    row = 3
    while day.year == year:
        ws.cell(row, 1, day).number_format = "dd-mmm-yyyy"
        day += dt.timedelta(days=1)
        row += 1
    ws.freeze_panes = "B3"

    buffer = BytesIO()
    wb.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="expense_import_template.xlsx"'
    return response


@login_required
def expense_import_batch_list(request):
    batches = ExpenseImportBatch.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot", "uploaded_by")
    return render(request, "finance/expense_import_batch_list.html", {"batches": batches})


def _visible_batch_or_none(request, pk):
    batch = get_object_or_404(ExpenseImportBatch.objects.select_related("depot", "uploaded_by"), pk=pk)
    if not user_can_access_depot(request.user, batch.depot):
        return None
    return batch


@login_required
def expense_import_batch_detail(request, pk):
    batch = _visible_batch_or_none(request, pk)
    if batch is None:
        messages.error(request, "You do not have access to that import.")
        return redirect("finance:expense_list")

    expenses = batch.expenses.all()
    live = expenses.filter(is_reversed=False)
    by_month = (
        live.annotate(month=TruncMonth("expense_date"))
        .values("month").annotate(count=Count("id"), total=Sum("amount")).order_by("month")
    )
    return render(request, "finance/expense_import_batch_detail.html", {
        "batch": batch,
        "live_count": live.count(),
        "pending_count": live.filter(approved=False).count(),
        "reversed_count": expenses.filter(is_reversed=True).count(),
        "live_total": live.aggregate(t=Sum("amount"))["t"] or 0,
        "by_month": by_month,
        "can_approve": _can_approve_finance(request.user),
    })


@login_required
def expense_import_batch_approve(request, pk):
    batch = _visible_batch_or_none(request, pk)
    if batch is None or not _can_approve_finance(request.user):
        messages.error(request, "You do not have permission to approve these expenses.")
        return redirect("finance:expense_list")

    if request.method == "POST":
        count = importer.approve_batch(batch)
        messages.success(request, f"Approved {count} expenses.")
    return redirect("finance:expense_import_batch_detail", pk=batch.pk)


@login_required
def expense_import_batch_reverse(request, pk):
    batch = _visible_batch_or_none(request, pk)
    if batch is None or not _can_approve_finance(request.user):
        messages.error(request, "You do not have permission to reverse these expenses.")
        return redirect("finance:expense_list")

    live = batch.expenses.filter(is_reversed=False)
    if request.method == "POST":
        form = ReversalForm(request.POST)
        if form.is_valid():
            try:
                count = importer.reverse_batch(batch, request.user, form.cleaned_data["reason"])
                messages.success(request, f"Reversed {count} expenses from this import.")
                return redirect("finance:expense_import_batch_detail", pk=batch.pk)
            except Exception as exc:
                messages.error(request, str(exc))
    else:
        form = ReversalForm()

    return render(request, "finance/reversal_form.html", {
        "form": form,
        "object_repr": f"{batch.file_name} \u2014 {live.count()} expenses, \u20a6{live.aggregate(t=Sum('amount'))['t'] or 0:,.2f}",
        "title": "Reverse whole import",
    })


# =========================
# SUPPLIER PAYMENTS
# =========================
@login_required
def supplier_payment_list(request):
    payments = SupplierPayment.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot", "supplier").order_by("-payment_date")
    return render(request, "finance/supplier_payment_list.html", {
        "payments": payments,
        "can_approve": _can_approve_finance(request.user),
        "can_record": _can_approve_finance(request.user),
    })


@login_required
def supplier_payment_create(request):
    if not _can_approve_finance(request.user):
        messages.error(request, "You do not have permission to record supplier payments.")
        return redirect("finance:supplier_payment_list")

    if request.method == "POST":
        form = SupplierPaymentForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier payment recorded.")
            return redirect("finance:supplier_payment_list")
    else:
        form = SupplierPaymentForm(user=request.user)

    return render(request, "finance/supplier_payment_form.html", {"form": form, "title": "New Supplier Payment"})


@login_required
def supplier_payment_reverse(request, pk):
    payment = get_object_or_404(SupplierPayment, pk=pk)

    if not _can_approve_finance(request.user):
        messages.error(request, "You do not have permission to reverse supplier payments.")
        return redirect("finance:supplier_payment_list")

    if not user_can_access_depot(request.user, payment.depot):
        messages.error(request, "You do not have access to that supplier payment.")
        return redirect("finance:supplier_payment_list")

    if request.method == "POST":
        form = ReversalForm(request.POST)
        if form.is_valid():
            try:
                payment.reverse(user=request.user, reason=form.cleaned_data["reason"])
                messages.success(request, "Supplier payment reversed.")
                return redirect("finance:supplier_payment_list")
            except Exception as exc:
                messages.error(request, str(exc))
    else:
        form = ReversalForm()

    return render(request, "finance/reversal_form.html", {
        "form": form,
        "object_repr": f"{payment.reference_number} — {payment.supplier.name} — \u20a6{payment.amount}",
        "title": f"Reverse Payment {payment.reference_number}",
    })


# =========================
# SUPPLIER REBATES
# =========================
@login_required
def supplier_rebate_list(request):
    rebates = SupplierRebate.objects.filter(
        depot__in=get_visible_depots(request.user)
    ).select_related("depot", "supplier").order_by("-rebate_date")
    return render(request, "finance/supplier_rebate_list.html", {
        "rebates": rebates,
        "can_approve": _can_manage_rebates(request.user),
        "can_record": _can_manage_rebates(request.user),
    })


@login_required
def supplier_rebate_create(request):
    if not _can_manage_rebates(request.user):
        messages.error(request, "You do not have permission to record supplier rebates.")
        return redirect("finance:supplier_rebate_list")

    if request.method == "POST":
        form = SupplierRebateForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier rebate recorded.")
            return redirect("finance:supplier_rebate_list")
    else:
        form = SupplierRebateForm(user=request.user)

    return render(request, "finance/supplier_rebate_form.html", {"form": form, "title": "New Supplier Rebate"})


@login_required
def supplier_rebate_reverse(request, pk):
    rebate = get_object_or_404(SupplierRebate, pk=pk)

    if not _can_manage_rebates(request.user):
        messages.error(request, "You do not have permission to reverse supplier rebates.")
        return redirect("finance:supplier_rebate_list")

    if not user_can_access_depot(request.user, rebate.depot):
        messages.error(request, "You do not have access to that supplier rebate.")
        return redirect("finance:supplier_rebate_list")

    if request.method == "POST":
        form = ReversalForm(request.POST)
        if form.is_valid():
            try:
                rebate.reverse(user=request.user, reason=form.cleaned_data["reason"])
                messages.success(request, "Supplier rebate reversed.")
                return redirect("finance:supplier_rebate_list")
            except Exception as exc:
                messages.error(request, str(exc))
    else:
        form = ReversalForm()

    return render(request, "finance/reversal_form.html", {
        "form": form,
        "object_repr": f"{rebate.reference_number} — {rebate.supplier.name} — \u20a6{rebate.amount}",
        "title": f"Reverse Rebate {rebate.reference_number}",
    })


# =========================
# BUSINESS LEDGER (read-only)
# =========================
@login_required
def ledger_list(request):
    """
    Business Ledger, scoped for depot confidentiality — this is a
    deliberate exception to the rest of the app's "reads are open to
    anyone" convention, since ledger entries are real financial
    detail for a specific depot:

    - Super Admin (or staff): every depot, switchable.
    - Territory Manager: every depot in their own territory, switchable.
    - Everyone else (Depot Manager, Depot Officer, Finance Officer,
      Salesman, Viewer): only their own assigned depot — no switcher,
      and a ?depot= query param from anyone outside the two groups
      above is ignored rather than honored, so this can't be bypassed
      by editing the URL. No depot on the account means no ledger to
      show at all, rather than falling back to "all of them".
    """

    user = request.user
    can_switch = is_unrestricted(user) or (user.is_territory_manager and user.territory_id)
    depots = get_visible_depots(user).order_by("name")

    depot_id = request.GET.get("depot")

    if depot_id and can_switch:
        depot = get_object_or_404(depots, pk=depot_id)
    else:
        depot = depots.first()

    ledger_entries = (
        BusinessLedger.objects.filter(depot=depot).order_by("-transaction_date", "-created_at")[:200]
        if depot else []
    )

    return render(request, "finance/ledger_list.html", {
        "depots": depots,
        "depot": depot,
        "can_switch": can_switch,
        "ledger_entries": ledger_entries,
    })