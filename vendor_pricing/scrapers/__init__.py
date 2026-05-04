"""Scraper registry — maps vendor slugs to scraper classes."""

from typing import Optional

from .base import BaseScraper
from .pfg import PFGScraper
from .sysco import SyscoScraper
from .usfoods import USFoodsScraper
from .samsclub import SamsClubScraper
from .walmart import WalmartScraper
from .restaurant_depot import RestaurantDepotScraper, ChefStoreScraper

# Vendor slugs that have auto-scrapers
SCRAPER_VENDORS = [
    "pfg",
    "sysco",
    "usfoods",
    "samsclub",
    "walmart",
    "restaurant_depot",
    "chef_store",
]

# Manual-only vendors (use vp manual or vp import-csv)
MANUAL_VENDORS = [
    "brothers",
    "chefs_produce",
    "sprouts",
]

_REGISTRY: dict[str, type[BaseScraper]] = {
    "pfg": PFGScraper,
    "sysco": SyscoScraper,
    "usfoods": USFoodsScraper,
    "samsclub": SamsClubScraper,
    "walmart": WalmartScraper,
    "restaurant_depot": RestaurantDepotScraper,
    "chef_store": ChefStoreScraper,
}


def get_scraper(
    vendor_slug: str,
    sku_map: Optional[dict] = None,
) -> Optional[BaseScraper]:
    """Return an initialized scraper for the given vendor slug, or None."""
    cls = _REGISTRY.get(vendor_slug.lower())
    if cls is None:
        return None
    return cls(sku_map=sku_map or {})
