"""
Excel expense import.

The depot's expense workbook is a grid: one row per day, one column per
expense category, the amount in the cell where they meet. The importer
turns every non-empty cell into one Expense ("<category> - daily total").

Three stages, so nothing is saved until the person has seen what will
happen:

    parse_workbook()   read the file -> plain rows + problems (JSON-safe)
    classify_rows()    compare the rows with what is already in the app
    commit_import()    save the new rows through Expense.save(), so every
                       import gets reference numbers and ledger entries
                       exactly like an expense typed into the app

Rows are never edited after posting (Expense locks its financial fields).
If a cell changes in the sheet after it was imported, the importer
reports a conflict instead of rewriting the ledger; the old expense is
reversed in the app and the sheet is imported again.
"""

import datetime as dt
import difflib
import re
from collections import OrderedDict, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl
from django.db import transaction
from django.utils import timezone

from .models import Expense, ExpenseCategory, ExpenseImportBatch

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
HEADER_SEARCH_ROWS = 15
MAX_AMOUNT = Decimal("999999999999.99")  # the most Expense.amount (14 digits) can hold
CENT = Decimal("0.01")

# Row statuses produced by classify_rows()
NEW = "new"
ALREADY_IMPORTED = "already_imported"   # same date+category+amount imported before
ALREADY_IN_APP = "already_in_app"       # same date+category+amount typed into the app
CHANGED = "changed"                     # imported before, but the sheet amount differs
OVERLAP = "overlap"                     # app has a different amount for that day+category


class SheetImportError(ValueError):
    """The file cannot be read as an expense sheet at all."""


def norm(value):
    return re.sub(r"\s+", " ", str(value)).strip()


def name_key(value):
    return norm(value).casefold()


# --------------------------------------------------------------------------
# PARSING
# --------------------------------------------------------------------------
def _pick_sheet(wb, requested):
    names = wb.sheetnames
    if requested:
        for name in names:
            if name_key(name) == name_key(requested):
                return name
        raise SheetImportError(
            f'No sheet named "{requested}". Sheets in this file: {", ".join(names)}.'
        )

    likely = [n for n in names if "expens" in n.casefold()]
    if len(likely) == 1:
        return likely[0]
    if len(likely) > 1:
        raise SheetImportError(
            f'Several sheets look like expense sheets ({", ".join(likely)}). '
            "Type the sheet name to use."
        )
    if len(names) == 1:
        return names[0]
    raise SheetImportError(
        f'Could not tell which sheet holds the expenses ({", ".join(names)}). '
        "Type the sheet name to use."
    )


def _find_header_row(ws):
    for r in range(1, HEADER_SEARCH_ROWS + 1):
        value = ws.cell(r, 1).value
        if isinstance(value, str) and name_key(value) == "date":
            return r
    raise SheetImportError(
        'Could not find the heading row. Cell A of the heading row must say "Date", '
        "followed by one column per expense category."
    )


def _read_headers(ws, header_row):
    headers = OrderedDict()
    seen = {}
    col = 2
    while True:
        value = ws.cell(header_row, col).value
        if value is None or not norm(value):
            break
        text = norm(value)
        key = text.casefold()
        if key in seen:
            raise SheetImportError(
                f'The heading "{text}" appears twice (columns {seen[key]} and '
                f"{openpyxl.utils.get_column_letter(col)}). Category headings must be unique."
            )
        seen[key] = openpyxl.utils.get_column_letter(col)
        headers[col] = text
        col += 1
    if not headers:
        raise SheetImportError("No category headings found to the right of the Date column.")
    return headers


