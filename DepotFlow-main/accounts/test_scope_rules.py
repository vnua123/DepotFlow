"""
Guards the User.clean() rule: every non-admin user must be scoped to a
depot (Commercial Manager: a territory). This rule once vanished when
accounts/models.py was overwritten from an older copy; the in-app Add User
form has its own copy of the check, so only a model-level test notices.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from depots.models import Depot, Territory

from .models import User

R = User.Role


class DepotRequiredRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=cls.north, name="N1", code="N1")

    def clean(self, **fields):
        User(username=fields.pop("username", "probe"), **fields).full_clean(exclude=["password"])

    def test_every_depot_scoped_role_requires_a_depot(self):
        for role in (R.DEPOT_MANAGER, R.DEPOT_OFFICER, R.SALESMAN, R.FINANCE_OFFICER, R.VIEWER):
            with self.subTest(role=role):
                with self.assertRaises(ValidationError) as ctx:
                    self.clean(role=role)
                self.assertIn("depot", ctx.exception.message_dict)

    def test_territory_manager_requires_a_territory(self):
        with self.assertRaises(ValidationError) as ctx:
            self.clean(role=R.TERRITORY_MANAGER)
        self.assertIn("territory", ctx.exception.message_dict)
        self.clean(role=R.TERRITORY_MANAGER, territory=self.north)  # accepted

    def test_roles_with_a_depot_are_accepted(self):
        for role in (R.DEPOT_MANAGER, R.DEPOT_OFFICER, R.VIEWER):
            with self.subTest(role=role):
                self.clean(username=f"ok-{role}", role=role, depot=self.depot)

    def test_unrestricted_accounts_need_no_scope(self):
        self.clean(role=R.SUPER_ADMIN)
        self.clean(role=R.VIEWER, is_staff=True)
        self.clean(role=R.VIEWER, is_superuser=True)
