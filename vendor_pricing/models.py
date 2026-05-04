from dataclasses import dataclass, field
from datetime import date
from typing import Optional


VENDOR_NAMES = {
    "pfg": "PFG",
    "sysco": "Sysco",
    "usfoods": "US Foods",
    "samsclub": "Sam's Club",
    "walmart": "Walmart",
    "brothers": "Brothers Produce",
    "chefs_produce": "Chefs Produce",
    "chef_store": "Chef Store",
    "restaurant_depot": "Restaurant Depot",
    "sprouts": "Sprouts",
}

ALL_VENDORS = list(VENDOR_NAMES.keys())


@dataclass
class DumpRow:
    """Matches the exact column schema of 01_VENDOR_PRICING_DUMP."""
    vendor: str               # "PFG", "Sysco", "Sam's Club", etc.
    invoice_no: str           # e.g. "SCRAPER_2026-05-04" or real invoice number
    sku: str
    vendor_description: str
    pack_size: str
    pack_unit: str
    pack_price: float
    net_qty: float
    uom: str
    cpu: float                # pack_price / net_qty (cost per unit)
    ing_id: str               # ING-XXXX canonical key
    canonical_name: str
    mapped_by: str            # "scraper" | "manual" | "csv"
    notes: str = ""
    date: str = field(default_factory=lambda: date.today().isoformat())
    row_id: str = ""          # auto-assigned VPD-XXXX when writing to sheet

    def to_sheet_row(self) -> list:
        """Returns ordered list matching DUMP column order."""
        return [
            self.row_id,
            self.date,
            self.vendor,
            self.invoice_no,
            self.sku,
            self.vendor_description,
            self.pack_size,
            self.pack_unit,
            self.pack_price,
            self.net_qty,
            self.uom,
            round(self.cpu, 4),
            self.ing_id,
            self.canonical_name,
            self.mapped_by,
            self.notes,
        ]

    @classmethod
    def from_sheet_row(cls, row: list) -> "DumpRow":
        """Parse a row read back from the DUMP tab."""
        def safe_float(v):
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0

        return cls(
            row_id=row[0] if len(row) > 0 else "",
            date=row[1] if len(row) > 1 else "",
            vendor=row[2] if len(row) > 2 else "",
            invoice_no=row[3] if len(row) > 3 else "",
            sku=row[4] if len(row) > 4 else "",
            vendor_description=row[5] if len(row) > 5 else "",
            pack_size=row[6] if len(row) > 6 else "",
            pack_unit=row[7] if len(row) > 7 else "",
            pack_price=safe_float(row[8]) if len(row) > 8 else 0.0,
            net_qty=safe_float(row[9]) if len(row) > 9 else 0.0,
            uom=row[10] if len(row) > 10 else "",
            cpu=safe_float(row[11]) if len(row) > 11 else 0.0,
            ing_id=row[12] if len(row) > 12 else "",
            canonical_name=row[13] if len(row) > 13 else "",
            mapped_by=row[14] if len(row) > 14 else "",
            notes=row[15] if len(row) > 15 else "",
        )


@dataclass
class Ingredient:
    """A canonical ingredient from 02_INGREDIENT_REGISTRY."""
    ing_id: str
    name: str
    category: str = ""
    default_unit: str = ""
    active_cpu: float = 0.0
    approved_vendor: str = ""


@dataclass
class SpecOption:
    """A SKU→ING_ID mapping from 03_SPEC_SELECTION."""
    vendor: str
    sku: str
    ing_id: str
    canonical_name: str
    pack_size: str = ""
