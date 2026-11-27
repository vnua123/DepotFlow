from rest_framework.routers import DefaultRouter

from .api import CustomerViewSet, SaleViewSet, SaleItemViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("sales", SaleViewSet, basename="sale")
router.register("sale-items", SaleItemViewSet, basename="saleitem")

urlpatterns = router.urls
