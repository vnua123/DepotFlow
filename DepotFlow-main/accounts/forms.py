from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from core.scoping import (
    get_default_depot,
    get_visible_depots,
    get_visible_territories,
    is_unrestricted,
)

from .models import User
from .user_management import creatable_roles


class ProfileForm(forms.ModelForm):
    """
    Self-service profile editing. Deliberately excludes role, depot,
    territory, is_active, is_staff, is_superuser — those are
    assigned by an administrator through Django admin only, so every
    permission-relevant change goes through one auditable path (see
    accounts.signals.log_user_permission_change).
    """

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone"]


class UserCreateForm(forms.ModelForm):
    """
    Create a user from inside the app. What the creator may pick is
    limited by accounts.user_management.creatable_roles() and by
    core.scoping (only depots/territories they can already see).

    is_staff / is_superuser / is_active are never on this form, so a
    user made here is always an ordinary, active, non-admin account.
    """

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = [
            "username", "first_name", "last_name", "email", "phone",
            "role", "depot", "territory",
        ]

    def __init__(self, *args, creator, **kwargs):
        super().__init__(*args, **kwargs)
        self.creator = creator
        self._allowed_roles = creatable_roles(creator)

        self.fields["role"].choices = [
            (value, label) for value, label in User.Role.choices
            if value in self._allowed_roles
        ]

        depots = get_visible_depots(creator)
        self.fields["depot"].queryset = depots
        self.fields["depot"].help_text = "Required for every role except Territory Manager."

        # Non-admin creators can only ever add to their own depot, so
        # lock the field. A disabled field ignores whatever is posted
        # and always uses the initial value.
        if not is_unrestricted(creator):
            default_depot = get_default_depot(creator)
            if default_depot is not None:
                self.fields["depot"].initial = default_depot.pk
                self.fields["depot"].disabled = True

        # Only admins can create Territory Managers, so only they need
        # the territory field.
        if User.Role.TERRITORY_MANAGER in self._allowed_roles:
            self.fields["territory"].queryset = get_visible_territories(creator)
            self.fields["territory"].help_text = "Only used for Territory Managers."
        else:
            del self.fields["territory"]

    def clean(self):
        cleaned = super().clean()

        role = cleaned.get("role")
        depot = cleaned.get("depot")
        territory = cleaned.get("territory")

        if role and role not in self._allowed_roles:
            self.add_error("role", "You are not allowed to create users with that role.")
        elif role == User.Role.TERRITORY_MANAGER:
            if not territory:
                self.add_error("territory", "Choose a territory for a Territory Manager.")
            cleaned["depot"] = None
        elif role:
            if not depot:
                self.add_error("depot", "Choose a depot for this role.")

        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2:
            if password1 != password2:
                self.add_error("password2", "Passwords do not match.")
            else:
                candidate = User(
                    username=cleaned.get("username", ""),
                    first_name=cleaned.get("first_name", ""),
                    last_name=cleaned.get("last_name", ""),
                    email=cleaned.get("email", ""),
                )
                try:
                    validate_password(password1, user=candidate)
                except DjangoValidationError as exc:
                    self.add_error("password1", exc)

        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        user.is_staff = False
        user.is_superuser = False

        if user.role == User.Role.TERRITORY_MANAGER:
            user.depot = None
        elif user.depot_id:
            # Keeps the territory-level Team page accurate for Territory Managers.
            user.territory = user.depot.territory

        # Read by accounts.signals so the audit entry records who did it.
        user._changed_by = self.creator

        if commit:
            user.save()
        return user
