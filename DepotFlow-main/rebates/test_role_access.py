from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from depots.models import Depot, Territory


class DepotOwnerRebateAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        territory = Territory.objects.create(name="Restricted territory")
        depot = Depot.objects.create(territory=territory, name="Restricted depot", code="RBD")
        cls.owner = User.objects.create_user(
            username="staff_owner", password="Strong-password-123",
            role=User.Role.DEPOT_OWNER, depot=depot, is_staff=True,
        )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_staff_flagged_depot_owner_cannot_view_rebate_dashboard(self):
        response = self.client.get(reverse("rebates:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_staff_flagged_depot_owner_cannot_submit_health_check(self):
        response = self.client.get(reverse("rebates:health_check_create"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("rebates:dashboard"))

    def test_staff_flagged_depot_owner_cannot_manage_profitability(self):
        response = self.client.get(reverse("rebates:profitability_update"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("rebates:dashboard"))
