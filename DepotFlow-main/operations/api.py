from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import role_permission
from core.scoping import get_visible_depots
from .models import (
    Vehicle, VehicleSalesman, VehicleLoad, VehicleLoadItem,
    VehicleReturn, VehicleReturnItem,
)
from .serializers import (
    VehicleSerializer, VehicleSalesmanSerializer,
    VehicleLoadSerializer, VehicleLoadItemSerializer,
    VehicleReturnSerializer, VehicleReturnItemSerializer,
)

# Matches operations.views._can_manage_operations.
_OPERATIONS_ROLES = ("SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER")


class OwnerReadOnlyViewSet(viewsets.ModelViewSet):
    """Depot Owners may read their own depot data but cannot mutate it."""
    def get_permissions(self):
        if getattr(self.request.user, "role", "") == "DEPOT_OWNER" and self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return super().get_permissions()


class VehicleViewSet(OwnerReadOnlyViewSet):
    serializer_class = VehicleSerializer
    permission_classes = [role_permission(*_OPERATIONS_ROLES)]

    def get_queryset(self):
        return Vehicle.objects.filter(
            depot__in=get_visible_depots(self.request.user)
        ).select_related("depot").order_by("registration_number")


class VehicleSalesmanViewSet(OwnerReadOnlyViewSet):
    serializer_class = VehicleSalesmanSerializer
    permission_classes = [role_permission(*_OPERATIONS_ROLES)]

    def get_queryset(self):
        return VehicleSalesman.objects.filter(
            depot__in=get_visible_depots(self.request.user)
        ).select_related("depot", "vehicle").order_by("name")


class VehicleLoadViewSet(OwnerReadOnlyViewSet):
    serializer_class = VehicleLoadSerializer
    permission_classes = [role_permission(*_OPERATIONS_ROLES)]

    def get_queryset(self):
        return (
            VehicleLoad.objects
            .filter(depot__in=get_visible_depots(self.request.user))
            .select_related("depot", "vehicle", "salesman")
            .prefetch_related("items")
            .order_by("-load_date", "-created_at")
        )

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        load = self.get_object()
        load.close_load()
        return Response(VehicleLoadSerializer(load).data)


class VehicleLoadItemViewSet(OwnerReadOnlyViewSet):
    """
    Add/remove line items on an open vehicle load.

    Filter by ?vehicle_load=<id>. Stock-availability and closed-load
    checks live in VehicleLoadItem.clean()/save() and are surfaced as
    normal 400s by core.exceptions.api_exception_handler — this
    viewset does not duplicate that logic.
    """

    serializer_class = VehicleLoadItemSerializer
    permission_classes = [role_permission(*_OPERATIONS_ROLES)]

    def get_queryset(self):
        queryset = VehicleLoadItem.objects.filter(
            vehicle_load__depot__in=get_visible_depots(self.request.user)
        ).select_related("vehicle_load", "product")
        vehicle_load_id = self.request.query_params.get("vehicle_load")
        if vehicle_load_id:
            queryset = queryset.filter(vehicle_load_id=vehicle_load_id)
        return queryset


class VehicleReturnViewSet(OwnerReadOnlyViewSet):
    serializer_class = VehicleReturnSerializer
    permission_classes = [role_permission(*_OPERATIONS_ROLES)]

    def get_queryset(self):
        return (
            VehicleReturn.objects
            .filter(vehicle_load__depot__in=get_visible_depots(self.request.user))
            .select_related("vehicle_load")
            .prefetch_related("items")
            .order_by("-return_date", "-created_at")
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        vehicle_return = self.get_object()
        vehicle_return.confirm_return()
        return Response(VehicleReturnSerializer(vehicle_return).data)


class VehicleReturnItemViewSet(viewsets.ModelViewSet):
    """Filter by ?vehicle_return=<id>."""

    serializer_class = VehicleReturnItemSerializer
    permission_classes = [role_permission(*_OPERATIONS_ROLES)]

    def get_queryset(self):
        queryset = VehicleReturnItem.objects.filter(
            vehicle_return__vehicle_load__depot__in=get_visible_depots(self.request.user)
        ).select_related("vehicle_return", "product")
        vehicle_return_id = self.request.query_params.get("vehicle_return")
        if vehicle_return_id:
            queryset = queryset.filter(vehicle_return_id=vehicle_return_id)
        return queryset
