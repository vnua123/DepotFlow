from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.models import TimeStampedModel
from depots.models import Depot
from inventory.models import Supplier, StockReceipt
from core.utils import generate_document_number, next_sequence


# =========================
# EXPENSE CATEGORY
# =========================
class ExpenseCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# =========================
# EXPENSE IMPORT BATCH
# =========================
class ExpenseImportBatch(TimeStampedModel):
    """
    One upload of an expense workbook. Every Expense created by the
    importer points back at its batch, so a whole import can be
    reviewed, approved or reversed together.
    """

    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="expense_import_batches"
    )

    file_name = models.CharField(max_length=255)
    sheet_name = models.CharField(max_length=100, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    payment_method = models.CharField(max_length=10)
    auto_approved = models.BooleanField(default=False)

    expenses_created = models.PositiveIntegerField(default=0)
    rows_skipped = models.PositiveIntegerField(default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    date_from = models.DateField(null=True, blank=True)
    date_to = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Expense import batches"

    def __str__(self):
        return f"{self.file_name} ({self.created_at:%Y-%m-%d %H:%M})"


# =========================
# BUSINESS LEDGER
# =========================
class BusinessLedger(TimeStampedModel):
    class TransactionType(models.TextChoices):
        INCOME = "INCOME", "Income"
        EXPENSE = "EXPENSE", "Expense"
        SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT", "Supplier Payment"
        REBATE = "REBATE", "Supplier Rebate"

    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="ledger_entries"
    )

    transaction_type = models.CharField(
        max_length=30,
        choices=TransactionType.choices
    )

    transaction_date = models.DateField()

    description = models.TextField()

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    reference = models.CharField(
        max_length=100,
        blank=True
    )

    class Meta:
        ordering = ["-transaction_date", "-created_at"]

    def __str__(self):
        return f"{self.transaction_type} - ₦{self.amount}"


# =========================
# LEDGER-POSTED RECORD (abstract)
# =========================
class LedgerPostedRecord(TimeStampedModel):
    """
    Shared behavior for finance records that post an entry to
    BusinessLedger on creation: Expense, SupplierPayment,
    SupplierRebate.

    Once posted, the financial substance of the record is locked —
    save() will refuse to change any field listed in locked_fields.
    Correcting a mistake means calling reverse(), which posts an
    equal-and-opposite BusinessLedger entry (so both the original
    and the correction remain visible in the ledger) and marks this
    record as reversed. A brand new, correct record should then be
    created separately. Nothing is ever silently rewritten.
    """

    is_reversed = models.BooleanField(default=False)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True)

    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    # Subclasses MUST override these.
    ledger_transaction_type = None
    locked_fields = ()

    class Meta:
        abstract = True

    # --- hooks subclasses must implement -----------------------------
    def _ledger_depot(self):
        return self.depot

    def _ledger_date(self):
        raise NotImplementedError

    def _ledger_description(self):
        raise NotImplementedError

    def _ledger_reference(self):
        raise NotImplementedError

    # --- shared behavior ----------------------------------------------
    def _create_ledger_entry(self, amount=None, description=None, reference=None):
        BusinessLedger.objects.create(
            depot=self._ledger_depot(),
            transaction_type=self.ledger_transaction_type,
            transaction_date=self._ledger_date(),
            description=description or self._ledger_description(),
            amount=amount if amount is not None else self.amount,
            reference=reference or self._ledger_reference(),
        )

    def _check_locked_fields_unchanged(self):
        if self.pk is None:
            return

        original = type(self).objects.get(pk=self.pk)

        for field_name in self.locked_fields:
            if getattr(original, field_name) != getattr(self, field_name):
                raise ValidationError(
                    f"'{field_name}' cannot be changed after this record "
                    "has posted to the business ledger. Use reverse() "
                    "and create a new, corrected record instead."
                )

    def reverse(self, user=None, reason=""):
        """
        Post an equal-and-opposite BusinessLedger entry and mark
        this record as reversed. Does NOT delete or edit the
        original record or its original ledger entry — both remain
        as a permanent audit trail.
        """

        if self.is_reversed:
            raise ValidationError("This record has already been reversed.")

        from core.audit import log_action
        from core.models import AuditLog

        with transaction.atomic():
            self._create_ledger_entry(
                amount=-self.amount,
                description=f"REVERSAL: {self._ledger_description()}",
                reference=f"REV-{self._ledger_reference()}",
            )

            self.is_reversed = True
            self.reversed_at = timezone.now()
            self.reversal_reason = reason
            self.reversed_by = user

            super(LedgerPostedRecord, self).save(
                update_fields=[
                    "is_reversed",
                    "reversed_at",
                    "reversal_reason",
                    "reversed_by",
                    "updated_at",
                ]
            )

            log_action(
                AuditLog.Action.FINANCE_REVERSAL,
                obj=self,
                user=user,
                old_value={"amount": str(self.amount), "is_reversed": False},
                new_value={"amount": str(self.amount), "is_reversed": True},
                notes=reason,
            )


