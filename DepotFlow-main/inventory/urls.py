from django.urls import path
from . import views

app_name = "inventory"

urlpatterns = [
    path("stock-balance/", views.stock_balance_lookup, name="stock_balance_lookup"),

    path("", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_update, name="product_update"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("products/<int:pk>/change-price/", views.change_price, name="change_price"),

    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_create, name="supplier_create"),
    path("suppliers/<int:pk>/edit/", views.supplier_update, name="supplier_update"),

    path("stock-receipts/", views.stock_receipt_list, name="stock_receipt_list"),
    path("stock-receipts/new/", views.stock_receipt_create, name="stock_receipt_create"),
    path("stock-receipts/<int:pk>/", views.stock_receipt_detail, name="stock_receipt_detail"),

    path("promotions/", views.promotion_list, name="promotion_list"),
    path("promotions/new/", views.promotion_create, name="promotion_create"),
    path("promotions/<int:pk>/edit/", views.promotion_update, name="promotion_update"),
]