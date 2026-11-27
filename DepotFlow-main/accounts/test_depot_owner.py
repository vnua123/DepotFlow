"""
Depot Owner role + the depot/territory-required rule on the User model.

The model-level rule (User.clean) is what protects Django Admin and any
other full_clean() path; the in-app UserCreateForm has its own copy of
the rule, so these tests hit the model directly to guard against the
model rule silently going missing again.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from depots.models import Depot, Territory

from .forms import UserCreateForm
from .context_processors import nav_visibility
from .models import User
from .user_management import creatable_roles

R = User.Role
PASSWORD = "S0me-long-pass-123"


def make_user(username, role, depot=None, territory=None, **extra):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=role,
        depot=depot, territory=territory, **extra,
    )


class DepotRequiredRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north = Territory.objects.create(name="North")
        cls.depot = Depot.objects.create(territory=cls.north, name="N1", code="N1")

    def clean(self, **fields):
        User(username=fields.pop("username", "probe"), **fields).full_clean(exclude=["password"])

    def test_every_depot_scoped_role_requires_a_depot(self):
        for role in (R.DEPOT_OWNER, R.DEPOT_MANAGER, R.DEPOT_OFFICER,
                     R.SALESMAN, R.FINANCE_OFFICER, R.VIEWER):
            with self.subTest(role=role):
                with self.assertRaises(ValidationError) as ctx:
                    self.clean(role=role)
                self.assertIn("depot", ctx.exception.message_dict)

    def test_territory_manager_requires_a_territory_not_a_depot(self):
        with self.assertRaises(ValidationError) as ctx:
            self.clean(role=R.TERRITORY_MANAGER)
        self.assertIn("territory", ctx.exception.message_dict)

        self.clean(role=R.TERRITORY_MANAGER, territory=self.north)  # no error

    def test_roles_with_a_depot_are_accepted(self):
        for role in (R.DEPOT_OWNER, R.DEPOT_MANAGER, R.VIEWER):
            with self.subTest(role=role):
                self.clean(username=f"ok-{role}", role=role, depot=self.depot)

    def test_unrestricted_accounts_need_no_scope(self):
        self.clean(role=R.SUPER_ADMIN)
        self.clean(role=R.VIEWER, is_staff=True)
        self.clean(role=R.VIEWER, is_superuser=True)


class DepotOwnerRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north = Territory.objects.create(name="North")
        cls.south = Territory.objects.create(name="South")
        cls.east = Territory.objects.create(name="East")
        cls.d_north = Depot.objects.create(territory=cls.north, name="N1", code="N1")
        cls.d_north2 = Depot.objects.create(territory=cls.north, name="N2", code="N2")
        cls.d_south = Depot.objects.create(territory=cls.south, name="S1", code="S1")
        cls.d_east = Depot.objects.create(territory=cls.east, name="E1", code="E1")

        cls.admin = make_user("admin", R.SUPER_ADMIN)
        cls.tm = make_user("tm", R.TERRITORY_MANAGER, territory=cls.north)
        cls.tm_east = make_user("tm_east", R.TERRITORY_MANAGER, territory=cls.east)
        cls.dm = make_user("dm_nav", R.DEPOT_MANAGER, depot=cls.d_north)
        cls.owner = make_user("owner", R.DEPOT_OWNER, depot=cls.d_north)

    def data(self, **overrides):
        base = {
            "username": "newowner", "first_name": "New", "last_name": "Owner",
            "email": "", "phone": "", "role": R.DEPOT_OWNER,
            "depot": self.d_north.pk, "password1": PASSWORD, "password2": PASSWORD,
        }
        base.update(overrides)
        return base

    def test_label_and_property(self):
        self.assertEqual(R.DEPOT_OWNER.label, "Depot Owner")
        self.assertTrue(self.owner.is_depot_owner)
        self.assertFalse(self.tm.is_depot_owner)


    def test_owner_navigation_hides_depots_but_shows_read_sections(self):
        request = type("Request", (), {"user": self.owner})()
        nav = nav_visibility(request)
        self.assertFalse(nav["nav_show_depots"])
        self.assertTrue(nav["nav_show_inventory"])
        self.assertTrue(nav["nav_show_operations"])
        self.assertTrue(nav["nav_show_sales"])
        self.assertTrue(nav["nav_show_finance_full"])
        self.assertFalse(nav["nav_show_team"])

    def test_commercial_manager_sees_depots_but_not_territory_management(self):
        request = type("Request", (), {"user": self.tm})()
        nav = nav_visibility(request)
        self.assertTrue(nav["nav_show_depots"])
        self.assertFalse(nav["nav_manage_territories"])

        # The role restriction still wins if a Commercial Manager is
        # accidentally marked as Django staff.
        self.tm.is_staff = True
        nav_staff_flagged = nav_visibility(request)
        self.assertFalse(nav_staff_flagged["nav_manage_territories"])

    def test_distribution_manager_keeps_nbc_rebate_navigation(self):
        request = type("Request", (), {"user": self.dm})()
        nav = nav_visibility(request)
        self.assertTrue(nav["nav_show_finance_full"])
        self.assertTrue(nav["nav_show_nbc_rebates"])

    def test_owner_cannot_open_team_page(self):
        from django.urls import reverse

        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:team_list"))
        self.assertEqual(response.status_code, 403)

    def test_owner_creates_nobody(self):
        self.assertEqual(creatable_roles(self.owner), ())

    def test_super_admin_can_create_an_owner(self):
        form = UserCreateForm(self.data(), creator=self.admin)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().role, R.DEPOT_OWNER)

    def test_commercial_manager_can_create_an_owner_in_own_territory_only(self):
        # North has two depots, so this is a real choice - and it's honoured.
        ok = UserCreateForm(self.data(depot=self.d_north2.pk), creator=self.tm)
        self.assertTrue(ok.is_valid(), ok.errors)

        # A depot from another territory is rejected outright.
        other_territory = UserCreateForm(self.data(username="x2", depot=self.d_south.pk), creator=self.tm)
        self.assertFalse(other_territory.is_valid())
        self.assertIn("depot", other_territory.errors)

    def test_single_depot_territory_locks_the_owner_to_that_depot(self):
        # East has exactly one depot, so there is no choice to make: the
        # form locks to it and ignores whatever depot was posted. Nothing
        # can leak into another territory this way.
        form = UserCreateForm(self.data(username="x3", depot=self.d_south.pk), creator=self.tm_east)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().depot, self.d_east)

    def test_owner_cannot_be_created_without_a_depot(self):
        form = UserCreateForm(self.data(depot=""), creator=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn("depot", form.errors)


class DepotOwnerPermissionPrecedenceTests(TestCase):
    """The Depot Owner role remains limited even if is_staff was set by mistake."""

    @classmethod
    def setUpTestData(cls):
        territory = Territory.objects.create(name="Owner territory")
        cls.depot = Depot.objects.create(territory=territory, name="Owner depot", code="OWN")
        cls.owner = make_user(
            "staff_flagged_owner", R.DEPOT_OWNER, depot=cls.depot, is_staff=True,
        )

    def test_owner_role_overrides_staff_flag_in_navigation_and_scoping(self):
        from core.scoping import get_visible_depots, is_unrestricted

        request = type("Request", (), {"user": self.owner})()
        nav = nav_visibility(request)

        self.assertTrue(nav["nav_is_depot_owner"])
        self.assertFalse(nav["nav_show_depots"])
        self.assertFalse(nav["nav_show_nbc_rebates"])
        self.assertFalse(nav["nav_show_team"])
        self.assertFalse(nav["nav_full_workflow"])
        self.assertEqual(list(get_visible_depots(self.owner)), [self.depot])
        self.assertFalse(is_unrestricted(self.owner))

    def test_owner_is_read_only_in_inventory_operations_and_sales(self):
        from inventory.views import _can_manage_inventory, _can_manage_pricing
        from operations.views import _can_manage_operations, _can_set_targets
        from sales.views import _can_manage_sales

        self.assertFalse(_can_manage_inventory(self.owner))
        self.assertFalse(_can_manage_pricing(self.owner))
        self.assertFalse(_can_manage_operations(self.owner))
        self.assertFalse(_can_set_targets(self.owner))
        self.assertFalse(_can_manage_sales(self.owner))

    def test_owner_can_manage_expenses_and_supplier_payments_but_not_rebates(self):
        from finance.views import _can_record_expenses, _can_approve_finance, _can_manage_rebates

        self.assertTrue(_can_record_expenses(self.owner))
        self.assertTrue(_can_approve_finance(self.owner))
        self.assertFalse(_can_manage_rebates(self.owner))

    def test_owner_role_prevents_staff_bypass_in_api_write_permissions(self):
        from types import SimpleNamespace
        from core.permissions import role_permission

        request = SimpleNamespace(user=self.owner, method="POST")
        rebate_permission = role_permission("SUPER_ADMIN", "DEPOT_MANAGER", "FINANCE_OFFICER")()
        payment_permission = role_permission("SUPER_ADMIN", "DEPOT_OWNER", "DEPOT_MANAGER")()

        self.assertFalse(rebate_permission.has_permission(request, None))
        self.assertTrue(payment_permission.has_permission(request, None))
