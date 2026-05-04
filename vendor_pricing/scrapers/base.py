"""Base scraper ABC and shared utilities."""

import json
from abc import ABC, abstractmethod
from typing import Optional

from ..models import DumpRow, Ingredient, SpecOption


class BaseScraper(ABC):
    """All vendor scrapers implement this interface."""

    vendor_name: str = ""      # e.g. "PFG"
    vendor_slug: str = ""      # e.g. "pfg"
    requires_login: bool = True

    def __init__(self, sku_map: Optional[dict] = None):
        # sku_map: {(vendor_lower, sku_lower): SpecOption} for ING_ID lookups
        self.sku_map: dict[tuple[str, str], SpecOption] = sku_map or {}

    def map_sku(self, sku: str) -> Optional[SpecOption]:
        """Look up ING_ID from the 03_SPEC_SELECTION map."""
        return self.sku_map.get((self.vendor_slug, sku.strip().lower()))

    @abstractmethod
    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        """
        Scrape prices for the given ingredients.
        Returns a list of DumpRow objects ready to append to the DUMP tab.
        """

    @staticmethod
    def calculate_cpu(pack_price: float, net_qty: float) -> float:
        if net_qty <= 0:
            return 0.0
        return round(pack_price / net_qty, 4)

    @staticmethod
    def intercept_json(responses: list, url_fragment: str) -> Optional[dict]:
        """Find the first response matching url_fragment and parse its JSON body."""
        for r in responses:
            if url_fragment.lower() in r.get("url", "").lower():
                try:
                    return json.loads(r.get("body", "{}"))
                except json.JSONDecodeError:
                    pass
        return None
