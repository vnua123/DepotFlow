from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied

from .api import PromotionViewSet


class PromotionAPIScopeTests(SimpleTestCase):
    def setUp(self):
        self.view = PromotionViewSet()
        self.view.request = Mock()
        self.view.request.user = Mock(is_staff=False, role="DEPOT_MANAGER")
        self.depot = Mock(pk=10)

    def test_depot_specific_promotion_must_belong_to_user(self):
        with patch("inventory.api.user_can_access_depot", return_value=False):
            with self.assertRaises(PermissionDenied):
                self.view._check_depot_allowed(self.depot)

    def test_user_can_manage_promotion_in_own_depot(self):
        with patch("inventory.api.user_can_access_depot", return_value=True):
            self.view._check_depot_allowed(self.depot)

    def test_company_wide_promotion_is_super_admin_only(self):
        with self.assertRaises(PermissionDenied):
            self.view._check_depot_allowed(None)

    def test_super_admin_can_manage_company_wide_promotion(self):
        self.view.request.user.role = "SUPER_ADMIN"
        self.view._check_depot_allowed(None)

    def test_staff_can_manage_company_wide_promotion(self):
        self.view.request.user.is_staff = True
        self.view._check_depot_allowed(None)
