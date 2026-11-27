from django.core.exceptions import ValidationError
from django.test import TestCase

from depots.models import Depot, Territory
from .models import User


class DepotAssignmentValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.territory = Territory.objects.create(name="Test Territory")
        cls.depot = Depot.objects.create(territory=cls.territory, name="Test Depot", code="TD")

    def test_depot_scoped_role_requires_depot(self):
        user = User(username="unassigned", role=User.Role.DEPOT_MANAGER)
        with self.assertRaises(ValidationError):
            user.full_clean(exclude=["password"])

    def test_commercial_manager_requires_territory(self):
        user = User(username="unassigned_tm", role=User.Role.TERRITORY_MANAGER)
        with self.assertRaises(ValidationError):
            user.full_clean(exclude=["password"])

    def test_commercial_manager_can_have_territory_without_depot(self):
        user = User(username="assigned_tm", role=User.Role.TERRITORY_MANAGER, territory=self.territory)
        user.full_clean(exclude=["password"])

    def test_depot_owner_requires_depot(self):
        user = User(username="unassigned_owner", role=User.Role.DEPOT_OWNER)
        with self.assertRaises(ValidationError):
            user.full_clean(exclude=["password"])

    def test_super_admin_does_not_need_depot_or_territory(self):
        user = User(username="admin", role=User.Role.SUPER_ADMIN)
        user.full_clean(exclude=["password"])
