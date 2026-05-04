"""Manual entry and CSV import for local vendors (Brothers, Chefs Produce, Sprouts, etc.)."""

import csv
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from .models import DumpRow, Ingredient, VENDOR_NAMES


@dataclass
class ImportResult:
    rows_added: int
    rows_skipped: int
    errors: list[str]


def calculate_cpu(pack_price: float, net_qty: float) -> float:
    """Cost per unit = pack_price / net_qty."""
    if net_qty <= 0:
        return 0.0
    return round(pack_price / net_qty, 4)


def manual_entry(
    vendor_slug: str,
    ingredients: list[Ingredient],
    ing_filter: Optional[str] = None,
    invoice_ref: Optional[str] = None,
) -> list[DumpRow]:
    """
    Interactive CLI prompt — ask user for price per ingredient.
    Returns list of DumpRow objects ready to append.

    Skips ingredients where user presses Enter (no price).
    """
    vendor_display = VENDOR_NAMES.get(vendor_slug, vendor_slug)
    inv_ref = invoice_ref or f"MANUAL_{date.today().isoformat()}"
    today = date.today().isoformat()

    filtered = ingredients
    if ing_filter:
        q = ing_filter.lower()
        filtered = [i for i in ingredients if q in i.name.lower()]

    rows: list[DumpRow] = []
    print(f"\nManual price entry for: {vendor_display}")
    print("Press Enter to skip an ingredient. Type 'q' to quit.\n")

    for ing in filtered:
        try:
            raw = input(
                f"  {ing.ing_id} {ing.name} [{ing.default_unit}] — pack price (or Enter to skip): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw.lower() == "q":
            break
        if not raw:
            continue

        try:
            pack_price = float(raw.replace("$", "").replace(",", ""))
        except ValueError:
            print(f"    Invalid price: {raw!r} — skipping")
            continue

        net_qty_raw = input(
            f"    Net qty (number of {ing.default_unit}s per pack, e.g. '50'): "
        ).strip()
        uom_raw = input(
            f"    UOM [{ing.default_unit}]: "
        ).strip() or ing.default_unit

        try:
            net_qty = float(net_qty_raw) if net_qty_raw else 1.0
        except ValueError:
            net_qty = 1.0

        pack_size_raw = input("    Pack size label (e.g. '50 LB', optional): ").strip()
        sku_raw = input("    SKU / item# (optional): ").strip() or "MANUAL"
        desc_raw = input("    Description (optional): ").strip() or ing.name

        rows.append(DumpRow(
            vendor=vendor_display,
            invoice_no=inv_ref,
            sku=sku_raw,
            vendor_description=desc_raw,
            pack_size=pack_size_raw,
            pack_unit=uom_raw,
            pack_price=pack_price,
            net_qty=net_qty,
            uom=uom_raw,
            cpu=calculate_cpu(pack_price, net_qty),
            ing_id=ing.ing_id,
            canonical_name=ing.name,
            mapped_by="manual",
            date=today,
        ))

    return rows


def import_csv(
    vendor_slug: str,
    filepath: str,
    ingredients: list[Ingredient],
    invoice_ref: Optional[str] = None,
) -> tuple[list[DumpRow], ImportResult]:
    """
    Import prices from a CSV file for a manual-entry vendor.

    Expected CSV columns (case-insensitive, extra columns ignored):
      sku, description, pack_size, pack_price, net_qty, uom
      Optional: ing_id, canonical_name, date, notes

    The importer auto-matches ingredient names if ing_id is absent.
    """
    vendor_display = VENDOR_NAMES.get(vendor_slug, vendor_slug)
    inv_ref = invoice_ref or f"CSV_{date.today().isoformat()}"
    today = date.today().isoformat()

    # Build name → ING_ID lookup for auto-matching
    name_map = {i.name.lower(): i for i in ingredients}

    path = Path(filepath)
    if not path.exists():
        return [], ImportResult(0, 0, [f"File not found: {filepath}"])

    rows: list[DumpRow] = []
    errors: list[str] = []
    skipped = 0

    def norm(h: str) -> str:
        return h.strip().lower().replace(" ", "_")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return [], ImportResult(0, 0, ["CSV has no header row"])

        # Normalize header names
        normalized_headers = {norm(k): k for k in reader.fieldnames}

        def get(row: dict, *keys: str) -> str:
            for k in keys:
                orig = normalized_headers.get(k)
                if orig and orig in row:
                    return str(row[orig]).strip()
            return ""

        for line_num, raw_row in enumerate(reader, start=2):
            try:
                sku = get(raw_row, "sku", "item_no", "item#") or "UNKNOWN"
                desc = get(raw_row, "description", "desc", "product_name", "name")
                pack_size = get(raw_row, "pack_size", "pack", "size")
                pack_price_str = get(raw_row, "pack_price", "price", "case_price", "total_price")
                net_qty_str = get(raw_row, "net_qty", "qty", "quantity", "net_quantity")
                uom = get(raw_row, "uom", "unit", "unit_of_measure") or "EA"
                ing_id = get(raw_row, "ing_id")
                canonical = get(raw_row, "canonical_name", "canonical")
                row_date = get(raw_row, "date", "invoice_date") or today
                notes = get(raw_row, "notes", "note")

                if not pack_price_str:
                    errors.append(f"Line {line_num}: missing price — skipped")
                    skipped += 1
                    continue

                pack_price = float(pack_price_str.replace("$", "").replace(",", ""))
                net_qty = float(net_qty_str.replace(",", "")) if net_qty_str else 1.0

                # Auto-match ingredient if ing_id not supplied
                if not ing_id:
                    match = name_map.get(desc.lower()) or name_map.get(canonical.lower())
                    if match:
                        ing_id = match.ing_id
                        canonical = match.name
                    else:
                        ing_id = "UNMAPPED"
                        errors.append(
                            f"Line {line_num}: '{desc}' not matched to an ingredient — "
                            "set ing_id manually or add it to the registry"
                        )

                rows.append(DumpRow(
                    vendor=vendor_display,
                    invoice_no=inv_ref,
                    sku=sku,
                    vendor_description=desc,
                    pack_size=pack_size,
                    pack_unit=uom,
                    pack_price=pack_price,
                    net_qty=net_qty,
                    uom=uom,
                    cpu=calculate_cpu(pack_price, net_qty),
                    ing_id=ing_id,
                    canonical_name=canonical,
                    mapped_by="csv",
                    notes=notes,
                    date=row_date,
                ))

            except (ValueError, KeyError) as e:
                errors.append(f"Line {line_num}: {e}")
                skipped += 1

    return rows, ImportResult(len(rows), skipped, errors)
