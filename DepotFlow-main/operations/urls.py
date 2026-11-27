from django.urls import path
from . import views

app_name = "operations"

urlpatterns = [
    path("vehicles/", views.vehicle_list, name="vehicle_list"),
    path("vehicles/new/", views.vehicle_create, name="vehicle_create"),
    path("vehicles/<int:pk>/edit/", views.vehicle_update, name="vehicle_update"),
    path("vehicles/<int:pk>/delete/", views.vehicle_delete, name="vehicle_delete"),
    path("vehicles/<int:pk>/reassign-and-delete/", views.vehicle_reassign_and_delete, name="vehicle_reassign_and_delete"),

    path("salesmen/", views.salesman_list, name="salesman_list"),
    path("salesmen/new/", views.salesman_create, name="salesman_create"),
    path("salesmen/<int:pk>/edit/", views.salesman_update, name="salesman_update"),

    path("my-loads/", views.my_loads, name="my_loads"),

    path("targets/", views.target_list, name="target_list"),
    path("targets/new/", views.target_create, name="target_create"),
    path("targets/<int:pk>/edit/", views.target_update, name="target_update"),

    path("", views.load_list, name="load_list"),
    path("loads/new/", views.load_create, name="load_create"),
    path("loads/<int:pk>/", views.load_detail, name="load_detail"),
    path("loads/<int:pk>/close/", views.load_close, name="load_close"),

    path("loads/<int:load_pk>/returns/new/", views.return_create, name="return_create"),
    path("returns/<int:pk>/", views.return_detail, name="return_detail"),
    path("returns/<int:pk>/confirm/", views.return_confirm, name="return_confirm"),
]

# from django.urls import path

# from . import views

# app_name = "operations"

# urlpatterns = [
#     path("", views.dashboard, name="dashboard"),
#     path("transactions/", views.transaction_list, name="transaction_list"),
#     path("transactions/create/", views.transaction_create, name="transaction_create"),
#     path("transactions/<int:pk>/", views.transaction_detail, name="transaction_detail"),
#     path("transactions/<int:pk>/update/", views.transaction_update, name="transaction_update"),
#     path("transactions/<int:pk>/delete/", views.transaction_delete, name="transaction_delete"),
#     path("dispatches/", views.dispatch_list, name="dispatch_list"),
#     path("dispatches/create/", views.dispatch_create, name="dispatch_create"),
#     path("dispatches/<int:pk>/", views.dispatch_detail, name="dispatch_detail"),
#     path("dispatches/<int:pk>/update/", views.dispatch_update, name="dispatch_update"),
#     path("dispatches/<int:pk>/delete/", views.dispatch_delete, name="dispatch_delete"),
#     path("receipts/", views.receipt_list, name="receipt_list"),
#     path("receipts/create/", views.receipt_create, name="receipt_create"),
#     path("receipts/<int:pk>/", views.receipt_detail, name="receipt_detail"),
#     path("receipts/<int:pk>/update/", views.receipt_update, name="receipt_update"),
#     path("receipts/<int:pk>/delete/", views.receipt_delete, name="receipt_delete"),
# ]
