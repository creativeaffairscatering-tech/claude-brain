"""US Foods scraper — usfoods.com with XHR intercept."""

import json
import os
import re
import time
from datetime import date

from playwright.sync_api import sync_playwright, Page, Response

from .base import BaseScraper
from ..models import DumpRow, Ingredient


class USFoodsScraper(BaseScraper):
    vendor_name = "US Foods"
    vendor_slug = "usfoods"
    requires_login = True

    _API_FRAGMENTS = [
        "api/product",
        "search",
        "__NEXT_DATA__",
        "catalog",
    ]

    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        username = os.environ.get("USFOODS_USERNAME", "")
        password = os.environ.get("USFOODS_PASSWORD", "")

        if not username or not password:
            raise RuntimeError(
                "USFOODS_USERNAME and USFOODS_PASSWORD must be set in your .env file."
            )

        rows: list[DumpRow] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                self._login(page, username, password)
                for ing in ingredients:
                    try:
                        new_rows = self._search_ingredient(page, ing)
                        rows.extend(new_rows)
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"  [US Foods] Error searching '{ing.name}': {e}")
            finally:
                browser.close()

        return rows

    def _login(self, page: Page, username: str, password: str) -> None:
        print("  [US Foods] Logging in...")
        page.goto("https://www.usfoods.com/", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)
        try:
            page.click('a[href*="login"], button:has-text("Sign In"), button:has-text("Login")')
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            page.goto("https://www.usfoods.com/our-services/ordering.html")

        page.fill('input[type="email"], input[name="username"], input[id*="email"]', username)
        page.fill('input[type="password"], input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=30000)
        print("  [US Foods] Logged in.")

    def _search_ingredient(self, page: Page, ing: Ingredient) -> list[DumpRow]:
        captured: list[dict] = []

        def capture(response: Response):
            url = response.url.lower()
            if any(frag in url for frag in self._API_FRAGMENTS):
                try:
                    data = json.loads(response.text())
                    captured.append({"url": response.url, "data": data})
                except Exception:
                    pass

        page.on("response", capture)
        try:
            query = ing.name.replace(" ", "+")
            page.goto(
                f"https://www.usfoods.com/shop/products?search={query}",
                wait_until="networkidle",
                timeout=20000,
            )
        except Exception:
            pass
        finally:
            page.remove_listener("response", capture)

        rows = []
        for cap in captured:
            rows.extend(self._parse_response(cap["data"], ing))

        if not rows:
            rows = self._parse_next_data(page, ing)

        return rows

    def _parse_response(self, data: dict, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        products = (
            data.get("products")
            or data.get("items")
            or data.get("results")
            or []
        )
        if not isinstance(products, list):
            return []
        for p in products:
            try:
                sku = str(p.get("itemNumber") or p.get("sku") or p.get("id") or "")
                desc = str(p.get("description") or p.get("name") or "")
                pack_size = str(p.get("packSize") or "")
                uom = str(p.get("unitOfMeasure") or "EA")
                price = float(p.get("price") or p.get("casePrice") or 0)
                net_qty = float(p.get("netQuantity") or p.get("netQty") or 1)
                if not sku or price <= 0:
                    continue
                spec = self.map_sku(sku)
                rows.append(DumpRow(
                    vendor=self.vendor_name,
                    invoice_no=f"SCRAPER_{today}",
                    sku=sku, vendor_description=desc,
                    pack_size=pack_size, pack_unit=uom,
                    pack_price=price, net_qty=net_qty, uom=uom,
                    cpu=self.calculate_cpu(price, net_qty),
                    ing_id=spec.ing_id if spec else ing.ing_id,
                    canonical_name=spec.canonical_name if spec else ing.name,
                    mapped_by="scraper", date=today,
                ))
            except Exception:
                continue
        return rows

    def _parse_next_data(self, page: Page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            script = page.query_selector("#__NEXT_DATA__")
            if not script:
                return []
            data = json.loads(script.inner_text())
            products = (
                data.get("props", {}).get("pageProps", {})
                .get("searchResults", {}).get("products") or []
            )
            for p in products[:20]:
                try:
                    sku = str(p.get("itemNumber") or "")
                    desc = str(p.get("name") or "")
                    price = float(p.get("price") or 0)
                    if not desc or price <= 0:
                        continue
                    spec = self.map_sku(sku) if sku else None
                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku=sku or "NEXTDATA", vendor_description=desc,
                        pack_size="", pack_unit="EA",
                        pack_price=price, net_qty=1.0, uom="EA", cpu=price,
                        ing_id=spec.ing_id if spec else ing.ing_id,
                        canonical_name=spec.canonical_name if spec else ing.name,
                        mapped_by="scraper_nextdata", date=today,
                    ))
                except Exception:
                    continue
        except Exception:
            pass
        return rows
