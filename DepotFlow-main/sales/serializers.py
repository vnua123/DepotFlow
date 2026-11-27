from rest_framework import serializers

from .models import Customer, Sale, SaleItem


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "name", "outlet_type", "depot", "phone", "address", "is_active"]


class SaleItemSerializer(serializers.ModelSerializer):
    """
    unit_cost/unit_price/discount_applied are the FROZEN snapshot of
    what was actually charged/cost at the moment of sale — set by
    SaleItem.save(), never submitted by the client.
    """

    line_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_profit = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            "id", "sale", "product", "quantity",
            "unit_cost", "unit_price", "discount_applied", "promotion",
            "line_revenue", "line_cost", "line_profit",
        ]
        read_only_fields = ["unit_cost", "unit_price", "discount_applied"]


class SaleSerializer(serializers.ModelSerializer):
    """
    salesman is deliberately read-only — Sale.save() auto-fills it
    from vehicle_load.salesman (mirrors sales.forms.SaleForm, which
    excludes it from the form for the same reason). sale_number is
    auto-generated in Sale.save().
    """

    items = SaleItemSerializer(many=True, read_only=True)
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_cost = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_profit = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Sale
        fields = [
            "id", "vehicle_load", "salesman", "customer", "sale_number", "sale_date",
            "is_finalized", "finalized_at", "notes", "items",
            "total_revenue", "total_cost", "total_profit",
        ]
        read_only_fields = ["salesman", "sale_number", "is_finalized", "finalized_at"]
