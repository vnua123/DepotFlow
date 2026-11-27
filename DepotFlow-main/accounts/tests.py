from django.test import TestCase
from django.core.exceptions import ValidationError
from django.urls import reverse

from core.models import AuditLog
from depots.models import Depot, Territory

from .forms import UserCreateForm
from .models import User
from .user_management import creatable_roles

R = User.Role
PASSWORD = "S0me-long-pass-123"


def make_user(username, role, depot=None, territory=None, **extra):
    return User.objects.create_user(
        username=username, password=PASSWORD, role=role,
        depot=depot, territory=territory, **extra,
    )


class UserCreationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north = Territory.objects.create(name="North")
        cls.south = Territory.objects.create(name="South")
        cls.d_north1 = Depot.objects.create(territory=cls.north, name="N1", code="N1")
        cls.d_north2 = Depot.objects.create(territory=cls.north, name="N2", code="N2")
        cls.d_south = Depot.objects.create(territory=cls.south, name="S1", code="S1")

        cls.admin = make_user("admin", R.SUPER_ADMIN)
        cls.tm = make_user("tm", R.TERRITORY_MANAGER, territory=cls.north)
        cls.dm = make_user("dm", R.DEPOT_MANAGER, depot=cls.d_north1)
        cls.officer = make_user("officer", R.DEPOT_OFFICER, depot=cls.d_north1)

    def data(self, **overrides):
        base = {
            "username": "newbie", "first_name": "New", "last_name": "User",
            "email": "", "phone": "", "role": R.VIEWER,
            "depot": self.d_north1.pk,
            "password1": PASSWORD, "password2": PASSWORD,
        }
        base.update(overrides)
        return base

    # --- hierarchy ---------------------------------------------------
    def test_role_matrix(self):
        self.assertEqual(
            set(creatable_roles(self.admin)),
            {R.TERRITORY_MANAGER, R.DEPOT_OWNER, R.DEPOT_MANAGER, R.DEPOT_OFFICER, R.FINANCE_OFFICER, R.VIEWER},
        )
        self.assertEqual(
            set(creatable_roles(self.tm)),
            {R.DEPOT_OWNER, R.DEPOT_MANAGER, R.DEPOT_OFFICER, R.FINANCE_OFFICER, R.VIEWER},
        )
        self.assertEqual(
            set(creatable_roles(self.dm)),
            {R.DEPOT_OFFICER, R.FINANCE_OFFICER, R.VIEWER},
        )
        self.assertEqual(creatable_roles(self.officer), ())

    def test_salesman_and_super_admin_never_creatable(self):
        for user in (self.admin, self.tm, self.dm):
            self.assertNotIn(R.SALESMAN, creatable_roles(user))
            self.assertNotIn(R.SUPER_ADMIN, creatable_roles(user))

    def test_manager_without_scope_cannot_create(self):
        lonely = make_user("lonely", R.DEPOT_MANAGER)
        self.assertEqual(creatable_roles(lonely), ())

    # --- form rules --------------------------------------------------
    def test_depot_manager_cannot_create_territory_manager_or_peer(self):
        for role in (R.TERRITORY_MANAGER, R.DEPOT_MANAGER, R.SUPER_ADMIN):
            form = UserCreateForm(self.data(role=role), creator=self.dm)
            self.assertFalse(form.is_valid(), role)
            self.assertIn("role", form.errors)

    def test_depot_manager_is_locked_to_own_depot(self):
        # Even if another depot's pk is posted, the disabled field uses own depot.
        form = UserCreateForm(self.data(depot=self.d_south.pk), creator=self.dm)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.depot, self.d_north1)
        self.assertEqual(user.territory, self.north)

    def test_territory_manager_limited_to_own_territory_depots(self):
        ok = UserCreateForm(self.data(role=R.DEPOT_MANAGER, depot=self.d_north2.pk), creator=self.tm)
        self.assertTrue(ok.is_valid(), ok.errors)

        bad = UserCreateForm(self.data(role=R.DEPOT_MANAGER, depot=self.d_south.pk), creator=self.tm)
        self.assertFalse(bad.is_valid())
        self.assertIn("depot", bad.errors)

    def test_depot_required_for_depot_roles(self):
        form = UserCreateForm(self.data(role=R.DEPOT_OFFICER, depot=""), creator=self.admin)
        self.assertFalse(form.is_valid())
        self.assertIn("depot", form.errors)

    def test_super_admin_creates_territory_manager_with_territory(self):
        form = UserCreateForm(
            self.data(role=R.TERRITORY_MANAGER, depot="", territory=self.south.pk),
            creator=self.admin,
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.territory, self.south)
        self.assertIsNone(user.depot)

        missing = UserCreateForm(
            self.data(username="tm2", role=R.TERRITORY_MANAGER, depot="", territory=""),
            creator=self.admin,
        )
        self.assertFalse(missing.is_valid())
        self.assertIn("territory", missing.errors)

    def test_password_rules(self):
        mismatch = UserCreateForm(self.data(password2="different"), creator=self.dm)
        self.assertFalse(mismatch.is_valid())
        self.assertIn("password2", mismatch.errors)

    def test_created_user_is_never_admin(self):
        form = UserCreateForm(
            self.data(is_staff="on", is_superuser="on"), creator=self.admin,
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))

    # --- view --------------------------------------------------------
    def test_view_blocks_roles_without_permission(self):
        self.client.force_login(self.officer)
        response = self.client.post(reverse("accounts:user_create"), self.data())
        self.assertRedirects(response, reverse("accounts:team_list"))
        self.assertFalse(User.objects.filter(username="newbie").exists())

    def test_view_creates_user_and_audits_actor(self):
        self.client.force_login(self.dm)
        response = self.client.post(reverse("accounts:user_create"), self.data())
        self.assertRedirects(response, reverse("accounts:team_list"))

        created = User.objects.get(username="newbie")
        self.assertEqual(created.role, R.VIEWER)

        # Requires the updated accounts/signals.py (creation is logged).
        entry = AuditLog.objects.filter(
            action=AuditLog.Action.PERMISSION_CHANGE, object_id=created.pk
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.user, self.dm)

    def test_team_page_shows_add_button_only_when_allowed(self):
        self.client.force_login(self.dm)
        self.assertContains(self.client.get(reverse("accounts:team_list")), "Add user")

        self.client.force_login(self.officer)
        self.assertNotContains(self.client.get(reverse("accounts:team_list")), "Add user")


class DepotAssignmentValidationTests(TestCase):
    def test_non_admin_user_requires_depot(self):
        user = User(username="missing-depot", role=User.Role.DEPOT_OFFICER)
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_super_admin_can_exist_without_depot(self):
        user = User(username="root-user", role=User.Role.SUPER_ADMIN)
        # Password is intentionally excluded: this test covers depot/territory
        # assignment validation, not password-field validation.
        user.full_clean(exclude=["password"])
