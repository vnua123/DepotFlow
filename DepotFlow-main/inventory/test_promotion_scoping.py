"""
Promotions are depot-scoped: depot=None means company-wide, otherwise one
depot. Company-wide ones are visible to everyone but editable only by
unrestricted users; depot-specific ones only within the user's own depots.
(Before this was enforced, any depot's manager could list and edit every
other depot's promotions by ID.)
"""
import re
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from depots.models import Depot, Territory

from .models import Promotion

R = User.Role
PW = "S0me-long-pass-123"
P = Promotion


def mk(username, role, depot=None):
    return User.objects.create_user(username=username, password=PW, role=role, depot=depot)


def promo(name, depot=None):
    return P.objects.create(
        name=name, level=P.Level.DEPOT_TO_CUSTOMER, promotion_type=P.PromotionType.PERCENTAGE_DISCOUNT,
        percentage_value=Decimal("10"), start_date=date.today(), depot=depot,
    )


class PromotionScopingBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        t = Territory.objects.create(name="North")
        cls.a = Depot.objects.create(territory=t, name="A", code="A")
        cls.b = Depot.objects.create(territory=t, name="B", code="B")
        cls.admin = mk("admin", R.SUPER_ADMIN)
        cls.dm_a = mk("dm_a", R.DEPOT_MANAGER, cls.a)
        cls.viewer_a = mk("viewer_a", R.VIEWER, cls.a)
        cls.glob = promo("Company-wide")
        cls.pa = promo("Depot A deal", cls.a)
        cls.pb = promo("Depot B deal", cls.b)

    def form_data(self, name, depot):
        return {"name": name, "level": P.Level.DEPOT_TO_CUSTOMER,
                "promotion_type": P.PromotionType.PERCENTAGE_DISCOUNT, "percentage_value": "10",
                "start_date": date.today().isoformat(), "depot": depot, "is_active": "on"}


class PromotionScreenTests(PromotionScopingBase):
    def listed(self, user):
        self.client.force_login(user)
        return {p.pk for p in self.client.get(reverse("inventory:promotion_list")).context["promotions"]}

    def test_depot_user_sees_company_wide_and_own_depot_only(self):
        self.assertEqual(self.listed(self.dm_a), {self.glob.pk, self.pa.pk})
        self.assertEqual(self.listed(self.viewer_a), {self.glob.pk, self.pa.pk})

    def test_super_admin_sees_everything(self):
        self.assertEqual(self.listed(self.admin), {self.glob.pk, self.pa.pk, self.pb.pk})

    def test_cannot_open_or_edit_another_depots_promotion(self):
        self.client.force_login(self.dm_a)
        url = reverse("inventory:promotion_update", args=[self.pb.pk])
        self.assertRedirects(self.client.get(url), reverse("inventory:promotion_list"))
        self.client.post(url, self.form_data("HACKED", self.b.pk))
        self.pb.refresh_from_db()
        self.assertEqual(self.pb.name, "Depot B deal")

    def test_can_edit_own_depots_promotion(self):
        self.client.force_login(self.dm_a)
        resp = self.client.post(reverse("inventory:promotion_update", args=[self.pa.pk]),
                                self.form_data("Renamed", self.a.pk))
        self.assertRedirects(resp, reverse("inventory:promotion_list"))
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.name, "Renamed")

    def test_depot_manager_cannot_edit_a_company_wide_promotion(self):
        self.client.force_login(self.dm_a)
        url = reverse("inventory:promotion_update", args=[self.glob.pk])
        self.assertRedirects(self.client.get(url), reverse("inventory:promotion_list"))
        self.client.post(url, self.form_data("HACKED", self.a.pk))
        self.glob.refresh_from_db()
        self.assertEqual(self.glob.name, "Company-wide")

    def test_super_admin_can_edit_a_company_wide_promotion(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("inventory:promotion_update", args=[self.glob.pk]),
                         self.form_data("Renamed global", ""))
        self.glob.refresh_from_db()
        self.assertEqual(self.glob.name, "Renamed global")

    def test_depot_manager_cannot_create_company_wide_or_other_depot_promotions(self):
        self.client.force_login(self.dm_a)
        before = P.objects.count()
        self.client.post(reverse("inventory:promotion_create"), self.form_data("Sneaky global", ""))
        self.client.post(reverse("inventory:promotion_create"), self.form_data("Sneaky B", self.b.pk))
        self.assertEqual(P.objects.count(), before)

    def test_depot_manager_creates_promotion_for_own_depot(self):
        self.client.force_login(self.dm_a)
        self.client.post(reverse("inventory:promotion_create"), self.form_data("Mine", self.a.pk))
        made = P.objects.get(name="Mine")
        self.assertEqual(made.depot, self.a)
        self.assertEqual(made.created_by, self.dm_a)

    def test_promotion_pages_still_render(self):
        for user in (self.dm_a, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("inventory:promotion_create")).status_code, 200)
        self.client.force_login(self.dm_a)
        self.assertEqual(self.client.get(reverse("inventory:promotion_update", args=[self.pa.pk])).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("inventory:promotion_update", args=[self.glob.pk])).status_code, 200)

    def test_single_depot_manager_gets_hidden_depot_not_a_dropdown(self):
        self.client.force_login(self.dm_a)
        html = self.client.get(reverse("inventory:promotion_create")).content.decode()
        tag = re.search(r'<input[^>]*name="depot"[^>]*>', html)
        self.assertIsNotNone(tag, "depot field should render as a hidden input")
        self.assertIn('type="hidden"', tag.group(0))
        self.assertNotIn("<select", re.search(r'<[^>]*name="depot"[^>]*>', html).group(0))

    def test_super_admin_still_gets_a_depot_dropdown(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("inventory:promotion_create")).content.decode()
        self.assertRegex(html, r'<select[^>]*name="depot"')