# =========================
# EXPENSE
# =========================
class Expense(LedgerPostedRecord):
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK = "BANK", "Bank Transfer"
        POS = "POS", "POS"
        OTHER = "OTHER", "Other"

    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="expenses"
    )

    category = models.ForeignKey(
        ExpenseCategory,
        on_delete=models.PROTECT,
        related_name="expenses"
    )

    expense_date = models.DateField(default=timezone.now)

    description = models.TextField()

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    payment_method = models.CharField(
        max_length=10,
        choices=PaymentMethod.choices
    )

    reference_number = models.CharField(
        max_length=100,
        blank=True
    )

    # Workflow field — deliberately NOT in locked_fields.
    approved = models.BooleanField(default=False)

    # Set when the expense was created by an Excel import; null for
    # expenses typed into the app. Not a locked field.
    import_batch = models.ForeignKey(
        ExpenseImportBatch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="expenses",
    )

    ledger_transaction_type = BusinessLedger.TransactionType.EXPENSE
    locked_fields = ("depot", "category", "expense_date", "amount", "description")

    class Meta:
        ordering = ["-expense_date", "-created_at"]

    def __str__(self):
        return f"{self.category.name} - ₦{self.amount}"

    def _ledger_date(self):
        return self.expense_date

    def _ledger_description(self):
        return self.description

    def _ledger_reference(self):
        return self.reference_number

    def save(self, *args, **kwargs):
        self._check_locked_fields_unchanged()

        if not self.reference_number:
            self.reference_number = generate_document_number(
                prefix="EXP",
                depot_code=self.depot.code,
                sequence=next_sequence(Expense, "reference_number"),
            )

        is_new = self.pk is None

        with transaction.atomic():
            super().save(*args, **kwargs)

            if is_new:
                self._create_ledger_entry()


# =========================
# SUPPLIER PAYMENT
# =========================
class SupplierPayment(LedgerPostedRecord):
    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="supplier_payments"
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="payments"
    )

    stock_receipt = models.ForeignKey(
        StockReceipt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    payment_date = models.DateField(default=timezone.now)

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    reference_number = models.CharField(
        max_length=100,
        blank=True
    )

    notes = models.TextField(blank=True)

    ledger_transaction_type = BusinessLedger.TransactionType.SUPPLIER_PAYMENT
    locked_fields = ("depot", "supplier", "payment_date", "amount")

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    def __str__(self):
        return f"{self.supplier.name} - ₦{self.amount}"

    def _ledger_date(self):
        return self.payment_date

    def _ledger_description(self):
        return f"Payment to {self.supplier.name}"

    def _ledger_reference(self):
        return self.reference_number

    def save(self, *args, **kwargs):
        self._check_locked_fields_unchanged()

        if not self.reference_number:
            self.reference_number = generate_document_number(
                prefix="SPY",
                depot_code=self.depot.code,
                sequence=next_sequence(SupplierPayment, "reference_number"),
            )

        is_new = self.pk is None

        with transaction.atomic():
            super().save(*args, **kwargs)

            if is_new:
                self._create_ledger_entry()


# =========================
# SUPPLIER REBATE
# =========================
class SupplierRebate(LedgerPostedRecord):
    depot = models.ForeignKey(
        Depot,
        on_delete=models.PROTECT,
        related_name="supplier_rebates"
    )

    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name="rebates"
    )

    rebate_date = models.DateField(default=timezone.now)

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2
    )

    description = models.TextField(blank=True)

    reference_number = models.CharField(
        max_length=100,
        blank=True
    )

    ledger_transaction_type = BusinessLedger.TransactionType.REBATE
    locked_fields = ("depot", "supplier", "rebate_date", "amount")

    class Meta:
        ordering = ["-rebate_date", "-created_at"]

    def __str__(self):
        return f"{self.supplier.name} - ₦{self.amount}"

    def _ledger_date(self):
        return self.rebate_date

    def _ledger_description(self):
        return f"Rebate from {self.supplier.name}"

    def _ledger_reference(self):
        return self.reference_number

    def save(self, *args, **kwargs):
        self._check_locked_fields_unchanged()

        if not self.reference_number:
            self.reference_number = generate_document_number(
                prefix="SRB",
                depot_code=self.depot.code,
                sequence=next_sequence(SupplierRebate, "reference_number"),
            )

        is_new = self.pk is None

        with transaction.atomic():
            super().save(*args, **kwargs)

            if is_new:
                self._create_ledger_entry()