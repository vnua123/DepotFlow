from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, RequestFactory
from django.urls import reverse

from core.audit import log_action
from core.models import AuditLog
from depots.models import Depot, Territory
from accounts.models import User


class HomeViewTests(TestCase):
    def test_home_requires_authentication(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('home')}",
            fetch_redirect_response=False,
        )

    def test_authenticated_user_can_open_home(self):
        user = User.objects.create_user(username="home-user", password="test-pass-123")
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home.html")


class AuditLogServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="auditor", password="test-pass-123")
        territory = Territory.objects.create(name="Audit Territory")
        self.depot = Depot.objects.create(
            territory=territory, name="Audit Depot", code="AUDIT-01"
        )

    def test_log_action_records_actor_and_generic_object_reference(self):
        entry = log_action(
            AuditLog.Action.OTHER,
            obj=self.depot,
            user=self.user,
            old_value={"name": "Old Depot"},
            new_value={"name": "Audit Depot"},
            notes="Test audit entry",
        )

        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.action, AuditLog.Action.OTHER)
        self.assertEqual(entry.content_type, ContentType.objects.get_for_model(self.depot))
        self.assertEqual(entry.object_id, self.depot.pk)
        self.assertEqual(entry.content_object, self.depot)
        self.assertEqual(entry.object_repr, str(self.depot))
        self.assertEqual(entry.old_value, {"name": "Old Depot"})
        self.assertEqual(entry.new_value, {"name": "Audit Depot"})

    def test_log_action_captures_request_metadata_and_actor(self):
        request = RequestFactory().post("/audit-test/")
        request.META["HTTP_USER_AGENT"] = "DepotFlow test client"
        request.user = self.user

        entry = log_action(
            AuditLog.Action.OTHER,
            obj=self.depot,
            request=request,
        )

        self.assertEqual(entry.user, self.user)
        self.assertEqual(entry.ip_address, "127.0.0.1")
        self.assertEqual(entry.user_agent, "DepotFlow test client")
