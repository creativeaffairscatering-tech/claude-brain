"""Walmart scraper — public search, JSON-LD and __NEXT_DATA__ parsing."""

import json
import re
import time
from datetime import date

from playwright.sync_api import sync_playwright

from .base import BaseScraper
from ..models import DumpRow, Ingredient


class WalmartScraper(BaseScraper):
    vendor_name = "Walmart"
    vendor_slug = "walmart"
    requires_login = False

    def scrape(self, ingredients: list[Ingredient]) -> list[DumpRow]:
        rows: list[DumpRow] = []

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
                    print(f"  [Walmart] Error searching '{ing.name}': {e}")

            browser.close()

        return rows

    def _search_ingredient(self, page, ing: Ingredient) -> list[DumpRow]:
        query = ing.name.replace(" ", "+")
        try:
            page.goto(
                f"https://www.walmart.com/search?q={query}&affinityOverride=default",
                wait_until="networkidle",
                timeout=20000,
            )
        except Exception:
            pass

        # Try JSON-LD structured data first
        rows = self._parse_jsonld(page, ing)
        if rows:
            return rows

        # Try __NEXT_DATA__ embedded JSON
        rows = self._parse_next_data(page, ing)
        if rows:
            return rows

        # DOM fallback
        return self._parse_dom(page, ing)

    def _parse_jsonld(self, page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            scripts = page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                try:
                    data = json.loads(script.inner_text())
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        if item.get("@type") not in ("Product", "ItemList"):
                            continue
                        products = item.get("itemListElement") or [item]
                        for p in products:
                            prod = p.get("item") or p
                            offer = prod.get("offers") or {}
                            if isinstance(offer, list):
                                offer = offer[0]
                            price = float(offer.get("price") or 0)
                            sku = str(prod.get("sku") or prod.get("productID") or "")
                            desc = str(prod.get("name") or "")
                            if not desc or price <= 0:
                                continue
                            spec = self.map_sku(sku) if sku else None
                            rows.append(DumpRow(
                                vendor=self.vendor_name,
                                invoice_no=f"SCRAPER_{today}",
                                sku=sku or "JSONLD",
                                vendor_description=desc,
                                pack_size="",
                                pack_unit="EA",
                                pack_price=price,
                                net_qty=1.0,
                                uom="EA",
                                cpu=price,
                                ing_id=spec.ing_id if spec else ing.ing_id,
                                canonical_name=spec.canonical_name if spec else ing.name,
                                mapped_by="scraper_jsonld",
                                notes="Verify pack size",
                                date=today,
                            ))
                except Exception:
                    continue
        except Exception:
            pass
        return rows

    def _parse_next_data(self, page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            script = page.query_selector("#__NEXT_DATA__")
            if not script:
                return []
            data = json.loads(script.inner_text())
            # Navigate Walmart's Next.js data structure
            search_data = (
                data.get("props", {})
                .get("pageProps", {})
                .get("initialData", {})
                .get("searchResult", {})
            )
            items = (
                search_data.get("itemStacks", [{}])[0].get("items")
                or search_data.get("items")
                or []
            )
            for item in items[:20]:
                try:
                    sku = str(item.get("usItemId") or item.get("id") or "")
                    desc = str(item.get("name") or "")
                    price = float(
                        item.get("price")
                        or item.get("priceInfo", {}).get("currentPrice", {}).get("price")
                        or 0
                    )
                    unit = str(item.get("unitQuantity") or item.get("weight") or "")
                    if not desc or price <= 0:
                        continue
                    net_qty, uom = _parse_weight(unit)
                    spec = self.map_sku(sku) if sku else None
                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku=sku or "NEXTDATA",
                        vendor_description=desc,
                        pack_size=unit,
                        pack_unit=uom,
                        pack_price=price,
                        net_qty=net_qty,
                        uom=uom,
                        cpu=self.calculate_cpu(price, net_qty),
                        ing_id=spec.ing_id if spec else ing.ing_id,
                        canonical_name=spec.canonical_name if spec else ing.name,
                        mapped_by="scraper_nextdata",
                        date=today,
                    ))
                except Exception:
                    continue
        except Exception:
            pass
        return rows

    def _parse_dom(self, page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            cards = page.query_selector_all(
                '[data-item-id], [data-testid="list-view"], .search-result-gridview-item'
            )
            for card in cards[:15]:
                try:
                    desc = _text(card, '[itemprop="name"], .product-title-link, span.lh-title')
                    price_str = _text(card, '[itemprop="price"], .price-main, .price-characteristic')
                    price = _parse_price(price_str)
                    if not desc or price <= 0:
                        continue
                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku="DOM",
                        vendor_description=desc,
                        pack_size="",
                        pack_unit="EA",
                        pack_price=price,
                        net_qty=1.0,
                        uom="EA",
                        cpu=price,
                        ing_id=ing.ing_id,
                        canonical_name=ing.name,
                        mapped_by="scraper_dom",
                        notes="DOM parse — verify pack and qty",
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


def _parse_weight(s: str) -> tuple[float, str]:
    if not s:
        return 1.0, "EA"
    s = s.strip().upper()
    m = re.match(r"(\d+\.?\d*)\s*(LB|OZ|EA|GAL|CT|FL OZ)", s)
    if m:
        return float(m.group(1)), m.group(2)
    return 1.0, "EA"
