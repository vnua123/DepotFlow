"""
NBC month-end rebate rates, transcribed from NBC's rebate table
("Month End Rebate Payout - Based on Monthly Achieved Volume in Physical Cases").

How NBC pays:
  * PLACEMENT (Standard / Maxi / Mega) is worked out QUARTERLY from the
    depot's total NBC cases for the quarter: Standard up to 12,000,
    Maxi above 12,000, Mega above 40,000.
  * PAYMENT is MONTHLY. Within the quarter's placement, each category's
    cases for that month pick its rate: the "fixed" rate, or a higher
    rate once the category passes each step. The rate reached applies to
    the category's whole month, and is a percentage of the rebate-based
    (landing) cost, not the tax-inclusive price.

Pure Python (no Django). When NBC revises the table, edit SCHEME below.
"""

SPARKLING = "SPARKLING"
WATER = "WATER"
JUICE = "JUICE"
MONSTER = "MONSTER"      # Energy - Premium
PREDATOR = "PREDATOR"    # Energy - Affordable

STANDARD = "STANDARD"
MAXI = "MAXI"
MEGA = "MEGA"

CATEGORY_ORDER = [SPARKLING, WATER, JUICE, MONSTER, PREDATOR]

CATEGORY_LABELS = {
    SPARKLING: "Sparkling (SSD)",
    WATER: "Water",
    JUICE: "Juice",
    MONSTER: "Energy - Premium (Monster)",
    PREDATOR: "Energy - Affordable (Predator)",
}

# Quarterly cases must be MORE than the number to reach the placement.
PLACEMENT_THRESHOLDS = [(MEGA, 40000), (MAXI, 12000)]

# tier -> category -> (fixed rate %, [(monthly cases from, rate %), ...])
SCHEME = {
    STANDARD: {
        SPARKLING: ("7.5", [(2100, "8.0"), (2701, "8.5")]),
        WATER:     ("8.0", [(400, "8.5"), (651, "9.0")]),
        JUICE:     ("5.5", [(70, "6.0"), (121, "6.5")]),
        MONSTER:   ("3.0", [(8, "3.5"), (14, "4.0")]),
        PREDATOR:  ("4.0", [(1050, "4.5"), (1351, "5.0")]),
    },
    MAXI: {
        SPARKLING: ("8.0", [(2701, "8.5"), (10501, "9.0")]),
        WATER:     ("8.5", [(651, "9.0"), (1801, "9.5")]),
        JUICE:     ("6.0", [(121, "6.5"), (481, "7.0")]),
        MONSTER:   ("3.5", [(14, "4.0"), (34, "4.5")]),
        PREDATOR:  ("4.5", [(1351, "5.0"), (5251, "5.5")]),
    },
    MEGA: {
        SPARKLING: ("8.5", [(10501, "9.0"), (62001, "9.5")]),
        WATER:     ("9.0", [(1801, "9.5"), (9001, "10.0")]),
        JUICE:     ("6.5", [(481, "7.0"), (3001, "7.5")]),
        MONSTER:   ("4.0", [(34, "4.5"), (201, "5.0")]),
        PREDATOR:  ("5.0", [(5251, "5.5"), (31001, "6.0")]),
    },
}


def placement_for_cases(quarter_cases):
    for tier, threshold in PLACEMENT_THRESHOLDS:
        if quarter_cases > threshold:
            return tier
    return STANDARD


def get_rate(tier, category, monthly_cases):
    """Rebate percentage (Decimal) for a category's cases in one month."""
    from decimal import Decimal

    fixed, steps = SCHEME[tier][category]
    rate = Decimal(fixed)
    for start, step_rate in steps:
        if monthly_cases >= start:
            rate = Decimal(step_rate)
    return rate
