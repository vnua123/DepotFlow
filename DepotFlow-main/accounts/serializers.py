from rest_framework import serializers

from .models import User


class ProfileSerializer(serializers.ModelSerializer):
    """
    Self-service profile fields only — mirrors accounts.forms.ProfileForm
    exactly. role/depot/territory/is_staff/is_superuser are deliberately
    read-only here; every permission-relevant change goes through Django
    admin only (see accounts.signals.log_user_permission_change), so
    there is exactly one auditable path for those fields.
    """

    depot_name = serializers.CharField(source="depot.name", read_only=True, default=None)
    territory_name = serializers.CharField(source="territory.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "email", "phone",
            "role", "depot", "depot_name", "territory", "territory_name",
        ]
        read_only_fields = ["id", "username", "role", "depot", "territory"]


class TeamMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "role", "phone"]
        read_only_fields = fields
