"""
Excel expense import: parsing the depot's date x category grid, comparing
it with what is already in the app, and saving through Expense.save().
"""
import datetime as dt
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from depots.models import Depot, Territory

from . import expense_import as ei
from .models import BusinessLedger, Expense, ExpenseCategory, ExpenseImportBatch

R = User.Role
PASSWORD = "S0me-long-pass-123"
D = dt.datetime


def make_user(username, role, depot=None):
    return User.objects.create_user(username=username, password=PASSWORD, role=role, depot=depot)


def build_workbook(rows, headers=("Fuel", "Salary"), sheet="Expense", extra_sheets=(), header_row=2):
    """rows: list of (date, {header: value}) ; returns an open BytesIO."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.cell(1, 9, "Expenses")
    ws.cell(header_row, 1, "Date")
    for col, h in enumerate(headers, start=2):
        ws.cell(header_row, col, h)
    r = header_row + 1
    for day, values in rows:
        ws.cell(r, 1, day)
        for h, v in values.items():
            ws.cell(r, headers.index(h) + 2, v)
        r += 1
    for name in extra_sheets:
        other = wb.create_sheet(name)
        other["A1"] = "Date"
        other["B1"] = "Tony"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def upload(buf, name="expenses.xlsx"):
    return SimpleUploadedFile(name, buf.getvalue(),
                              content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


PAST = dt.date.today() - dt.timedelta(days=10)


class ParseTests(TestCase):
    def test_reads_one_expense_per_non_empty_cell(self):
        buf = build_workbook([
            (D(2026, 1, 5), {"Fuel": 120000, "Salary": 50000}),
            (D(2026, 1, 6), {"Fuel": 40300}),
            (D(2026, 1, 7), {}),
        ])
        parsed = ei.parse_workbook(buf)
        self.assertEqual(parsed["issues"], [])
        self.assertEqual(
            [(r["date"], r["header"], r["amount"]) for r in parsed["rows"]],
            [("2026-01-05", "Fuel", "120000.00"), ("2026-01-05", "Salary", "50000.00"),
             ("2026-01-06", "Fuel", "40300.00")],
        )
        self.assertEqual(parsed["sheet"], "Expense")

    def test_total_rows_zeros_blanks_and_columns_past_the_headings_are_ignored(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Expense"
        ws["A2"], ws["B2"], ws["C2"] = "Date", "Fuel", "Salary"
        ws["A3"], ws["B3"], ws["C3"] = D(2026, 1, 5), 1000, 0
        ws["A4"], ws["B4"], ws["C4"] = "Total", "=SUM(B3:B3)", "=SUM(C3:C3)"
        ws["S5"], ws["T5"], ws["V5"] = "Grand total", "=SUM(B4:C4)", 450000   # RB / grand-total area
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        parsed = ei.parse_workbook(buf)
        self.assertEqual(parsed["issues"], [])
        self.assertEqual(len(parsed["rows"]), 1)
        self.assertEqual(parsed["rows"][0]["amount"], "1000.00")

    def test_prefers_the_expense_sheet_over_other_sheets_with_a_date_heading(self):
        buf = build_workbook([(D(2026, 1, 5), {"Fuel": 10})], extra_sheets=("Daily Sales", "Monthly Summary"))
        self.assertEqual(ei.parse_workbook(buf)["sheet"], "Expense")

    def test_amount_problems_block_the_import_instead_of_being_dropped(self):
        buf = build_workbook([
            (D(2026, 1, 5), {"Fuel": "abc", "Salary": -5}),
            (D(2026, 1, 6), {"Fuel": "1,200"}),
            (dt.date.today() + dt.timedelta(days=30), {"Fuel": 10}),
        ])
        parsed = ei.parse_workbook(buf)
        messages = " | ".join(i["message"] for i in parsed["issues"])
        self.assertEqual(len(parsed["issues"]), 3)
        self.assertIn("not a number", messages)
        self.assertIn("negative", messages)
        self.assertIn("future", messages)
        # the valid "1,200" cell is still read
        self.assertEqual([r["amount"] for r in parsed["rows"]], ["1200.00"])

    def test_amount_with_no_date_is_reported(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Expense"
        ws["A2"], ws["B2"] = "Date", "Fuel"
        ws["A3"], ws["B3"] = "someday", 5000
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        parsed = ei.parse_workbook(buf)
        self.assertEqual(len(parsed["issues"]), 1)
        self.assertIn("no valid date", parsed["issues"][0]["message"])

    def test_formula_without_a_saved_result_is_reported(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Expense"
        ws["A2"], ws["B2"] = "Date", "Fuel"
        ws["A3"], ws["B3"] = D(2026, 1, 5), "=1000+500"   # written by openpyxl: no cached value
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        parsed = ei.parse_workbook(buf)
        self.assertEqual(parsed["rows"], [])
        self.assertIn("no saved result", parsed["issues"][0]["message"])

    def test_two_rows_for_the_same_day_and_category_are_added_together(self):
        buf = build_workbook([(D(2026, 1, 5), {"Fuel": 100}), (D(2026, 1, 5), {"Fuel": 50})])
        parsed = ei.parse_workbook(buf)
        self.assertEqual(parsed["rows"][0]["amount"], "150.00")
        self.assertEqual(len(parsed["notes"]), 1)

    def test_unreadable_or_unusable_files_raise_a_friendly_error(self):
        with self.assertRaises(ei.SheetImportError):
            ei.parse_workbook(BytesIO(b"not an excel file"))
        with self.assertRaises(ei.SheetImportError):          # no "Date" heading
            wb = openpyxl.Workbook()
            wb.active["A1"] = "hello"
            buf = BytesIO(); wb.save(buf); buf.seek(0)
            ei.parse_workbook(buf)
        with self.assertRaises(ei.SheetImportError):          # wrong sheet name
            ei.parse_workbook(build_workbook([]), sheet_name="Nope")
        with self.assertRaises(ei.SheetImportError):          # duplicate headings
            ei.parse_workbook(build_workbook([], headers=("Fuel", "fuel")))


class ImportLogicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.territory = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=cls.territory, name="Mine", code="MI")
        cls.user = make_user("admin", R.SUPER_ADMIN)
        cls.fuel, _ = ExpenseCategory.objects.get_or_create(name="Fuel")
        cls.rows = [
            {"date": "2026-01-05", "header": "Fuel", "amount": "1000.00", "ref": "B3"},
            {"date": "2026-01-05", "header": "Salary", "amount": "500.50", "ref": "C3"},
        ]
        cls.headers = ["Fuel", "Salary"]

    def commit(self, rows=None, mapping=None, **kw):
        return ei.commit_import(
            user=self.user, depot=self.depot, file_name="f.xlsx", sheet_name="Expense",
            rows=rows or self.rows, headers=self.headers,
            mapping=mapping or {"Fuel": self.fuel.pk, "Salary": None},
            payment_method="CASH", **kw,
        )

    def test_commit_posts_real_expenses_with_ledger_entries_and_a_batch(self):
        batch, _ = self.commit()
        self.assertEqual(batch.expenses_created, 2)
        self.assertEqual(batch.total_amount, Decimal("1500.50"))
        self.assertEqual(Expense.objects.filter(import_batch=batch).count(), 2)
        self.assertEqual(BusinessLedger.objects.filter(transaction_type="EXPENSE").count(), 2)
        e = Expense.objects.get(category=self.fuel)
        self.assertTrue(e.reference_number.startswith("EXP-MI-"))
        self.assertFalse(e.approved)
        self.assertEqual(e.payment_method, "CASH")
        self.assertEqual(e.expense_date, dt.date(2026, 1, 5))
        self.assertIn("Fuel", e.description)

    def test_new_category_is_created_only_when_chosen_and_never_duplicated(self):
        self.commit()
        self.assertTrue(ExpenseCategory.objects.filter(name="Salary").exists())
        self.assertEqual(ExpenseCategory.objects.filter(name__iexact="fuel").count(), 1)

    def test_auto_approve(self):
        self.commit(auto_approve=True)
        self.assertFalse(Expense.objects.filter(approved=False).exists())

    def test_uploading_the_same_sheet_again_creates_nothing(self):
        self.commit()
        mapping = {"Fuel": self.fuel.pk, "Salary": ExpenseCategory.objects.get(name="Salary").pk}
        classified = ei.classify_rows(self.depot, self.rows, mapping)
        self.assertEqual(len(classified["importable"]), 0)
        self.assertEqual(len(classified[ei.ALREADY_IMPORTED]), 2)
        batch2, _ = self.commit(mapping=mapping)
        self.assertEqual(batch2.expenses_created, 0)
        self.assertEqual(Expense.objects.count(), 2)

    def test_a_changed_sheet_amount_is_a_conflict_not_a_second_expense(self):
        self.commit()
        mapping = {"Fuel": self.fuel.pk, "Salary": ExpenseCategory.objects.get(name="Salary").pk}
        rows = [dict(self.rows[0], amount="1200.00"), self.rows[1]]
        classified = ei.classify_rows(self.depot, rows, mapping)
        self.assertEqual(len(classified[ei.CHANGED]), 1)
        self.assertEqual(classified[ei.CHANGED][0]["app_amount"], Decimal("1000.00"))
        self.assertEqual(len(classified["importable"]), 0)

    def test_expenses_typed_into_the_app_are_not_duplicated(self):
        Expense.objects.create(depot=self.depot, category=self.fuel, expense_date=dt.date(2026, 1, 5),
                               description="Diesel", amount=Decimal("1000.00"), payment_method="CASH")
        Expense.objects.create(depot=self.depot, category=self.fuel, expense_date=dt.date(2026, 1, 6),
                               description="Diesel", amount=Decimal("77.00"), payment_method="CASH")
        mapping = {"Fuel": self.fuel.pk, "Salary": None}
        classified = ei.classify_rows(self.depot, self.rows, mapping)
        self.assertEqual(len(classified[ei.ALREADY_IN_APP]), 1)     # same day/category/amount
        self.assertEqual(len(classified["importable"]), 1)          # Salary only

        rows = [{"date": "2026-01-06", "header": "Fuel", "amount": "900.00", "ref": "B4"}]
        strict = ei.classify_rows(self.depot, rows, mapping)
        self.assertEqual(len(strict[ei.OVERLAP]), 1)
        self.assertEqual(len(strict["importable"]), 0)
        loose = ei.classify_rows(self.depot, rows, mapping, allow_overlap=True)
        self.assertEqual(len(loose["importable"]), 1)

    def test_other_depots_do_not_interfere(self):
        other = Depot.objects.create(territory=self.territory, name="Other", code="OT")
        Expense.objects.create(depot=other, category=self.fuel, expense_date=dt.date(2026, 1, 5),
                               description="x", amount=Decimal("1000.00"), payment_method="CASH")
        classified = ei.classify_rows(self.depot, self.rows, {"Fuel": self.fuel.pk, "Salary": None})
        self.assertEqual(len(classified["importable"]), 2)

    def test_suggest_category_map(self):
        s = ei.suggest_category_map(["fuel ", "Warehous maintainance", "Pure water"])
        self.assertEqual((s["fuel "]["match"], s["fuel "]["category_id"]), ("exact", self.fuel.pk))
        self.assertEqual(s["Warehous maintainance"]["match"], "similar")
        self.assertEqual(s["Warehous maintainance"]["category_name"], "Warehouse maintainance")
        self.assertEqual(s["Pure water"]["match"], "exact")
        self.assertIsNotNone(s["Pure water"]["category_id"])

    def test_approve_batch_and_reverse_batch(self):
        batch, _ = self.commit()
        self.assertEqual(ei.approve_batch(batch), 2)
        self.assertEqual(ei.reverse_batch(batch, self.user, "wrong depot"), 2)
        self.assertEqual(Expense.objects.filter(is_reversed=True).count(), 2)
        self.assertEqual(
            sum(e.amount for e in BusinessLedger.objects.all()), Decimal("0.00"),
        )
        # reversed rows no longer block a corrected re-import
        mapping = {"Fuel": self.fuel.pk, "Salary": ExpenseCategory.objects.get(name="Salary").pk}
        classified = ei.classify_rows(self.depot, self.rows, mapping)
        self.assertEqual(len(classified["importable"]), 2)


class ImportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.territory = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=cls.territory, name="Mine", code="MI")
        cls.other_depot = Depot.objects.create(territory=cls.territory, name="Theirs", code="TH")
        cls.owner = make_user("owner", R.DEPOT_OWNER, depot=cls.depot)
        cls.other_owner = make_user("owner2", R.DEPOT_OWNER, depot=cls.other_depot)
        cls.officer = make_user("officer", R.DEPOT_OFFICER, depot=cls.depot)
        cls.viewer = make_user("viewer", R.VIEWER, depot=cls.depot)
        ExpenseCategory.objects.get_or_create(name="Fuel")

    def sheet(self, **kw):
        return build_workbook([(D(PAST.year, PAST.month, PAST.day), {"Fuel": 1000, "Salary": 500})], **kw)

    def start_import(self, buf=None, **extra):
        data = {"depot": self.depot.pk, "file": upload(buf or self.sheet()),
                "payment_method": "CASH", "sheet_name": "", **extra}
        return self.client.post(reverse("finance:expense_import"), data)

    def test_viewer_cannot_open_the_importer(self):
        self.client.login(username="viewer", password=PASSWORD)
        response = self.client.get(reverse("finance:expense_import"))
        self.assertRedirects(response, reverse("finance:expense_list"))

    def test_upload_preview_confirm_end_to_end(self):
        self.client.login(username="owner", password=PASSWORD)
        response = self.start_import(mark_approved="on")
        self.assertRedirects(response, reverse("finance:expense_import_preview"))

        preview = self.client.get(reverse("finance:expense_import_preview"))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["classified"]["totals"]["count"], 2)
        self.assertEqual(Expense.objects.count(), 0)             # nothing saved yet

        response = self.client.post(reverse("finance:expense_import_preview"), {
            "action": "confirm", "map_0": str(ExpenseCategory.objects.get(name="Fuel").pk), "map_1": "new",
        })
        batch = ExpenseImportBatch.objects.get()
        self.assertRedirects(response, reverse("finance:expense_import_batch_detail", args=[batch.pk]))
        self.assertEqual(Expense.objects.filter(import_batch=batch).count(), 2)
        self.assertTrue(ExpenseCategory.objects.filter(name="Salary").exists())
        self.assertTrue(Expense.objects.filter(approved=True).count() == 2)   # owner may approve
        self.assertEqual(batch.uploaded_by, self.owner)

        detail = self.client.get(reverse("finance:expense_import_batch_detail", args=[batch.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["live_count"], 2)

    def test_double_confirm_does_not_duplicate(self):
        self.client.login(username="owner", password=PASSWORD)
        self.start_import()
        url = reverse("finance:expense_import_preview")
        self.client.post(url, {"action": "confirm"})
        response = self.client.post(url, {"action": "confirm"})     # session already consumed
        self.assertRedirects(response, reverse("finance:expense_import"))
        self.assertEqual(Expense.objects.count(), 2)

    def test_sheet_problems_block_confirm(self):
        self.client.login(username="owner", password=PASSWORD)
        bad = build_workbook([(D(2026, 1, 5), {"Fuel": "abc"}), (D(2026, 1, 6), {"Fuel": 10})])
        self.start_import(bad)
        response = self.client.post(reverse("finance:expense_import_preview"), {"action": "confirm"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_confirm"])
        self.assertEqual(Expense.objects.count(), 0)

    def test_officer_cannot_auto_approve(self):
        self.client.login(username="officer", password=PASSWORD)
        self.start_import(mark_approved="on")
        self.client.post(reverse("finance:expense_import_preview"), {"action": "confirm"})
        self.assertEqual(Expense.objects.filter(approved=True).count(), 0)
        self.assertEqual(Expense.objects.count(), 2)

    def test_officer_cannot_approve_or_reverse_a_batch(self):
        self.client.login(username="owner", password=PASSWORD)
        self.start_import()
        self.client.post(reverse("finance:expense_import_preview"), {"action": "confirm"})
        batch = ExpenseImportBatch.objects.get()
        self.client.logout()
        self.client.login(username="officer", password=PASSWORD)
        self.client.post(reverse("finance:expense_import_batch_approve", args=[batch.pk]))
        self.client.post(reverse("finance:expense_import_batch_reverse", args=[batch.pk]), {"reason": "x"})
        self.assertEqual(Expense.objects.filter(approved=True).count(), 0)
        self.assertEqual(Expense.objects.filter(is_reversed=True).count(), 0)

    def test_approve_all_and_reverse_whole_import_as_owner(self):
        self.client.login(username="owner", password=PASSWORD)
        self.start_import()
        self.client.post(reverse("finance:expense_import_preview"), {"action": "confirm"})
        batch = ExpenseImportBatch.objects.get()
        self.client.post(reverse("finance:expense_import_batch_approve", args=[batch.pk]))
        self.assertEqual(Expense.objects.filter(approved=True).count(), 2)
        self.client.post(reverse("finance:expense_import_batch_reverse", args=[batch.pk]),
                         {"reason": "uploaded to the wrong depot"})
        self.assertEqual(Expense.objects.filter(is_reversed=True).count(), 2)

    def test_owner_cannot_import_into_or_view_another_depot(self):
        self.client.login(username="owner", password=PASSWORD)
        response = self.client.post(reverse("finance:expense_import"), {
            "depot": self.other_depot.pk, "file": upload(self.sheet()), "payment_method": "CASH",
        })
        self.assertEqual(response.status_code, 200)                 # form re-rendered with an error
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(Expense.objects.count(), 0)

        batch = ExpenseImportBatch.objects.create(
            depot=self.other_depot, file_name="theirs.xlsx", payment_method="CASH")
        detail = self.client.get(reverse("finance:expense_import_batch_detail", args=[batch.pk]))
        self.assertRedirects(detail, reverse("finance:expense_list"))
        listing = self.client.get(reverse("finance:expense_import_batch_list"))
        self.assertNotIn(batch, list(listing.context["batches"]))

    def test_wrong_file_type_and_unreadable_file_show_an_error(self):
        self.client.login(username="owner", password=PASSWORD)
        r = self.client.post(reverse("finance:expense_import"), {
            "depot": self.depot.pk, "payment_method": "CASH",
            "file": SimpleUploadedFile("expenses.csv", b"a,b"),
        })
        self.assertTrue(r.context["form"].errors["file"])
        r = self.client.post(reverse("finance:expense_import"), {
            "depot": self.depot.pk, "payment_method": "CASH",
            "file": SimpleUploadedFile("expenses.xlsx", b"not a workbook"),
        })
        self.assertTrue(r.context["form"].errors["file"])

    def test_template_download_uses_the_current_categories(self):
        self.client.login(username="officer", password=PASSWORD)
        response = self.client.get(reverse("finance:expense_import_template"))
        self.assertEqual(response.status_code, 200)
        ws = openpyxl.load_workbook(BytesIO(response.content))["Expense"]
        self.assertEqual(ws["A2"].value, "Date")
        expected_categories = list(ExpenseCategory.objects.order_by("name").values_list("name", flat=True))
        actual_categories = [ws.cell(2, col).value for col in range(2, ws.max_column + 1)]
        self.assertEqual(actual_categories, expected_categories)
        # and the importer can read its own template
        ws["A3"].value
        ws["B3"] = 2500
        buf = BytesIO(); ws.parent.save(buf); buf.seek(0)
        self.assertEqual(ei.parse_workbook(buf)["rows"][0]["amount"], "2500.00")

    def test_expense_list_is_paginated(self):
        cat = ExpenseCategory.objects.get(name="Fuel")
        for i in range(55):
            Expense.objects.create(depot=self.depot, category=cat, expense_date=dt.date(2026, 1, 1),
                                   description=f"e{i}", amount=Decimal("1.00"), payment_method="CASH")
        self.client.login(username="owner", password=PASSWORD)
        first = self.client.get(reverse("finance:expense_list"))
        self.assertEqual(len(first.context["expenses"]), 50)
        second = self.client.get(reverse("finance:expense_list") + "?page=2")
        self.assertEqual(len(second.context["expenses"]), 5)
