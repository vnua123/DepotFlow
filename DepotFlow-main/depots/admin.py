from django.contrib import admin
from .models import Territory, Depot


@admin.register(Territory)
class TerritoryAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Depot)
class DepotAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "territory")
    list_filter = ("territory",)
    search_fields = ("code", "name")