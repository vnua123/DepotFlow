from rest_framework import serializers

from .models import (
    Vehicle, VehicleSalesman, VehicleLoad, VehicleLoadItem,
    VehicleReturn, VehicleReturnItem,
)


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ["id", "depot", "registration_number", "vehicle_name", "capacity", "is_active"]


class VehicleSalesmanSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleSalesman
        fields = ["id", "name", "employee_id", "phone", "depot", "vehicle", "is_active"]


class VehicleLoadItemSerializer(serializers.ModelSerializer):
    """
    cost_price/selling_price are the point-in-time snapshot taken at
    load time (audit only) — set by VehicleLoadItem.save(), never
    submitted by the client. effective_*/expected_* are the live
    figures (current PriceHistory / current acquisition cost) and
    are always read-only, computed properties.
    """

    effective_cost_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    effective_selling_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    expected_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    expected_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    expected_profit = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = VehicleLoadItem
        fields = [
            "id", "vehicle_load", "product", "quantity",
            "cost_price", "selling_price", "promo_discount",
            "effective_cost_price", "effective_selling_price",
            "expected_revenue", "expected_cost", "expected_profit",
        ]
        read_only_fields = ["cost_price", "selling_price"]


class VehicleLoadSerializer(serializers.ModelSerializer):
    items = VehicleLoadItemSerializer(many=True, read_only=True)

    class Meta:
        model = VehicleLoad
        fields = [
            "id", "salesman", "vehicle", "depot", "load_number", "load_date",
            "is_closed", "closed_at", "notes", "items",
        ]
        read_only_fields = ["is_closed", "closed_at", "load_number"]


class VehicleReturnItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleReturnItem
        fields = ["id", "vehicle_return", "product", "quantity", "condition", "notes"]


class VehicleReturnSerializer(serializers.ModelSerializer):
    items = VehicleReturnItemSerializer(many=True, read_only=True)

    class Meta:
        model = VehicleReturn
        fields = [
            "id", "vehicle_load", "return_number", "return_date", "notes",
            "is_confirmed", "confirmed_at", "items",
        ]
        read_only_fields = ["is_confirmed", "confirmed_at", "return_number"]
