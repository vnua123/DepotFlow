from rest_framework import viewsets

from core.permissions import role_permission
from core.scoping import get_visible_depots, get_visible_territories
from .models import Territory, Depot
from .serializers import TerritorySerializer, DepotSerializer


class TerritoryViewSet(viewsets.ModelViewSet):
    serializer_class = TerritorySerializer
    permission_classes = [role_permission("SUPER_ADMIN")]

    def get_queryset(self):
        return get_visible_territories(self.request.user).order_by("name")


class DepotViewSet(viewsets.ModelViewSet):
    serializer_class = DepotSerializer
    permission_classes = [role_permission("SUPER_ADMIN")]

    def get_queryset(self):
        return get_visible_depots(self.request.user).select_related("territory").order_by("name")