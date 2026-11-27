from decimal import Decimal
from unittest import TestCase
from types import SimpleNamespace

from rebates import scheme as s
from inventory.landing_cost import (
    landing_cost_breakdown, parse_bottles_per_case, parse_litres,
)


class PlacementTests(TestCase):
    def test_boundaries(self):
        self.assertEqual(s.placement_for_cases(12000), s.STANDARD)
        self.assertEqual(s.placement_for_cases(12001), s.MAXI)
        self.assertEqual(s.placement_for_cases(40000), s.MAXI)
        self.assertEqual(s.placement_for_cases(40001), s.MEGA)


class RateTests(TestCase):
    def test_standard_sparkling(self):
        r = lambda c: s.get_rate(s.STANDARD, s.SPARKLING, c)
        self.assertEqual(r(0), Decimal("7.5"))
        self.assertEqual(r(2099), Decimal("7.5"))
        self.assertEqual(r(2100), Decimal("8.0"))
        self.assertEqual(r(2700), Decimal("8.0"))
        self.assertEqual(r(2701), Decimal("8.5"))

    def test_other_cells_from_the_table(self):
        self.assertEqual(s.get_rate(s.MAXI, s.WATER, 651), Decimal("9.0"))
        self.assertEqual(s.get_rate(s.MAXI, s.WATER, 1801), Decimal("9.5"))
        self.assertEqual(s.get_rate(s.MEGA, s.WATER, 9001), Decimal("10.0"))
        self.assertEqual(s.get_rate(s.MEGA, s.PREDATOR, 31001), Decimal("6.0"))
        self.assertEqual(s.get_rate(s.MEGA, s.MONSTER, 33), Decimal("4.0"))
        self.assertEqual(s.get_rate(s.MEGA, s.MONSTER, 34), Decimal("4.5"))
        self.assertEqual(s.get_rate(s.STANDARD, s.JUICE, 121), Decimal("6.5"))
        # Decimal case counts (as summed from the database) work too.
        self.assertEqual(s.get_rate(s.STANDARD, s.MONSTER, Decimal("8")), Decimal("3.5"))

    def test_every_tier_has_every_category(self):
        for tier in (s.STANDARD, s.MAXI, s.MEGA):
            for category in s.CATEGORY_ORDER:
                self.assertIn(category, s.SCHEME[tier])


class CompleteRateTableTests(TestCase):
    """Boundary checks for every category/tier row transcribed from NBC's image."""

    def test_all_rate_steps_and_boundaries(self):
        cases = {
            s.STANDARD: {
                s.SPARKLING: [(0, "7.5"), (2099, "7.5"), (2100, "8.0"), (2700, "8.0"), (2701, "8.5")],
                s.WATER: [(0, "8.0"), (399, "8.0"), (400, "8.5"), (650, "8.5"), (651, "9.0")],
                s.JUICE: [(0, "5.5"), (69, "5.5"), (70, "6.0"), (120, "6.0"), (121, "6.5")],
                s.MONSTER: [(0, "3.0"), (7, "3.0"), (8, "3.5"), (13, "3.5"), (14, "4.0")],
                s.PREDATOR: [(0, "4.0"), (1049, "4.0"), (1050, "4.5"), (1350, "4.5"), (1351, "5.0")],
            },
            s.MAXI: {
                s.SPARKLING: [(0, "8.0"), (2700, "8.0"), (2701, "8.5"), (10500, "8.5"), (10501, "9.0")],
                s.WATER: [(0, "8.5"), (650, "8.5"), (651, "9.0"), (1800, "9.0"), (1801, "9.5")],
                s.JUICE: [(0, "6.0"), (120, "6.0"), (121, "6.5"), (480, "6.5"), (481, "7.0")],
                s.MONSTER: [(0, "3.5"), (13, "3.5"), (14, "4.0"), (33, "4.0"), (34, "4.5")],
                s.PREDATOR: [(0, "4.5"), (1350, "4.5"), (1351, "5.0"), (5250, "5.0"), (5251, "5.5")],
            },
            s.MEGA: {
                s.SPARKLING: [(0, "8.5"), (10500, "8.5"), (10501, "9.0"), (62000, "9.0"), (62001, "9.5")],
                s.WATER: [(0, "9.0"), (1800, "9.0"), (1801, "9.5"), (9000, "9.5"), (9001, "10.0")],
                s.JUICE: [(0, "6.5"), (480, "6.5"), (481, "7.0"), (3000, "7.0"), (3001, "7.5")],
                s.MONSTER: [(0, "4.0"), (33, "4.0"), (34, "4.5"), (200, "4.5"), (201, "5.0")],
                s.PREDATOR: [(0, "5.0"), (5250, "5.0"), (5251, "5.5"), (31000, "5.5"), (31001, "6.0")],
            },
        }
        for tier, categories in cases.items():
            for category, points in categories.items():
                for volume, expected in points:
                    with self.subTest(tier=tier, category=category, volume=volume):
                        self.assertEqual(s.get_rate(tier, category, volume), Decimal(expected))


