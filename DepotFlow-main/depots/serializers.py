from rest_framework import serializers

from .models import Territory, Depot


class TerritorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Territory
        fields = ["id", "name"]


class DepotSerializer(serializers.ModelSerializer):
    territory_name = serializers.CharField(source="territory.name", read_only=True)

    class Meta:
        model = Depot
        fields = ["id", "territory", "territory_name", "name", "code", "address"]