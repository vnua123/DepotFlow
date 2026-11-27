from django.urls import path
from . import views
app_name = 'rebates'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('health-checks/new/', views.health_check_create, name='health_check_create'),
    path('profitability/manage/', views.profitability_update, name='profitability_update'),
    path('calculate/', views.calculate, name='calculate'),
    path('placement/initial/', views.initial_placement, name='initial_placement'),
    path('placement/assess/', views.assess_quarter, name='assess_quarter'),
]
