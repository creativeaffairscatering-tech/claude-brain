"""
PFG (Performance Food Group) scraper.
Extends the existing price_scraper.py login flow.
Instead of saving a PDF, intercepts the XHR product search response
and parses structured JSON pricing data.
"""

import json
import os
import re
import time
from datetime import date
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Response

from .base import BaseScraper
from ..models import DumpRow, Ingredient, SpecOption


class PFGScraper(BaseScraper):
    vendor_name = "PFG"
    vendor_slug = "pfg"
    requires_login = True

    # Known XHR URL fragments for PFG product search
    _API_FRAGMENTS = [
        "api/products/search",
        "api/search",
        "products?",
        "search?",
        "catalog/search",
    ]

    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        username = os.environ.get("PFG_USERNAME", "")
        password = os.environ.get("PFG_PASSWORD", "")

        if not username or not password:
            raise RuntimeError(
                "PFG_USERNAME and PFG_PASSWORD must be set in your .env file."
            )

        rows: list[DumpRow] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                self._login(page, username, password)

                for ing in ingredients:
                    try:
                        new_rows = self._search_ingredient(page, ing)
                        rows.extend(new_rows)
                        time.sleep(0.5)  # polite delay between searches
                    except Exception as e:
                        print(f"  [PFG] Error searching '{ing.name}': {e}")
                        continue

            finally:
                browser.close()

        return rows

    def _login(self, page: Page, username: str, password: str) -> None:
        """Login flow from existing price_scraper.py, extended."""
        print("  [PFG] Navigating to login page...")
        page.goto("https://pfgcustomerfirst.com/", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)

        # Fill credentials
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')

        # Wait for post-login navigation
        page.wait_for_load_state("networkidle", timeout=30000)
        print("  [PFG] Logged in.")

    def _search_ingredient(self, page: Page, ing: Ingredient) -> list[DumpRow]:
        """Search for one ingredient and parse results."""
        captured: list[dict] = []

        def capture_response(response: Response):
            url = response.url.lower()
            if any(frag in url for frag in self._API_FRAGMENTS):
                try:
                    body = response.text()
                    data = json.loads(body)
                    captured.append({"url": response.url, "data": data})
                except Exception:
                    pass

        page.on("response", capture_response)

        # Search for the ingredient
        try:
            search_box = page.wait_for_selector(
                'input[placeholder*="Search"], input[type="search"], input[name="search"]',
                timeout=10000,
            )
            search_box.triple_click()
            search_box.fill(ing.name)
            page.keyboard.press("Enter")
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"    [PFG] Search failed for '{ing.name}': {e}")
            return []
        finally:
            page.remove_listener("response", capture_response)

        # Parse captured XHR responses
        rows = []
        for cap in captured:
            rows.extend(self._parse_response(cap["data"], ing))

        # Fallback: parse DOM if no XHR captured
        if not rows:
            rows = self._parse_dom(page, ing)

        return rows

    def _parse_response(self, data: dict, ing: Ingredient) -> list[DumpRow]:
        """Parse a PFG product search API JSON response."""
        rows = []
        today = date.today().isoformat()

        # Try common response shapes
        products = (
            data.get("products")
            or data.get("items")
            or data.get("results")
            or data.get("data", {}).get("products")
            or []
        )

        if not isinstance(products, list):
            return []

        for product in products:
            try:
                sku = str(product.get("sku") or product.get("itemNumber") or product.get("id") or "")
                desc = str(
                    product.get("description")
                    or product.get("name")
                    or product.get("productName")
                    or ""
                )
                pack_size = str(
                    product.get("packSize")
                    or product.get("pack_size")
                    or product.get("unitSize")
                    or ""
                )

                # Price extraction — PFG uses various field names
                price_info = (
                    product.get("pricing")
                    or product.get("price")
                    or product
                )
                pack_price = float(
                    price_info.get("casePrice")
                    or price_info.get("pack_price")
                    or price_info.get("unitPrice")
                    or price_info.get("price")
                    or 0
                )

                net_qty = float(
                    product.get("netWeight")
                    or product.get("net_qty")
                    or product.get("quantity")
                    or 1
                )
                uom = str(
                    product.get("unitOfMeasure")
                    or product.get("uom")
                    or product.get("unit")
                    or "EA"
                )

                if not sku or pack_price <= 0:
                    continue

                # Map SKU to ING_ID
                spec = self.map_sku(sku)
                ing_id = spec.ing_id if spec else ing.ing_id
                canonical = spec.canonical_name if spec else ing.name

                rows.append(DumpRow(
                    vendor=self.vendor_name,
                    invoice_no=f"SCRAPER_{today}",
                    sku=sku,
                    vendor_description=desc,
                    pack_size=pack_size,
                    pack_unit=uom,
                    pack_price=pack_price,
                    net_qty=net_qty,
                    uom=uom,
                    cpu=self.calculate_cpu(pack_price, net_qty),
                    ing_id=ing_id,
                    canonical_name=canonical,
                    mapped_by="scraper",
                    date=today,
                ))
            except (TypeError, ValueError):
                continue

        return rows

    def _parse_dom(self, page: Page, ing: Ingredient) -> list[DumpRow]:
        """DOM fallback parser when XHR intercept yields nothing."""
        today = date.today().isoformat()
        rows = []

        try:
            # Common PFG product card selectors
            cards = page.query_selector_all(
                ".product-card, .search-result-item, [data-testid='product-item'], .product-tile"
            )

            for card in cards[:20]:
                try:
                    sku = _text(card, "[data-sku], .sku, .item-number")
                    desc = _text(card, ".product-name, .description, h3, h4")
                    price_str = _text(card, ".price, .case-price, [data-price]")
                    pack = _text(card, ".pack-size, .unit-size, .pack")

                    price = _parse_price(price_str)
                    if not desc or price <= 0:
                        continue

                    spec = self.map_sku(sku) if sku else None
                    ing_id = spec.ing_id if spec else ing.ing_id
                    canonical = spec.canonical_name if spec else ing.name

                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku=sku or "DOM_PARSE",
                        vendor_description=desc,
                        pack_size=pack,
                        pack_unit="EA",
                        pack_price=price,
                        net_qty=1.0,
                        uom="EA",
                        cpu=price,
                        ing_id=ing_id,
                        canonical_name=canonical,
                        mapped_by="scraper_dom",
                        notes="DOM parse — verify pack size",
                        date=today,
                    ))
                except Exception:
                    continue
        except Exception:
            pass

        return rows


def _text(element, selector: str) -> str:
    try:
        el = element.query_selector(selector)
        return el.inner_text().strip() if el else ""
    except Exception:
        return ""


def _parse_price(s: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", s))
    except (ValueError, TypeError):
        return 0.0
