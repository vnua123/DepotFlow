from django.contrib import admin
from .models import (
    ExpenseCategory,
    Expense,
    BusinessLedger,
    SupplierPayment,
    SupplierRebate,
)


REVERSAL_ADMIN_REASON = "Reversed via Django admin action."


def make_reverse_action(model_label):
    def reverse_selected(modeladmin, request, queryset):
        reversed_count = 0
        skipped_count = 0

        for obj in queryset:
            if obj.is_reversed:
                skipped_count += 1
                continue

            obj.reverse(user=request.user, reason=REVERSAL_ADMIN_REASON)
            reversed_count += 1

        modeladmin.message_user(
            request,
            f"Reversed {reversed_count} {model_label}(s). "
            f"Skipped {skipped_count} already-reversed record(s).",
        )

    reverse_selected.short_description = f"Reverse selected {model_label}(s)"
    return reverse_selected


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "expense_date",
        "depot",
        "category",
        "amount",
        "payment_method",
        "approved",
        "is_reversed",
    )
    list_filter = (
        "depot",
        "category",
        "payment_method",
        "approved",
        "is_reversed",
    )
    search_fields = ("description", "reference_number")
    actions = [make_reverse_action("expense")]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.pk:
            return [
                "depot", "category", "expense_date", "amount", "description",
                "reference_number", "is_reversed", "reversed_at",
                "reversal_reason", "reversed_by",
            ]
        return ["is_reversed", "reversed_at", "reversal_reason", "reversed_by"]


@admin.register(BusinessLedger)
class BusinessLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "depot",
        "transaction_type",
        "amount",
        "reference",
    )
    list_filter = ("depot", "transaction_type")
    search_fields = ("reference", "description")

    def has_change_permission(self, request, obj=None):
        # The ledger is the audit trail — corrections happen via
        # reverse() on the source record, never a direct edit here.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "payment_date",
        "supplier",
        "depot",
        "amount",
        "is_reversed",
    )
    list_filter = ("depot", "payment_date", "is_reversed")
    actions = [make_reverse_action("supplier payment")]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.pk:
            return [
                "depot", "supplier", "payment_date", "amount",
                "reference_number", "is_reversed", "reversed_at",
                "reversal_reason", "reversed_by",
            ]
        return ["is_reversed", "reversed_at", "reversal_reason", "reversed_by"]


@admin.register(SupplierRebate)
class SupplierRebateAdmin(admin.ModelAdmin):
    list_display = (
        "rebate_date",
        "supplier",
        "depot",
        "amount",
        "is_reversed",
    )
    list_filter = ("depot", "rebate_date", "is_reversed")
    actions = [make_reverse_action("supplier rebate")]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.pk:
            return [
                "depot", "supplier", "rebate_date", "amount",
                "reference_number", "is_reversed", "reversed_at",
                "reversal_reason", "reversed_by",
            ]
        return ["is_reversed", "reversed_at", "reversal_reason", "reversed_by"]


