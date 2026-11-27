from django.contrib import admin
from .models import Customer, Sale, SaleItem


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "outlet_type", "depot", "phone", "is_active")
    list_filter = ("outlet_type", "depot", "is_active")
    search_fields = ("name", "phone")


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1

    def get_readonly_fields(self, request, obj=None):
        # unit_cost/unit_price/discount_applied are always
        # computed in SaleItem.save(), never hand-entered.
        readonly = ["unit_cost", "unit_price", "discount_applied"]

        if obj and obj.is_finalized:
            readonly += ["product", "quantity", "promotion"]

        return readonly


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        "sale_number",
        "vehicle_load",
        "salesman",
        "customer",
        "sale_date",
        "is_finalized",
    )
    list_filter = ("sale_date", "is_finalized")
    search_fields = ("sale_number",)
    inlines = [SaleItemInline]
    readonly_fields = ("sale_number", "is_finalized", "finalized_at")
    actions = ["finalize_sales"]

    def finalize_sales(self, request, queryset):
        finalized = 0
        skipped = 0

        for sale in queryset:
            if sale.is_finalized:
                skipped += 1
                continue

            try:
                sale.finalize()
                finalized += 1
            except Exception as exc:
                self.message_user(request, f"{sale}: {exc}", level="error")

        self.message_user(
            request,
            f"Finalized {finalized} sale(s). Skipped {skipped} already-finalized.",
        )

    finalize_sales.short_description = "Finalize selected sales (posts revenue to ledger)"