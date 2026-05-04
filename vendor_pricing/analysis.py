"""Price analysis — best vendor selection, comparisons, savings."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .models import DumpRow, Ingredient


@dataclass
class VendorPrice:
    vendor: str
    sku: str
    description: str
    pack_size: str
    pack_unit: str
    pack_price: float
    net_qty: float
    uom: str
    cpu: float
    date: str


@dataclass
class CompareResult:
    ing_id: str
    canonical_name: str
    prices: list[VendorPrice]   # sorted cheapest first

    @property
    def best(self) -> Optional[VendorPrice]:
        return self.prices[0] if self.prices else None

    @property
    def savings_vs_worst(self) -> float:
        if len(self.prices) < 2:
            return 0.0
        return round(self.prices[-1].cpu - self.prices[0].cpu, 4)


def _latest_by_vendor(rows: list[DumpRow]) -> dict[tuple[str, str], DumpRow]:
    """Return {(ing_id, vendor): most_recent_row}."""
    latest: dict[tuple[str, str], DumpRow] = {}
    for row in rows:
        if not row.ing_id or not row.vendor:
            continue
        key = (row.ing_id, row.vendor)
        if key not in latest or row.date > latest[key].date:
            latest[key] = row
    return latest


def compare_ingredient(
    ing_id: str,
    dump_rows: list[DumpRow],
    canonical_name: str = "",
) -> CompareResult:
    """Compare latest prices for one ingredient across all vendors."""
    latest = _latest_by_vendor(dump_rows)
    prices = []
    for (iid, vendor), row in latest.items():
        if iid != ing_id:
            continue
        prices.append(VendorPrice(
            vendor=vendor,
            sku=row.sku,
            description=row.vendor_description,
            pack_size=row.pack_size,
            pack_unit=row.pack_unit,
            pack_price=row.pack_price,
            net_qty=row.net_qty,
            uom=row.uom,
            cpu=row.cpu,
            date=row.date,
        ))
    prices.sort(key=lambda p: p.cpu)
    return CompareResult(ing_id=ing_id, canonical_name=canonical_name, prices=prices)


def compare_by_name(
    name_query: str,
    dump_rows: list[DumpRow],
    ingredients: list[Ingredient],
) -> list[CompareResult]:
    """Search canonical ingredient names, return compare results for all matches."""
    q = name_query.lower()
    matches = [i for i in ingredients if q in i.name.lower()]
    results = []
    for ing in matches:
        results.append(compare_ingredient(ing.ing_id, dump_rows, ing.name))
    return results


def get_best_vendor(
    ing_id: str,
    dump_rows: list[DumpRow],
) -> Optional[VendorPrice]:
    """Return the lowest-CPU vendor price for an ingredient."""
    result = compare_ingredient(ing_id, dump_rows)
    return result.best


def best_per_ingredient(
    dump_rows: list[DumpRow],
    ingredients: list[Ingredient],
    category_filter: Optional[str] = None,
) -> list[tuple[Ingredient, Optional[VendorPrice]]]:
    """
    Return (ingredient, best_vendor_price) for every ingredient.
    Optionally filter by category.
    """
    filtered = ingredients
    if category_filter:
        filtered = [i for i in ingredients if category_filter.lower() in i.category.lower()]

    results = []
    for ing in filtered:
        best = get_best_vendor(ing.ing_id, dump_rows)
        results.append((ing, best))
    return results


def savings_opportunities(
    dump_rows: list[DumpRow],
    ingredients: list[Ingredient],
    top_n: int = 10,
) -> list[CompareResult]:
    """
    Return the top N ingredients by potential savings (worst vendor CPU -
    best vendor CPU), showing where switching vendors saves the most money.
    """
    results = []
    for ing in ingredients:
        result = compare_ingredient(ing.ing_id, dump_rows, ing.name)
        if len(result.prices) >= 2:
            results.append(result)

    results.sort(key=lambda r: r.savings_vs_worst, reverse=True)
    return results[:top_n]


def dump_status(dump_rows: list[DumpRow]) -> dict:
    """
    Return summary stats about the DUMP:
    - total row count
    - row count per vendor
    - last update date per vendor
    """
    vendor_counts: dict[str, int] = defaultdict(int)
    vendor_last_date: dict[str, str] = {}

    for row in dump_rows:
        v = row.vendor
        vendor_counts[v] += 1
        if v not in vendor_last_date or row.date > vendor_last_date[v]:
            vendor_last_date[v] = row.date

    return {
        "total_rows": len(dump_rows),
        "vendors": {
            v: {"rows": vendor_counts[v], "last_date": vendor_last_date.get(v, "")}
            for v in sorted(vendor_counts)
        },
    }
