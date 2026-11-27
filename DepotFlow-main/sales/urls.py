from django.urls import path
from . import views

app_name = "sales"

urlpatterns = [
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_create, name="customer_create"),
    path("customers/<int:pk>/edit/", views.customer_update, name="customer_update"),

    path("", views.sale_list, name="sale_list"),
    path("loads/<int:load_pk>/new/", views.sale_create, name="sale_create"),
    path("<int:pk>/", views.sale_detail, name="sale_detail"),
    path("<int:pk>/finalize/", views.sale_finalize, name="sale_finalize"),
]