def _to_amount(raw):
    """Return a 2dp Decimal, None for blank/zero, or raise ValueError."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise ValueError("is not a number")
    if isinstance(raw, (int, float, Decimal)):
        amount = Decimal(str(raw))
    elif isinstance(raw, str):
        text = raw.replace(",", "").replace("\u20a6", "").replace("NGN", "").strip()
        if not text:
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise ValueError("is not a number")
    else:
        raise ValueError("is not a number")

    if not amount.is_finite():
        raise ValueError("is not a number")
    if amount == 0:
        return None
    if amount < 0:
        raise ValueError("is negative")
    amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if amount > MAX_AMOUNT:
        raise ValueError("is too large")
    return amount


def parse_workbook(fileobj, sheet_name=""):
    """
    Read an expense workbook. Returns a dict that is safe to keep in the
    session (only strings, numbers, lists and dicts):

        sheet, headers[], rows[{date, header, amount, ref}],
        issues[{ref, message}], notes[], date_from, date_to

    Anything that would make an import silently incomplete (a bad date,
    a text amount, a negative number, a formula with no saved value) is
    reported in `issues`; the caller must not import while issues remain.
    """
    try:
        wb_values = openpyxl.load_workbook(fileobj, data_only=True)
        fileobj.seek(0)
        wb_formulas = openpyxl.load_workbook(fileobj, data_only=False)
    except Exception:
        raise SheetImportError("Could not read that file. Upload an Excel workbook (.xlsx).")

    title = _pick_sheet(wb_values, sheet_name)
    ws = wb_values[title]
    ws_f = wb_formulas[title]

    header_row = _find_header_row(ws)
    headers = _read_headers(ws, header_row)

    issues = []
    notes = []
    combined = OrderedDict()   # (date, header) -> {"amount", "refs"}
    today = timezone.localdate()

    for r in range(header_row + 1, ws.max_row + 1):
        a = ws.cell(r, 1).value
        if isinstance(a, dt.datetime):
            day = a.date()
        elif isinstance(a, dt.date):
            day = a
        else:
            day = None

        label = name_key(a) if isinstance(a, str) else ""
        if day is None and label.startswith(("total", "grand", "sub")):
            continue  # monthly total rows

        for col, header in headers.items():
            cell = ws.cell(r, col)
            ref = cell.coordinate
            raw = cell.value
            formula = ws_f.cell(r, col).value

            if raw is None:
                if isinstance(formula, str) and formula.startswith("="):
                    issues.append({
                        "ref": ref,
                        "message": "Formula has no saved result. Open the file in Excel, "
                                   "save it, and upload it again.",
                    })
                continue

            try:
                amount = _to_amount(raw)
            except ValueError as exc:
                issues.append({"ref": ref, "message": f'Amount "{raw}" {exc}.'})
                continue
            if amount is None:
                continue

            if day is None:
                issues.append({
                    "ref": ref,
                    "message": f"Amount {amount:,} has no valid date in column A of row {r}.",
                })
                continue
            if day > today + dt.timedelta(days=1):
                issues.append({
                    "ref": ref,
                    "message": f"Amount {amount:,} is dated in the future ({day:%d %b %Y}).",
                })
                continue

            slot = combined.setdefault((day, header), {"amount": Decimal("0.00"), "refs": []})
            slot["amount"] += amount
            slot["refs"].append(ref)

    rows = []
    order = {h: i for i, h in enumerate(headers.values())}
    for (day, header), slot in sorted(combined.items(), key=lambda kv: (kv[0][0], order[kv[0][1]])):
        if len(slot["refs"]) > 1:
            notes.append(
                f'{header} on {day:%d %b %Y} appears in more than one row '
                f'({", ".join(slot["refs"])}); the amounts were added together.'
            )
        rows.append({
            "date": day.isoformat(),
            "header": header,
            "amount": str(slot["amount"]),
            "ref": slot["refs"][0],
        })

    return {
        "sheet": title,
        "headers": list(headers.values()),
        "rows": rows,
        "issues": issues,
        "notes": notes,
        "date_from": rows[0]["date"] if rows else None,
        "date_to": rows[-1]["date"] if rows else None,
    }


# --------------------------------------------------------------------------
# CATEGORY MAPPING
# --------------------------------------------------------------------------
def suggest_category_map(headers):
    """
    For each sheet heading, the best existing ExpenseCategory:
        {heading: {"category_id": id|None, "match": "exact"|"similar"|"new",
                   "category_name": str}}
    "similar" catches spelling slips (Maintainance/Maintenance) so the
    person can confirm instead of ending up with two categories.
    """
    categories = list(ExpenseCategory.objects.all())
    by_key = {name_key(c.name): c for c in categories}
    keys = list(by_key)
    result = {}
    for header in headers:
        key = name_key(header)
        if key in by_key:
            match, cat = "exact", by_key[key]
        else:
            close = difflib.get_close_matches(key, keys, n=1, cutoff=0.85)
            match, cat = ("similar", by_key[close[0]]) if close else ("new", None)
        result[header] = {
            "category_id": cat.pk if cat else None,
            "match": match,
            "category_name": cat.name if cat else "",
        }
    return result


# --------------------------------------------------------------------------
# CLASSIFY
# --------------------------------------------------------------------------
def classify_rows(depot, rows, mapping, allow_overlap=False):
    """
    mapping: {heading: category_id or None}   (None = a new category will be created)

    Returns a dict with the rows grouped by status plus totals the preview
    page shows. `importable` is what commit_import() would save.
    """
    result = {
        "importable": [],
        NEW: [], ALREADY_IMPORTED: [], ALREADY_IN_APP: [], CHANGED: [], OVERLAP: [],
    }
    if not rows:
        result["totals"] = {"count": 0, "amount": Decimal("0.00")}
        result["by_month"] = []
        result["by_header"] = {}
        return result

    dates = [dt.date.fromisoformat(r["date"]) for r in rows]
    existing = defaultdict(list)
    for exp in Expense.objects.filter(
        depot=depot, is_reversed=False,
        expense_date__gte=min(dates), expense_date__lte=max(dates),
    ).values("category_id", "expense_date", "amount", "import_batch_id"):
        existing[(exp["expense_date"], exp["category_id"])].append(exp)

    for row, day in zip(rows, dates):
        amount = Decimal(row["amount"])
        category_id = mapping.get(row["header"])
        entry = dict(row, day=day, amount_dec=amount, category_id=category_id)

        found = existing.get((day, category_id), []) if category_id else []
        if not found:
            status = NEW
        elif any(e["amount"] == amount for e in found):
            imported_same = any(e["amount"] == amount and e["import_batch_id"] for e in found)
            status = ALREADY_IMPORTED if imported_same else ALREADY_IN_APP
        elif any(e["import_batch_id"] for e in found):
            status = CHANGED
            entry["app_amount"] = next(e["amount"] for e in found if e["import_batch_id"])
        else:
            status = OVERLAP
            entry["app_amount"] = found[0]["amount"]

        entry["status"] = status
        result[status].append(entry)
        if status == NEW or (status == OVERLAP and allow_overlap):
            result["importable"].append(entry)

    by_month = OrderedDict()
    by_header = OrderedDict()
    for e in result["importable"]:
        month = e["day"].strftime("%Y-%m")
        m = by_month.setdefault(month, {"month": e["day"].replace(day=1), "count": 0, "amount": Decimal("0.00")})
        m["count"] += 1
        m["amount"] += e["amount_dec"]
        h = by_header.setdefault(e["header"], {"count": 0, "amount": Decimal("0.00")})
        h["count"] += 1
        h["amount"] += e["amount_dec"]

    result["by_month"] = list(by_month.values())
    result["by_header"] = by_header
    result["totals"] = {
        "count": len(result["importable"]),
        "amount": sum((e["amount_dec"] for e in result["importable"]), Decimal("0.00")),
    }
    return result


# --------------------------------------------------------------------------
# COMMIT
# --------------------------------------------------------------------------
def _resolve_categories(headers, mapping):
    """Create the categories the person chose to create; return {heading: category}."""
    resolved = {}
    for header in headers:
        category_id = mapping.get(header)
        if category_id:
            resolved[header] = ExpenseCategory.objects.get(pk=category_id)
        else:
            existing = ExpenseCategory.objects.filter(name__iexact=header).first()
            resolved[header] = existing or ExpenseCategory.objects.create(name=header)
    return resolved


@transaction.atomic
def commit_import(*, user, depot, file_name, sheet_name, rows, headers, mapping,
                  payment_method, auto_approve=False, allow_overlap=False):
    """
    Save the importable rows. The classification is redone here against the
    current database, so a stale preview can never create duplicates.
    """
    used_headers = [h for h in headers if any(r["header"] == h for r in rows)]
    categories = _resolve_categories(used_headers, mapping)
    final_mapping = {h: c.pk for h, c in categories.items()}

    classified = classify_rows(depot, rows, final_mapping, allow_overlap=allow_overlap)
    todo = classified["importable"]

    batch = ExpenseImportBatch.objects.create(
        depot=depot,
        file_name=file_name[:255],
        sheet_name=sheet_name[:100],
        uploaded_by=user,
        payment_method=payment_method,
        auto_approved=auto_approve,
        date_from=dt.date.fromisoformat(rows[0]["date"]) if rows else None,
        date_to=dt.date.fromisoformat(rows[-1]["date"]) if rows else None,
    )

    total = Decimal("0.00")
    for entry in todo:
        Expense(
            depot=depot,
            category=categories[entry["header"]],
            expense_date=entry["day"],
            description=f'{entry["header"]} \u2014 daily total (Excel import)',
            amount=entry["amount_dec"],
            payment_method=payment_method,
            approved=auto_approve,
            import_batch=batch,
        ).save()
        total += entry["amount_dec"]

    batch.expenses_created = len(todo)
    batch.rows_skipped = len(rows) - len(todo)
    batch.total_amount = total
    batch.save(update_fields=["expenses_created", "rows_skipped", "total_amount", "updated_at"])
    return batch, classified


# --------------------------------------------------------------------------
# BATCH ACTIONS
# --------------------------------------------------------------------------
def approve_batch(batch):
    """Approve every pending, non-reversed expense of the batch. Returns the count."""
    return Expense.objects.filter(
        import_batch=batch, approved=False, is_reversed=False,
    ).update(approved=True, updated_at=timezone.now())


@transaction.atomic
def reverse_batch(batch, user, reason):
    """Reverse every live expense of the batch (equal-and-opposite ledger entries)."""
    count = 0
    for expense in batch.expenses.filter(is_reversed=False).select_related("depot"):
        expense.reverse(user=user, reason=reason)
        count += 1
    return count
