from django.urls import path
from . import views

app_name = "depots"

urlpatterns = [
    path("territories/", views.territory_list, name="territory_list"),
    path("territories/new/", views.territory_create, name="territory_create"),
    path("territories/<int:pk>/edit/", views.territory_update, name="territory_update"),
    path("", views.depot_list, name="depot_list"),
    path("new/", views.depot_create, name="depot_create"),
    path("<int:pk>/", views.depot_detail, name="depot_detail"),
    path("<int:pk>/edit/", views.depot_update, name="depot_update"),
]