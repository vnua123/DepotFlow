from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .scoping import can_edit_promotion


class PromotionAccessRuleTests(SimpleTestCase):
    def test_company_wide_promotion_is_admin_only(self):
        promotion = Mock(depot_id=None)
        manager = Mock(is_staff=False, role="DEPOT_MANAGER")
        admin = Mock(is_staff=False, role="SUPER_ADMIN")

        with patch("inventory.scoping.is_unrestricted", side_effect=lambda user: user.role == "SUPER_ADMIN" or user.is_staff):
            self.assertFalse(can_edit_promotion(manager, promotion))
            self.assertTrue(can_edit_promotion(admin, promotion))

    def test_depot_promotion_requires_depot_access(self):
        promotion = Mock(depot_id=10, depot=Mock(pk=10))
        manager = Mock(is_staff=False, role="DEPOT_MANAGER")

        with patch("inventory.scoping.user_can_access_depot", return_value=True):
            self.assertTrue(can_edit_promotion(manager, promotion))
        with patch("inventory.scoping.user_can_access_depot", return_value=False):
            self.assertFalse(can_edit_promotion(manager, promotion))
