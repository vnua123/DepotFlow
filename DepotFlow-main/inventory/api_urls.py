from rest_framework.routers import DefaultRouter

from .api import ProductViewSet, SupplierViewSet, PromotionViewSet

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("promotions", PromotionViewSet, basename="promotion")

urlpatterns = router.urls