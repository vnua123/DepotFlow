from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from core.permissions import role_permission
from core.scoping import is_unrestricted, user_can_access_depot
from .models import Product, Supplier, Promotion
from .serializers import (
    ProductSerializer, PriceHistorySerializer, PriceChangeSerializer,
    SupplierSerializer, PromotionSerializer,
)
from .scoping import visible_promotions, can_edit_promotion
from .services import record_price_change


class OwnerReadOnlyViewSet(viewsets.ModelViewSet):
    """Depot Owners can read inventory reference data, never mutate it."""
    def get_permissions(self):
        if getattr(self.request.user, "role", "") == "DEPOT_OWNER" and self.action in ("list", "retrieve", "price_history"):
            return [IsAuthenticated()]
        return super().get_permissions()


class ProductViewSet(OwnerReadOnlyViewSet):
    queryset = Product.objects.all().order_by("name")
    serializer_class = ProductSerializer
    permission_classes = [role_permission("SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER")]

    @action(detail=True, methods=["get"])
    def price_history(self, request, pk=None):
        product = self.get_object()
        history = product.price_history.all()[:50]
        return Response(PriceHistorySerializer(history, many=True).data)

    @action(
        detail=True,
        methods=["post"],
        permission_classes=[role_permission("SUPER_ADMIN", "DEPOT_MANAGER")],
    )
    def change_price(self, request, pk=None):
        product = self.get_object()
        serializer = PriceChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        price_history = record_price_change(
            product,
            selling_price=serializer.validated_data["selling_price"],
            cost_price=serializer.validated_data.get("cost_price"),
            user=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )

        return Response(PriceHistorySerializer(price_history).data, status=201)


class SupplierViewSet(OwnerReadOnlyViewSet):
    queryset = Supplier.objects.all().order_by("name")
    serializer_class = SupplierSerializer
    permission_classes = [role_permission("SUPER_ADMIN", "DEPOT_MANAGER", "DEPOT_OFFICER")]


class PromotionViewSet(OwnerReadOnlyViewSet):
    """
    Scoped like the HTML screens: company-wide promotions (no depot) are
    visible to everyone but only unrestricted users may change them;
    depot-specific ones are visible/editable only within the user's own
    depots.
    """

    serializer_class = PromotionSerializer
    permission_classes = [role_permission("SUPER_ADMIN", "DEPOT_MANAGER")]

    def get_queryset(self):
        return visible_promotions(self.request.user).order_by("-start_date")

    def _check_depot_allowed(self, depot):
        user = self.request.user
        if is_unrestricted(user):
            return
        if depot is None or not user_can_access_depot(user, depot):
            raise PermissionDenied("You can only create or edit promotions for your own depot.")

    def perform_create(self, serializer):
        self._check_depot_allowed(serializer.validated_data.get("depot"))
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        if not can_edit_promotion(self.request.user, serializer.instance):
            raise PermissionDenied("You cannot edit this promotion.")
        self._check_depot_allowed(serializer.validated_data.get("depot", serializer.instance.depot))
        serializer.save()

    def perform_destroy(self, instance):
        if not can_edit_promotion(self.request.user, instance):
            raise PermissionDenied("You cannot delete this promotion.")
        instance.delete()