class LandingCostTests(TestCase):
    def test_pack_parsing(self):
        self.assertEqual(parse_bottles_per_case("500 RGB X24 Coca Cola"), 24)
        self.assertEqual(parse_bottles_per_case("330 CAN 4X6 COCA COLA NG"), 24)
        self.assertEqual(parse_bottles_per_case("44cl Monster Energy Green *24"), 24)
        self.assertEqual(parse_bottles_per_case("1.5 Pet X12 Eva Water"), 12)
        self.assertIsNone(parse_bottles_per_case("40cl PET Predator Gold"))
        self.assertEqual(parse_litres("500 RGB X24"), Decimal("0.5"))
        self.assertEqual(parse_litres("330 CAN 4X6"), Decimal("0.33"))
        self.assertEqual(parse_litres("44cl Monster"), Decimal("0.44"))
        self.assertEqual(parse_litres("1.0 PET X12"), Decimal("1.0"))
        # NBC workbook lists 401 PET as 0.4L and calculates excise on 0.4L.
        self.assertEqual(parse_litres("401 PET X12 SCHWEPPES BITTER LEMON"), Decimal("0.4"))
        self.assertEqual(parse_litres("Monster 500ml X12"), Decimal("0.5"))
        self.assertEqual(parse_litres("Predator 400ml X12"), Decimal("0.4"))
        self.assertEqual(parse_litres("Monster Energy 44cl X24"), Decimal("0.44"))
        self.assertIsNone(parse_litres("Unrelated 2024 product"))

    def test_product_volume_and_pack_size_are_authoritative(self):
        product = SimpleNamespace(name="500 RGB X24 Cola", volume="330 ml", pack_size=12)
        result = landing_cost_breakdown(6000, product)
        self.assertEqual(result["excise"], Decimal("39.60"))
        self.assertTrue(result["excise_known"])

    def test_product_fields_support_common_volume_formats(self):
        cases = [
            ("500ml", Decimal("0.5")),
            ("44cl", Decimal("0.44")),
            ("1.5L", Decimal("1.5")),
            ("330", Decimal("0.33")),
            ("401", Decimal("0.4")),
        ]
        for raw_volume, expected in cases:
            with self.subTest(volume=raw_volume):
                product = SimpleNamespace(name="Unhelpful product label", volume=raw_volume, pack_size=24)
                result = landing_cost_breakdown(1000, product)
                self.assertEqual(result["excise"], expected * 24 * Decimal("10"))
                self.assertTrue(result["excise_known"])

    def test_missing_product_fields_fall_back_to_product_name(self):
        product = SimpleNamespace(name="500 RGB X24 Cola", volume="", pack_size=None)
        result = landing_cost_breakdown(6000, product)
        self.assertEqual(result["excise"], Decimal("120.00"))
        self.assertTrue(result["excise_known"])

    def test_invalid_nonblank_product_specification_is_flagged(self):
        product = SimpleNamespace(name="500 RGB X24 Cola", volume="unknown", pack_size=24)
        result = landing_cost_breakdown(6000, product)
        self.assertFalse(result["excise_known"])

    def test_workbook_examples(self):
        # price, name -> landing cost, worked out exactly as the workbook does
        cases = [
            (6000, "500 RGB X24 Coca Cola", "5430.00"),
            (10600, "330 CAN 4X6 COCA COLA NG", "9725.80"),
            (3800, "1.5 Pet X12 Eva Water", "3335.00"),
            (21000, "44cl Monster Energy Green *24", "19319.40"),
        ]
        for price, name, expected in cases:
            result = landing_cost_breakdown(price, name)
            self.assertEqual(result["landing_cost"], Decimal(expected), name)
            self.assertTrue(result["excise_known"])

    def test_unreadable_pack_leaves_excise_out_and_flags_it(self):
        result = landing_cost_breakdown(5200, "40cl PET Predator Gold")
        self.assertFalse(result["excise_known"])
        self.assertEqual(result["landing_cost"], Decimal("4810.00"))  # price less VAT only
