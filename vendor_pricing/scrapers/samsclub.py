"""Sam's Club scraper — public search, no login required."""

import json
import re
import time
from datetime import date

from playwright.sync_api import sync_playwright, Response

from .base import BaseScraper
from ..models import DumpRow, Ingredient


class SamsClubScraper(BaseScraper):
    vendor_name = "Sam's Club"
    vendor_slug = "samsclub"
    requires_login = False

    _API_FRAGMENTS = [
        "api/search",
        "graphql",
        "samsclub.com/api",
    ]

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
                    time.sleep(1.0)
                except Exception as e:
                    print(f"  [Sam's Club] Error searching '{ing.name}': {e}")

            browser.close()

        return rows

    def _search_ingredient(self, page, ing: Ingredient) -> list[DumpRow]:
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
                f"https://www.samsclub.com/s/{query}",
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

        # Sam's Club typically returns products in payload.records or similar
        records = (
            data.get("payload", {}).get("records")
            or data.get("records")
            or data.get("products")
            or data.get("items")
            or []
        )

        if not isinstance(records, list):
            return []

        for item in records:
            try:
                props = item.get("productAttributes") or item
                sku = str(props.get("skuId") or props.get("itemNumber") or props.get("id") or "")
                desc = str(props.get("productName") or props.get("name") or props.get("title") or "")
                pack_size = str(props.get("weight") or props.get("packSize") or props.get("unitSize") or "")
                uom = "EA"

                prices = props.get("priceInfo") or props.get("pricing") or {}
                pack_price = float(
                    prices.get("finalPrice")
                    or prices.get("salePrice")
                    or prices.get("price")
                    or props.get("finalPrice")
                    or 0
                )

                if not sku or pack_price <= 0:
                    continue

                net_qty, uom = self._parse_weight(pack_size)
                spec = self.map_sku(sku)

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
                    ing_id=spec.ing_id if spec else ing.ing_id,
                    canonical_name=spec.canonical_name if spec else ing.name,
                    mapped_by="scraper",
                    date=today,
                ))
            except (TypeError, ValueError):
                continue

        return rows

    def _parse_dom(self, page, ing: Ingredient) -> list[DumpRow]:
        today = date.today().isoformat()
        rows = []
        try:
            cards = page.query_selector_all(
                ".sc-pc-item, .product-card, [data-testid='item-card'], .product-tile"
            )
            for card in cards[:15]:
                try:
                    sku = _text(card, "[data-item-id], .item-number")
                    desc = _text(card, ".product-title, h3, h4, .name")
                    price_str = _text(card, ".price-info__price, .actual-price, .price")
                    weight = _text(card, ".weight, .unit-size, .pack-size")
                    price = _parse_price(price_str)
                    if not desc or price <= 0:
                        continue
                    net_qty, uom = self._parse_weight(weight)
                    spec = self.map_sku(sku) if sku else None
                    rows.append(DumpRow(
                        vendor=self.vendor_name,
                        invoice_no=f"SCRAPER_{today}",
                        sku=sku or "DOM",
                        vendor_description=desc,
                        pack_size=weight,
                        pack_unit=uom,
                        pack_price=price,
                        net_qty=net_qty,
                        uom=uom,
                        cpu=self.calculate_cpu(price, net_qty),
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

    @staticmethod
    def _parse_weight(s: str) -> tuple[float, str]:
        """Parse '50 LB', '4/5 LB', '12 OZ' → (net_qty, uom)."""
        if not s:
            return 1.0, "EA"
        s = s.strip().upper()
        m = re.match(r"(\d+)\s*/\s*(\d+\.?\d*)\s*(LB|OZ|EA|GAL|CT)", s)
        if m:
            qty = float(m.group(1)) * float(m.group(2))
            return qty, m.group(3)
        m = re.match(r"(\d+\.?\d*)\s*(LB|OZ|EA|GAL|CT)", s)
        if m:
            return float(m.group(1)), m.group(2)
        return 1.0, "EA"


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
