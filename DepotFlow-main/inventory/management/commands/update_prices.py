"""
Bulk-update SELLING prices for one or more SKUs by writing new
effective-dated PriceHistory records.

This command NEVER overwrites Product.base_selling_price /
Product.base_cost_price directly — it always goes through
inventory.services.record_price_change(), which is the only
authoritative way to change pricing (see the finalized
inventory/pricing decision).

Usage:

    Single SKU:
        python manage.py update_prices --sku 2619501 --selling-price 10500

    Single SKU with an informational cost reference and reason:
        python manage.py update_prices --sku 2619501 --selling-price 10500 \\
            --cost-price 8200 --reason "Supplier price increase"

    Backdated / future-dated price:
        python manage.py update_prices --sku 2619501 --selling-price 10500 \\
            --effective-from 2026-08-25

    Bulk, from a CSV or Excel file with columns:
        sku, selling_price, cost_price (optional), effective_from (optional), reason (optional)

        python manage.py update_prices --file prices.csv
        python manage.py update_prices --file prices.xlsx
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inventory.models import Product
from inventory.services import record_price_change


class Command(BaseCommand):
    help = "Update SKU selling prices via effective-dated PriceHistory records."

    def add_arguments(self, parser):
        parser.add_argument("--sku", type=str, help="Single SKU to update.")
        parser.add_argument("--selling-price", type=str, help="New selling price for --sku.")
        parser.add_argument("--cost-price", type=str, default=None, help="Optional cost reference for --sku.")
        parser.add_argument("--effective-from", type=str, default=None, help="ISO date/datetime, default now.")
        parser.add_argument("--reason", type=str, default="", help="Optional reason/note.")
        parser.add_argument("--file", type=str, default=None, help="Path to a CSV or XLSX file for bulk updates.")

    def handle(self, *args, **options):
        if options["file"]:
            self._handle_file(options["file"])
        elif options["sku"] and options["selling_price"]:
            self._handle_single(options)
        else:
            raise CommandError(
                "Provide either --file <path> for bulk updates, "
                "or --sku <sku> --selling-price <amount> for a single update."
            )

    # ------------------------------------------------------------------
    def _parse_effective_from(self, raw):
        if not raw:
            return timezone.now()

        parsed = parse_datetime(raw)
        if parsed:
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)

        try:
            naive = datetime.strptime(raw, "%Y-%m-%d")
            return timezone.make_aware(naive)
        except ValueError:
            raise CommandError(f"Could not parse --effective-from value: {raw}")

    def _parse_decimal(self, raw, field_name):
        try:
            return Decimal(str(raw))
        except (InvalidOperation, TypeError):
            raise CommandError(f"Invalid {field_name}: {raw}")

    # ------------------------------------------------------------------
    def _handle_single(self, options):
        sku = options["sku"].strip()

        try:
            product = Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            raise CommandError(f"No product found with SKU '{sku}'.")

        selling_price = self._parse_decimal(options["selling_price"], "selling price")
        cost_price = (
            self._parse_decimal(options["cost_price"], "cost price")
            if options["cost_price"] is not None
            else None
        )
        effective_from = self._parse_effective_from(options["effective_from"])

        record_price_change(
            product=product,
            selling_price=selling_price,
            cost_price=cost_price,
            effective_from=effective_from,
            reason=options["reason"],
        )

        self.stdout.write(self.style.SUCCESS(
            f"Recorded new selling price ₦{selling_price} for {sku} "
            f"effective {effective_from.isoformat()}."
        ))

    # ------------------------------------------------------------------
    def _handle_file(self, file_path):
        path = Path(file_path)

        if not path.exists():
            raise CommandError(f"File not found: {file_path}")

        rows = self._read_rows(path)

        updated = 0
        errors = []

        for line_no, row in enumerate(rows, start=2):  # header is line 1
            sku = str(row.get("sku", "")).strip()

            if not sku:
                errors.append(f"Line {line_no}: missing sku, skipped.")
                continue

            try:
                product = Product.objects.get(sku=sku)
            except Product.DoesNotExist:
                errors.append(f"Line {line_no}: SKU '{sku}' not found, skipped.")
                continue

            raw_selling_price = row.get("selling_price")
            if raw_selling_price in (None, ""):
                errors.append(f"Line {line_no}: missing selling_price for SKU '{sku}', skipped.")
                continue

            try:
                selling_price = self._parse_decimal(raw_selling_price, "selling price")
            except CommandError as exc:
                errors.append(f"Line {line_no}: {exc}")
                continue

            raw_cost_price = row.get("cost_price")
            cost_price = (
                self._parse_decimal(raw_cost_price, "cost price")
                if raw_cost_price not in (None, "")
                else None
            )

            raw_effective_from = row.get("effective_from")
            effective_from = (
                self._parse_effective_from(str(raw_effective_from))
                if raw_effective_from not in (None, "")
                else timezone.now()
            )

            reason = str(row.get("reason", "") or "")

            try:
                with transaction.atomic():
                    record_price_change(
                        product=product,
                        selling_price=selling_price,
                        cost_price=cost_price,
                        effective_from=effective_from,
                        reason=reason,
                    )
                updated += 1
            except ValueError as exc:
                errors.append(f"Line {line_no}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Updated prices for {updated} product(s)."))

        if errors:
            self.stdout.write(self.style.WARNING(f"{len(errors)} row(s) skipped:"))
            for error in errors:
                self.stdout.write(f"  - {error}")

    def _read_rows(self, path):
        if path.suffix.lower() == ".csv":
            import csv
            with open(path, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))

        if path.suffix.lower() in (".xlsx", ".xls"):
            try:
                import openpyxl  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise CommandError(
                    "Reading Excel files requires the optional 'openpyxl' package. "
                    "Install it with: pip install openpyxl"
                ) from exc

            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(values_only=True)
            headers = [str(h).strip().lower() if h else "" for h in next(rows_iter)]
            return [dict(zip(headers, row)) for row in rows_iter]

        raise CommandError(f"Unsupported file type: {path.suffix}. Use .csv or .xlsx.")