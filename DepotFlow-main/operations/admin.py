from django.contrib import admin
from .models import (
    Vehicle,
    VehicleSalesman,
    VehicleLoad,
    VehicleLoadItem,
    VehicleReturn,
    VehicleReturnItem,
)


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = (
        "registration_number",
        "vehicle_name",
        "depot",
        "is_active",
    )
    list_filter = ("depot", "is_active")


@admin.register(VehicleSalesman)
class VehicleSalesmanAdmin(admin.ModelAdmin):
    list_display = (
        "employee_id",
        "name",
        "depot",
        "vehicle",
        "is_active",
    )
    list_filter = ("depot", "is_active")
    search_fields = (
        "employee_id",
        "name",
    )


class VehicleLoadItemInline(admin.TabularInline):
    model = VehicleLoadItem
    extra = 1


@admin.register(VehicleLoad)
class VehicleLoadAdmin(admin.ModelAdmin):
    list_display = (
        "load_number",
        "depot",
        "vehicle",
        "salesman",
        "load_date",
        "is_closed",
    )
    list_filter = ("depot", "load_date", "is_closed")
    search_fields = ("load_number",)
    inlines = [VehicleLoadItemInline]


class VehicleReturnItemInline(admin.TabularInline):
    model = VehicleReturnItem
    extra = 1


@admin.register(VehicleReturn)
class VehicleReturnAdmin(admin.ModelAdmin):
    list_display = (
        "return_number",
        "vehicle_load",
        "return_date",
    )
    list_filter = ("return_date",)
    search_fields = ("return_number",)
    inlines = [VehicleReturnItemInline]