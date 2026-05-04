"""Sysco scraper — shop.sysco.com with XHR intercept."""

import json
import os
import re
import time
from datetime import date

from playwright.sync_api import sync_playwright, Page, Response

from .base import BaseScraper
from ..models import DumpRow, Ingredient


class SyscoScraper(BaseScraper):
    vendor_name = "Sysco"
    vendor_slug = "sysco"
    requires_login = True

    _API_FRAGMENTS = [
        "api/product",
        "search/products",
        "catalog",
        "graphql",
    ]

    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        username = os.environ.get("SYSCO_USERNAME", "")
        password = os.environ.get("SYSCO_PASSWORD", "")

        if not username or not password:
            raise RuntimeError(
                "SYSCO_USERNAME and SYSCO_PASSWORD must be set in your .env file."
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
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"  [Sysco] Error searching '{ing.name}': {e}")

            finally:
                browser.close()

        return rows

    def _login(self, page: Page, username: str, password: str) -> None:
        print("  [Sysco] Logging in...")
        page.goto("https://shop.sysco.com/app/login", wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=30000)

        page.fill('input[type="email"], input[name="email"], input[name="username"]', username)
        page.fill('input[type="password"], input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=30000)
        print("  [Sysco] Logged in.")

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
            page.goto(
                f"https://shop.sysco.com/app/catalog?q={ing.name.replace(' ', '+')}",
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
            rows = self._parse_dom(page, ing)

        return rows

    def _parse_response(self, data: dict, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []

        products = (
            data.get("products")
            or data.get("items")
            or data.get("data", {}).get("products")
            or []
        )

        if isinstance(data, dict) and "data" in data:
            # GraphQL response
            gql_data = data.get("data", {})
            products = (
                gql_data.get("searchProducts", {}).get("products")
                or gql_data.get("products")
                or products
            )

        if not isinstance(products, list):
            return []

        for product in products:
            try:
                sku = str(product.get("supc") or product.get("sku") or product.get("itemNumber") or "")
                desc = str(product.get("name") or product.get("description") or "")
                pack_size = str(product.get("packSize") or product.get("packSizeDescription") or "")
                uom = str(product.get("catchWeightIndicator") or product.get("uom") or "EA")

                price_block = product.get("pricing") or product.get("price") or {}
                if isinstance(price_block, dict):
                    pack_price = float(
                        price_block.get("casePrice")
                        or price_block.get("price")
                        or price_block.get("unitPrice")
                        or 0
                    )
                else:
                    pack_price = float(price_block or 0)

                net_qty = float(product.get("packSize") or 1)
                if pack_size and "/" in pack_size:
                    # e.g. "4/5 LB" → net_qty = 20
                    try:
                        parts = pack_size.split("/")
                        qty_str = re.sub(r"[^\d.]", "", parts[1])
                        net_qty = float(parts[0]) * float(qty_str)
                    except Exception:
                        pass

                if not sku or pack_price <= 0:
                    continue

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
        today = date.today().isoformat()
        rows = []
        try:
            cards = page.query_selector_all(".product-card, .search-result, [data-testid='product']")
            for card in cards[:20]:
                try:
                    sku = _text(card, ".supc, .sku, [data-supc]")
                    desc = _text(card, ".product-name, h3, h4")
                    price_str = _text(card, ".price, .case-price")
                    pack = _text(card, ".pack-size")
                    price = _parse_price(price_str)
                    if not desc or price <= 0:
                        continue
                    spec = self.map_sku(sku) if sku else None
                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku=sku or "DOM",
                        vendor_description=desc,
                        pack_size=pack,
                        pack_unit="EA",
                        pack_price=price,
                        net_qty=1.0,
                        uom="EA",
                        cpu=price,
                        ing_id=spec.ing_id if spec else ing.ing_id,
                        canonical_name=spec.canonical_name if spec else ing.name,
                        mapped_by="scraper_dom",
                        notes="DOM parse — verify",
                        date=today,
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
