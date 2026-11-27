from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "Depot System",
            {
                "fields": (
                    "role",
                    "depot",
                    "territory",
                    "phone",
                )
            },
        ),
    )

    # The "Add user" page only asks for username/password by default.
    # Without these fields a new user is created with no depot, and
    # User.clean() would then reject the form.
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Depot System",
            {
                "classes": ("wide",),
                "fields": (
                    "role",
                    "depot",
                    "territory",
                    "phone",
                ),
            },
        ),
    )

    list_display = (
        "username",
        "first_name",
        "last_name",
        "role",
        "depot",
        "territory",
        "is_active",
    )

    list_filter = ("role", "depot", "territory", "is_active")

    def save_model(self, request, obj, form, change):
        # Lets accounts.signals record WHO made the change.
        obj._changed_by = request.user
        super().save_model(request, obj, form, change)
