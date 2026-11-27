from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from core.permissions import role_permission
from core.scoping import get_visible_depots
from .models import Customer, Sale, SaleItem
from .serializers import CustomerSerializer, SaleSerializer, SaleItemSerializer

# Matches sales.views._can_manage_sales.
_SALES_ROLES = ("SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER", "SALESMAN")


class OwnerReadOnlyViewSet(viewsets.ModelViewSet):
    """Depot Owners may read their own depot data but cannot mutate it."""
    def get_permissions(self):
        if getattr(self.request.user, "role", "") == "DEPOT_OWNER" and self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return super().get_permissions()


class CustomerViewSet(OwnerReadOnlyViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [role_permission(*_SALES_ROLES)]

    def get_queryset(self):
        return Customer.objects.filter(
            depot__in=get_visible_depots(self.request.user)
        ).select_related("depot").order_by("name")


class SaleViewSet(OwnerReadOnlyViewSet):
    serializer_class = SaleSerializer
    permission_classes = [role_permission(*_SALES_ROLES)]

    def get_queryset(self):
        return (
            Sale.objects
            .filter(vehicle_load__depot__in=get_visible_depots(self.request.user))
            .select_related("vehicle_load", "salesman", "customer")
            .prefetch_related("items")
            .order_by("-sale_date", "-created_at")
        )

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        sale = self.get_object()
        sale.finalize()
        return Response(SaleSerializer(sale).data)


class SaleItemViewSet(OwnerReadOnlyViewSet):
    """
    Add/remove line items on a not-yet-finalized sale. Filter by
    ?sale=<id>. Load-reconciliation (sold + returned <= loaded) and
    the finalized-sale lock live in SaleItem.clean()/save() and are
    surfaced as normal 400s by core.exceptions.api_exception_handler.
    """

    serializer_class = SaleItemSerializer
    permission_classes = [role_permission(*_SALES_ROLES)]

    def get_queryset(self):
        queryset = SaleItem.objects.filter(
            sale__vehicle_load__depot__in=get_visible_depots(self.request.user)
        ).select_related("sale", "product", "promotion")
        sale_id = self.request.query_params.get("sale")
        if sale_id:
            queryset = queryset.filter(sale_id=sale_id)
        return queryset
