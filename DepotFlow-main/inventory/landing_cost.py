"""
Two costs per case on an NBC purchase (from NBC's sub-dealer rebate workbook):

  * Total cost         - NBC's invoice price per case (StockReceiptItem.cost_price).
                         This is also the selling-price basis and it already
                         contains VAT and excise tax.
  * Rebate-based cost  - the "landing cost": total cost with the tax taken out.
                         NBC's rebate is a percentage of THIS, never of the
                         tax-inclusive price.

Workbook formula, per case:
    VAT          = 7.5% of the price
    Excise       = litres per bottle x bottles per case x N10
    Landing cost = price - VAT - excise

Pure Python (no Django) so it can be tested on its own. To change a tax
rate, edit the two constants below.
"""

import re
from decimal import Decimal, ROUND_HALF_UP

VAT_RATE = Decimal("0.075")
EXCISE_PER_LITRE = Decimal("10")

_TWO_PLACES = Decimal("0.01")


def _money(value):
    return Decimal(value).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def parse_litres(value):
    """Convert a product volume (or legacy product-name size) to litres.

    Explicit ML/CL/L sizes may occur anywhere in a product description,
    e.g. "Monster 500ml X12". If no unit is present, only a leading numeric
    token is treated as a size, preserving legacy catalogue conventions.
    The NBC token "401 PET" represents 0.4L.
    """
    text = str(value or "").strip().upper()

    # Prefer explicit units anywhere in the product name/specification.
    match = re.search(r"(?<![A-Z0-9.])(\d+(?:\.\d+)?)\s*(CL|ML|L)\b", text)
    if match:
        amount = Decimal(match.group(1))
        unit = match.group(2)
        if unit == "CL":
            return amount / 100
        if unit == "ML":
            return amount / 1000
        return amount

    # Legacy no-unit sizes are accepted only at the beginning.
    match = re.match(r"^(\d+(?:\.\d+)?)(?:\s|$)", text)
    if not match:
        return None
    amount = Decimal(match.group(1))
    if amount == Decimal("401"):
        return Decimal("0.4")
    return amount if amount < 10 else amount / 1000


def parse_bottles_per_case(name):
    """Bottles/cans per case: '4X6' -> 24, 'X12' -> 12, '*24' -> 24, else None."""
    text = (name or "").upper()
    grid = re.search(r"(\d+)\s*X\s*(\d+)", text)
    if grid:
        return int(grid.group(1)) * int(grid.group(2))
    star = re.search(r"\*\s*(\d+)", text)
    if star:
        return int(star.group(1))
    single = re.search(r"\bX\s*(\d+)", text)
    if single:
        return int(single.group(1))
    return None


def landing_cost_breakdown(price, product):
    """Return the tax and rebate landing-cost breakdown for one case.

    Product.volume and Product.pack_size are authoritative. Product-name
    parsing is retained only as a fallback for legacy/incomplete product
    records where the corresponding specification is blank or absent.
    Invalid nonblank specifications are not silently overridden by a name.
    A plain string remains supported for older callers and isolated tests.
    """
    price = Decimal(price)
    vat = price * VAT_RATE

    if isinstance(product, str) or product is None:
        product_name = product or ""
        litres = parse_litres(product_name)
        bottles = parse_bottles_per_case(product_name)
    else:
        product_name = getattr(product, "name", "") or ""
        raw_volume = getattr(product, "volume", None)
        raw_pack_size = getattr(product, "pack_size", None)

        litres = parse_litres(raw_volume) if raw_volume not in (None, "") else parse_litres(product_name)
        if raw_pack_size in (None, ""):
            bottles = parse_bottles_per_case(product_name)
        else:
            try:
                bottles = int(raw_pack_size)
                if bottles <= 0:
                    bottles = None
            except (TypeError, ValueError):
                bottles = None

    excise_known = litres is not None and bottles is not None
    excise = litres * bottles * EXCISE_PER_LITRE if excise_known else Decimal("0")

    landing = max(price - vat - excise, Decimal("0"))

    return {
        "price": _money(price),
        "vat": _money(vat),
        "excise": _money(excise),
        "landing_cost": _money(landing),
        "excise_known": excise_known,
    }
