from rest_framework.routers import DefaultRouter

from .api import TerritoryViewSet, DepotViewSet

router = DefaultRouter()
router.register("territories", TerritoryViewSet, basename="territory")
router.register("depots", DepotViewSet, basename="depot")

urlpatterns = router.urls