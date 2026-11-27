from rest_framework import serializers

from .models import ExpenseCategory, BusinessLedger, Expense, SupplierPayment, SupplierRebate


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name"]


class BusinessLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessLedger
        fields = ["id", "depot", "transaction_type", "transaction_date", "description", "amount", "reference"]
        read_only_fields = fields  # entries are only ever created by the models/services above, never directly


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id", "depot", "category", "category_name", "expense_date", "description",
            "amount", "payment_method", "reference_number", "approved",
            "is_reversed", "reversed_at", "reversal_reason",
        ]
        read_only_fields = [
            "reference_number", "approved", "is_reversed", "reversed_at", "reversal_reason",
        ]


class SupplierPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierPayment
        fields = [
            "id", "depot", "supplier", "stock_receipt", "payment_date", "amount",
            "reference_number", "notes", "is_reversed", "reversed_at", "reversal_reason",
        ]
        read_only_fields = ["reference_number", "is_reversed", "reversed_at", "reversal_reason"]


class SupplierRebateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierRebate
        fields = [
            "id", "depot", "supplier", "rebate_date", "amount", "description",
            "reference_number", "is_reversed", "reversed_at", "reversal_reason",
        ]
        read_only_fields = ["reference_number", "is_reversed", "reversed_at", "reversal_reason"]


class ReversalSerializer(serializers.Serializer):
    """
    Not a ModelSerializer — reversal always goes through
    LedgerPostedRecord.reverse(), never a direct field edit (mirrors
    finance.forms.ReversalForm).
    """

    reason = serializers.CharField()