class PromotionApiTests(PromotionScopingBase):
    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_list_is_scoped(self):
        ids = {r["id"] for r in self.api(self.dm_a).get("/api/v1/promotions/").json()["results"]}
        self.assertEqual(ids, {self.glob.pk, self.pa.pk})

    def test_other_depots_promotion_is_invisible(self):
        self.assertEqual(self.api(self.dm_a).get(f"/api/v1/promotions/{self.pb.pk}/").status_code, 404)

    def test_cannot_edit_company_wide_or_delete_it(self):
        c = self.api(self.dm_a)
        self.assertEqual(c.patch(f"/api/v1/promotions/{self.glob.pk}/", {"name": "x"}, format="json").status_code, 403)
        self.assertEqual(c.delete(f"/api/v1/promotions/{self.glob.pk}/").status_code, 403)
        self.assertTrue(P.objects.filter(pk=self.glob.pk).exists())

    def test_cannot_create_for_another_depot_or_company_wide(self):
        c = self.api(self.dm_a)
        body = {"name": "n", "level": P.Level.DEPOT_TO_CUSTOMER, "promotion_type": P.PromotionType.PERCENTAGE_DISCOUNT,
                "percentage_value": "10", "start_date": date.today().isoformat()}
        self.assertEqual(c.post("/api/v1/promotions/", {**body, "depot": self.b.pk}, format="json").status_code, 403)
        self.assertEqual(c.post("/api/v1/promotions/", body, format="json").status_code, 403)

    def test_can_create_edit_and_delete_for_own_depot(self):
        c = self.api(self.dm_a)
        body = {"name": "Mine", "level": P.Level.DEPOT_TO_CUSTOMER, "promotion_type": P.PromotionType.PERCENTAGE_DISCOUNT,
                "percentage_value": "10", "start_date": date.today().isoformat(), "depot": self.a.pk}
        made = c.post("/api/v1/promotions/", body, format="json")
        self.assertEqual(made.status_code, 201, made.content)
        pk = made.json()["id"]
        self.assertEqual(c.patch(f"/api/v1/promotions/{pk}/", {"name": "Mine2"}, format="json").status_code, 200)
        self.assertEqual(c.delete(f"/api/v1/promotions/{pk}/").status_code, 204)

    def test_cannot_move_own_promotion_to_another_depot(self):
        resp = self.api(self.dm_a).patch(f"/api/v1/promotions/{self.pa.pk}/", {"depot": self.b.pk}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.pa.refresh_from_db()
        self.assertEqual(self.pa.depot, self.a)

    def test_super_admin_can_edit_company_wide(self):
        resp = self.api(self.admin).patch(f"/api/v1/promotions/{self.glob.pk}/", {"name": "Global2"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_viewer_cannot_write(self):
        resp = self.api(self.viewer_a).patch(f"/api/v1/promotions/{self.pa.pk}/", {"name": "x"}, format="json")
        self.assertEqual(resp.status_code, 403)
