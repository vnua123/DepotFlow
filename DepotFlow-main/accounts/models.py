from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import AbstractUser
from depots.models import Depot, Territory


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
        TERRITORY_MANAGER = "TERRITORY_MANAGER", "Commercial Manager"
        DEPOT_OWNER = "DEPOT_OWNER", "Depot Owner"
        DEPOT_MANAGER = "DEPOT_MANAGER", "Distribution Manager"
        DEPOT_OFFICER = "DEPOT_OFFICER", "Depot Manager"
        SALESMAN = "SALESMAN", "Salesman"
        FINANCE_OFFICER = "FINANCE_OFFICER", "Finance Officer"
        VIEWER = "VIEWER", "Viewer"

    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.DEPOT_OFFICER
    )

    depot = models.ForeignKey(
        Depot,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    territory = models.ForeignKey(
        Territory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="users"
    )

    phone = models.CharField(
        max_length=20,
        blank=True
    )

    def __str__(self):
        return self.get_full_name() or self.username

    def clean(self):
        """
        Every non-admin user must be scoped to somewhere, otherwise
        core.scoping fails closed and they see nothing. Enforced in
        forms/admin (full_clean); create_user() and createsuperuser
        bypass this, which is fine because superusers are exempt.
        """
        super().clean()

        # Unrestricted accounts: scoping never applies to them.
        if self.role == self.Role.DEPOT_OWNER:
            # Depot Owners always require a depot assignment, even if an
            # account was accidentally granted Django staff/superuser flags.
            if not self.depot_id:
                raise ValidationError({"depot": "Depot Owners must be assigned a depot."})
            return

        if self.is_superuser or self.is_staff or self.role == self.Role.SUPER_ADMIN:
            return

        if self.role == self.Role.TERRITORY_MANAGER:
            if not self.territory_id:
                raise ValidationError({"territory": "Commercial Managers must be assigned a territory."})
        elif not self.depot_id:
            raise ValidationError({"depot": "This role must be assigned to a depot."})

    @property
    def is_super_admin(self):
        return self.role == self.Role.SUPER_ADMIN

    @property
    def is_territory_manager(self):
        return self.role == self.Role.TERRITORY_MANAGER

    @property
    def is_depot_owner(self):
        return self.role == self.Role.DEPOT_OWNER

    @property
    def is_depot_manager(self):
        return self.role == self.Role.DEPOT_MANAGER

    @property
    def is_depot_officer(self):
        return self.role == self.Role.DEPOT_OFFICER

    @property
    def is_salesman(self):
        return self.role == self.Role.SALESMAN

    @property
    def is_finance_officer(self):
        return self.role == self.Role.FINANCE_OFFICER

    @property
    def is_viewer(self):
        return self.role == self.Role.VIEWER