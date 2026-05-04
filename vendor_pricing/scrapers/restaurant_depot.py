"""Restaurant Depot scraper — hybrid: try Playwright, prompt for manual fallback."""

import json
import re
import time
from datetime import date

from playwright.sync_api import sync_playwright

from .base import BaseScraper
from ..models import DumpRow, Ingredient


class RestaurantDepotScraper(BaseScraper):
    vendor_name = "Restaurant Depot"
    vendor_slug = "restaurant_depot"
    requires_login = False  # site often blocks automation

    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        rows: list[DumpRow] = []
        print("  [Restaurant Depot] Attempting public web scrape...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            page = context.new_page()

            for ing in ingredients:
                try:
                    new_rows = self._search_ingredient(page, ing)
                    rows.extend(new_rows)
                    time.sleep(1.5)
                except Exception as e:
                    print(f"  [Restaurant Depot] Error for '{ing.name}': {e}")

            browser.close()

        if not rows:
            print(
                "  [Restaurant Depot] Automated scrape returned no results "
                "(site may require manual login).\n"
                "  Use 'vp manual --vendor restaurant_depot' to enter prices."
            )

        return rows

    def _search_ingredient(self, page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            query = ing.name.replace(" ", "+")
            page.goto(
                f"https://www.restaurantdepot.com/search?q={query}",
                wait_until="networkidle",
                timeout=20000,
            )

            # Try to parse products from DOM
            cards = page.query_selector_all(
                ".product-card, .product-item, .search-result-item, [data-product-id]"
            )
            for card in cards[:10]:
                try:
                    sku = _text(card, "[data-product-id], .product-id, .sku")
                    desc = _text(card, ".product-name, h3, h4, .title")
                    price_str = _text(card, ".price, .product-price, .case-price")
                    price = _parse_price(price_str)
                    if not desc or price <= 0:
                        continue
                    spec = self.map_sku(sku) if sku else None
                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku=sku or "DOM",
                        vendor_description=desc,
                        pack_size="",
                        pack_unit="EA",
                        pack_price=price,
                        net_qty=1.0,
                        uom="EA",
                        cpu=price,
                        ing_id=spec.ing_id if spec else ing.ing_id,
                        canonical_name=spec.canonical_name if spec else ing.name,
                        mapped_by="scraper_dom",
                        notes="Verify pack size manually",
                        date=today,
                    ))
                except Exception:
                    continue
        except Exception:
            pass
        return rows


class ChefStoreScraper(BaseScraper):
    """Chef Store (US Foods retail) — public search."""

    vendor_name = "Chef Store"
    vendor_slug = "chef_store"
    requires_login = False

    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        rows: list[DumpRow] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            for ing in ingredients:
                try:
                    new_rows = self._search_ingredient(page, ing)
                    rows.extend(new_rows)
                    time.sleep(1.0)
                except Exception as e:
                    print(f"  [Chef Store] Error for '{ing.name}': {e}")

            browser.close()

        return rows

    def _search_ingredient(self, page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            query = ing.name.replace(" ", "+")
            page.goto(
                f"https://www.chefstore.com/search?q={query}",
                wait_until="networkidle",
                timeout=20000,
            )

            # Try __NEXT_DATA__
            script = page.query_selector("#__NEXT_DATA__")
            if script:
                try:
                    data = json.loads(script.inner_text())
                    products = (
                        data.get("props", {}).get("pageProps", {})
                        .get("searchData", {}).get("products") or []
                    )
                    for p in products[:15]:
                        sku = str(p.get("itemNumber") or p.get("sku") or "")
                        desc = str(p.get("name") or p.get("description") or "")
                        price = float(p.get("price") or 0)
                        pack = str(p.get("packSize") or "")
                        if not desc or price <= 0:
                            continue
                        spec = self.map_sku(sku) if sku else None
                        rows.append(DumpRow(
                            vendor=self.vendor_name,
                            invoice_no=f"SCRAPER_{today}",
                            sku=sku or "NEXTDATA",
                            vendor_description=desc,
                            pack_size=pack, pack_unit="EA",
                            pack_price=price, net_qty=1.0, uom="EA", cpu=price,
                            ing_id=spec.ing_id if spec else ing.ing_id,
                            canonical_name=spec.canonical_name if spec else ing.name,
                            mapped_by="scraper", date=today,
                        ))
                except Exception:
                    pass

            if not rows:
                cards = page.query_selector_all(".product-card, .product-item")
                for card in cards[:15]:
                    try:
                        desc = _text(card, ".product-name, h3")
                        price_str = _text(card, ".price")
                        price = _parse_price(price_str)
                        if not desc or price <= 0:
                            continue
                        rows.append(DumpRow(
                            vendor=self.vendor_name,
                            invoice_no=f"SCRAPER_{today}",
                            sku="DOM", vendor_description=desc,
                            pack_size="", pack_unit="EA",
                            pack_price=price, net_qty=1.0, uom="EA", cpu=price,
                            ing_id=ing.ing_id, canonical_name=ing.name,
                            mapped_by="scraper_dom",
                            notes="Verify pack size", date=today,
                        ))
                    except Exception:
                        continue
        except Exception:
            pass
        return rows


def _text(el, sel):
    try:
        e = el.query_selector(sel)
        return e.inner_text().strip() if e else ""
    except Exception:
        return ""


def _parse_price(s):
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except Exception:
        return 0.0
