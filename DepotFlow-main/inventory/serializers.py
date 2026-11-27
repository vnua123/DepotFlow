from rest_framework import serializers

from .models import Product, PriceHistory, Supplier, Promotion
from .services import get_current_selling_price, get_current_cost_reference


class ProductSerializer(serializers.ModelSerializer):
    current_selling_price = serializers.SerializerMethodField()
    current_cost_reference = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "category", "package_type", "volume",
            "pack_size", "is_active",
            "current_selling_price", "current_cost_reference",
        ]
        read_only_fields = ["current_selling_price", "current_cost_reference"]

    def get_current_selling_price(self, obj):
        return get_current_selling_price(obj)

    def get_current_cost_reference(self, obj):
        return get_current_cost_reference(obj)


class PriceHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceHistory
        fields = ["id", "product", "cost_price", "selling_price", "effective_from", "changed_by", "reason"]
        read_only_fields = fields  # append-only, never editable via the API


class PriceChangeSerializer(serializers.Serializer):
    """
    Not a ModelSerializer — a price change must always go through
    inventory.services.record_price_change(), never a direct
    PriceHistory create, so this only validates input for that call.
    """

    selling_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    cost_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    reason = serializers.CharField(required=False, allow_blank=True)


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_person", "phone", "email", "address", "is_active"]


class PromotionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Promotion
        fields = [
            "id", "name", "level", "promotion_type", "description", "products",
            "supplier", "depot", "start_date", "end_date", "percentage_value",
            "fixed_value", "buy_quantity", "get_quantity", "minimum_quantity",
            "maximum_quantity", "is_active", "created_by",
        ]
        read_only_fields = ["created_by"]