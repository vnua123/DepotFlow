from rest_framework.routers import DefaultRouter

from .api import (
    VehicleViewSet, VehicleSalesmanViewSet,
    VehicleLoadViewSet, VehicleLoadItemViewSet,
    VehicleReturnViewSet, VehicleReturnItemViewSet,
)

router = DefaultRouter()
router.register("vehicles", VehicleViewSet, basename="vehicle")
router.register("salesmen", VehicleSalesmanViewSet, basename="salesman")
router.register("vehicle-loads", VehicleLoadViewSet, basename="vehicleload")
router.register("vehicle-load-items", VehicleLoadItemViewSet, basename="vehicleloaditem")
router.register("vehicle-returns", VehicleReturnViewSet, basename="vehiclereturn")
router.register("vehicle-return-items", VehicleReturnItemViewSet, basename="vehiclereturnitem")

urlpatterns = router.urls
