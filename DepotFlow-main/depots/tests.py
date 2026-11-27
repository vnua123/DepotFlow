from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .models import Depot, Territory


class CommercialManagerDepotPermissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.north = Territory.objects.create(name="North")
        cls.south = Territory.objects.create(name="South")
        cls.north_depot = Depot.objects.create(territory=cls.north, name="North Depot", code="NORTH")
        cls.south_depot = Depot.objects.create(territory=cls.south, name="South Depot", code="SOUTH")
        cls.manager = User.objects.create_user(
            username="commercial", password="test-pass-123", role=User.Role.TERRITORY_MANAGER,
            territory=cls.north,
        )

    def setUp(self):
        self.client.force_login(self.manager)

    def test_commercial_manager_can_open_create_depot_page(self):
        response = self.client.get(reverse("depots:depot_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "New Depot")

    def test_commercial_manager_can_create_depot_in_own_territory(self):
        response = self.client.post(reverse("depots:depot_create"), {
            "territory": self.north.pk, "name": "North New", "code": "NORTH2", "address": "",
        })
        self.assertEqual(response.status_code, 302)
        depot = Depot.objects.get(code="NORTH2")
        self.assertEqual(depot.territory, self.north)

    def test_commercial_manager_cannot_create_depot_in_another_territory(self):
        response = self.client.post(reverse("depots:depot_create"), {
            "territory": self.south.pk, "name": "South New", "code": "SOUTH2", "address": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Depot.objects.filter(code="SOUTH2").exists())

    def test_commercial_manager_can_edit_depot_in_own_territory(self):
        response = self.client.post(reverse("depots:depot_update", args=[self.north_depot.pk]), {
            "territory": self.north.pk, "name": "North Depot Updated", "code": "NORTH", "address": "",
        })
        self.assertEqual(response.status_code, 302)
        self.north_depot.refresh_from_db()
        self.assertEqual(self.north_depot.name, "North Depot Updated")

    def test_commercial_manager_cannot_edit_depot_outside_own_territory(self):
        response = self.client.get(reverse("depots:depot_update", args=[self.south_depot.pk]))
        self.assertEqual(response.status_code, 404)

    def test_commercial_manager_cannot_create_or_edit_territories(self):
        create_response = self.client.get(reverse("depots:territory_create"))
        edit_response = self.client.get(reverse("depots:territory_update", args=[self.north.pk]))
        self.assertEqual(create_response.status_code, 302)
        self.assertEqual(edit_response.status_code, 302)

    def test_depot_list_shows_create_button_but_not_territory_management(self):
        response = self.client.get(reverse("depots:depot_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("depots:depot_create"))
        self.assertNotContains(response, reverse("depots:territory_list"))
