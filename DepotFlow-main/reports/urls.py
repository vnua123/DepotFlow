from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("stock/", views.stock_view, name="stock_view"),
    path("depots/<int:depot_id>/daily-sales/", views.daily_sales_report, name="daily_sales_report"),
    path("depots/<int:depot_id>/stock-movement/", views.daily_stock_movement_report, name="daily_stock_movement_report"),
    path("depots/<int:depot_id>/inventory/", views.current_inventory_report, name="current_inventory_report"),
    path("depots/<int:depot_id>/expenses/", views.expense_report, name="expense_report"),
    path("depots/<int:depot_id>/net-profit/", views.net_profit_report, name="net_profit_report"),
    path("depots/<int:depot_id>/top-selling/", views.top_selling_skus_report, name="top_selling_skus_report"),
    path("depots/<int:depot_id>/slow-moving/", views.slow_moving_skus_report, name="slow_moving_skus_report"),
    path("salesmen/<int:salesman_id>/load-return/", views.salesman_load_return_report, name="salesman_load_return_report"),
    path("territories/<int:territory_id>/comparison/", views.territory_comparison_report, name="territory_comparison_report"),
    path("business-ledger/", views.business_ledger_summary_report, name="business_ledger_summary_report"),
]