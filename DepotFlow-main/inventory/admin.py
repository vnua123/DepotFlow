from django.contrib import admin
from .models import (
    Product,
    PriceHistory,
    Supplier,
    StockReceipt,
    StockReceiptItem,
    InventoryTransaction,
    Promotion,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "name",
        "category",
        "package_type",
        "volume",
        "base_cost_price",
        "base_selling_price",
        "is_active",
    )
    search_fields = ("sku", "name")
    list_filter = ("category", "package_type", "is_active")


@admin.register(PriceHistory)
class PriceHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "selling_price",
        "cost_price",
        "effective_from",
        "changed_by",
        "reason",
    )
    list_filter = ("effective_from",)
    search_fields = ("product__sku", "product__name", "reason")
    readonly_fields = (
        "product",
        "cost_price",
        "selling_price",
        "effective_from",
        "changed_by",
        "reason",
    )

    def has_change_permission(self, request, obj=None):
        # Price history is append-only — a new effective-dated row
        # is how you change pricing, never an edit to an old one.
        return False

    def has_delete_permission(self, request, obj=None):
        # Preserve historical truth — old prices are never deleted.
        return False


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "phone", "is_active")
    search_fields = ("name",)


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "level",
        "promotion_type",
        "supplier",
        "depot",
        "start_date",
        "end_date",
        "is_active",
    )
    list_filter = ("level", "promotion_type", "is_active", "depot", "supplier")
    search_fields = ("name", "description")
    filter_horizontal = ("products",)
    autocomplete_fields = ("supplier", "depot")


class StockReceiptItemInline(admin.TabularInline):
    model = StockReceiptItem
    extra = 1
    readonly_fields = ()

    def get_readonly_fields(self, request, obj=None):
        # Once a receipt item has been saved (and its inventory
        # transaction posted), the acquisition cost must not be
        # editable — it's the historical record of what was
        # actually paid. New items can still be added freely.
        if obj and obj.pk:
            return ["product", "quantity", "cost_price"]
        return []


@admin.register(StockReceipt)
class StockReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "invoice_number",
        "supplier",
        "depot",
        "receipt_date",
        "total_amount",
    )
    list_filter = ("depot", "receipt_date")
    search_fields = ("invoice_number",)
    inlines = [StockReceiptItemInline]

    def get_readonly_fields(self, request, obj=None):
        # invoice_number is referenced as the `reference` string on
        # every InventoryTransaction created from this receipt's
        # items. Editing it after items exist would silently break
        # that traceability link.
        if obj and obj.pk:
            return ["invoice_number"]
        return []


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_date",
        "depot",
        "product",
        "transaction_type",
        "quantity",
        "unit_cost",
        "reference",
    )
    list_filter = ("depot", "transaction_type")
    search_fields = ("reference",)

    def has_change_permission(self, request, obj=None):
        # The ledger itself must never be hand-edited — it's the
        # audit trail. Adjustments go through a new ADJUSTMENT
        # transaction, not an edit to an existing row.
        return False

    def has_delete_permission(self, request, obj=None):
        return False