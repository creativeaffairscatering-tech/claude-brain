"""Google Sheets API layer — all reads and writes go through this module."""

import os
import re
from pathlib import Path
from typing import Optional

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from .models import DumpRow, Ingredient, SpecOption

load_dotenv(Path(__file__).parent.parent / ".env")

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID", "1vVhrW3j2aKXT5_UaaxYY6ZIZ673a9vO2iHmsIiNBED0"
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Tab names in the spreadsheet
TAB_DUMP = "01_VENDOR_PRICING_DUMP"
TAB_COMPARE = "01A_VENDOR_COMPARE_VIEW"
TAB_COMPARE_EXTENDED = "01B_MULTI_VENDOR_COMPARE"
TAB_REGISTRY = "02_INGREDIENT_REGISTRY"
TAB_SPEC = "03_SPEC_SELECTION"
TAB_RECIPES_DB = "05_SYS_RECIPES_DB"
TAB_BUILDS_DB = "06_SYS_BUILD_DB"

ALL_VENDOR_LABELS = [
    "PFG", "Sysco", "US Foods", "Sam's Club", "Walmart",
    "Brothers Produce", "Chefs Produce", "Chef Store",
    "Restaurant Depot", "Sprouts",
]


def _get_client() -> gspread.Client:
    sa_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    sa_file = str(Path(sa_file).expanduser()) if sa_file else ""

    oauth_file = os.environ.get("GOOGLE_OAUTH_CREDENTIALS_FILE", "")
    oauth_file = str(Path(oauth_file).expanduser()) if oauth_file else ""

    if sa_file and Path(sa_file).exists():
        creds = Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return gspread.authorize(creds)

    if oauth_file and Path(oauth_file).exists():
        return gspread.oauth(credentials_filename=oauth_file)

    # Fall back to gspread's default local credentials
    return gspread.oauth()


def get_spreadsheet() -> gspread.Spreadsheet:
    client = _get_client()
    return client.open_by_key(SPREADSHEET_ID)


def list_tabs(spreadsheet: Optional[gspread.Spreadsheet] = None) -> list[str]:
    ss = spreadsheet or get_spreadsheet()
    return [ws.title for ws in ss.worksheets()]


# ── DUMP ──────────────────────────────────────────────────────────────────────

def get_all_dump_rows(spreadsheet: Optional[gspread.Spreadsheet] = None) -> list[DumpRow]:
    """Read all data rows from the DUMP tab (skips header)."""
    ss = spreadsheet or get_spreadsheet()
    ws = ss.worksheet(TAB_DUMP)
    all_rows = ws.get_all_values()
    if len(all_rows) < 2:
        return []
    return [DumpRow.from_sheet_row(r) for r in all_rows[1:] if r and r[0]]


def _next_vpd_id(existing: list[DumpRow]) -> int:
    """Return the next sequential VPD number."""
    nums = []
    for row in existing:
        m = re.match(r"VPD-(\d+)", row.row_id)
        if m:
            nums.append(int(m.group(1)))
    return max(nums, default=0) + 1


def append_dump_rows(
    new_rows: list[DumpRow],
    spreadsheet: Optional[gspread.Spreadsheet] = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Append new price rows to the DUMP tab with dedup logic.

    Dedup rules (matching the sheet's own rules):
      - Same Vendor + SKU + same price → skip
      - Same Vendor + SKU + new price → append (keeps history)
      - New Vendor + SKU → append

    Returns (appended_count, skipped_count).
    """
    ss = spreadsheet or get_spreadsheet()
    existing = get_all_dump_rows(ss)

    # Build dedup index: (vendor, sku) → set of prices
    existing_index: dict[tuple, set] = {}
    for row in existing:
        key = (row.vendor.strip().lower(), row.sku.strip().lower())
        existing_index.setdefault(key, set()).add(round(row.pack_price, 4))

    next_id = _next_vpd_id(existing)
    to_append: list[list] = []
    skipped = 0

    for row in new_rows:
        key = (row.vendor.strip().lower(), row.sku.strip().lower())
        price = round(row.pack_price, 4)

        if key in existing_index and price in existing_index[key]:
            skipped += 1
            continue

        row.row_id = f"VPD-{next_id:04d}"
        next_id += 1
        to_append.append(row.to_sheet_row())

    if not dry_run and to_append:
        ws = ss.worksheet(TAB_DUMP)
        ws.append_rows(to_append, value_input_option="USER_ENTERED")

    return len(to_append), skipped


# ── INGREDIENT REGISTRY ───────────────────────────────────────────────────────

def get_ingredient_registry(
    spreadsheet: Optional[gspread.Spreadsheet] = None,
) -> list[Ingredient]:
    """Read 02_INGREDIENT_REGISTRY. Returns all active ingredients."""
    ss = spreadsheet or get_spreadsheet()
    ws = ss.worksheet(TAB_REGISTRY)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []

    # Find column indices from header row
    header = [h.strip().lower() for h in rows[0]]
    def col(name: str) -> int:
        for alt in [name, name.replace("_", " "), name.replace(" ", "_")]:
            if alt in header:
                return header.index(alt)
        return -1

    id_col = col("ing_id")
    name_col = col("canonical_name") if col("canonical_name") >= 0 else col("name")
    cat_col = col("category")
    unit_col = col("default_unit") if col("default_unit") >= 0 else col("uom")
    cpu_col = col("active_cpu") if col("active_cpu") >= 0 else col("cpu")
    vendor_col = col("approved_vendor")

    ingredients = []
    for row in rows[1:]:
        if not row or not (id_col >= 0 and id_col < len(row) and row[id_col]):
            continue
        def v(c: int) -> str:
            return row[c].strip() if c >= 0 and c < len(row) else ""
        def fv(c: int) -> float:
            try:
                return float(v(c).replace("$", "").replace(",", ""))
            except ValueError:
                return 0.0
        ingredients.append(Ingredient(
            ing_id=v(id_col),
            name=v(name_col),
            category=v(cat_col),
            default_unit=v(unit_col),
            active_cpu=fv(cpu_col),
            approved_vendor=v(vendor_col),
        ))
    return ingredients


# ── SPEC SELECTION (SKU → ING_ID map) ────────────────────────────────────────

def get_spec_options(
    spreadsheet: Optional[gspread.Spreadsheet] = None,
) -> list[SpecOption]:
    """Read 03_SPEC_SELECTION for SKU→ING_ID mappings."""
    ss = spreadsheet or get_spreadsheet()
    try:
        ws = ss.worksheet(TAB_SPEC)
    except gspread.WorksheetNotFound:
        return []
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []

    header = [h.strip().lower() for h in rows[0]]
    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    vendor_col = col("vendor")
    sku_col = col("sku")
    ing_col = col("ing_id")
    name_col = col("canonical_name")
    pack_col = col("pack_size")

    specs = []
    for row in rows[1:]:
        if not row or not (sku_col >= 0 and sku_col < len(row) and row[sku_col]):
            continue
        def v(c: int) -> str:
            return row[c].strip() if c >= 0 and c < len(row) else ""
        specs.append(SpecOption(
            vendor=v(vendor_col),
            sku=v(sku_col),
            ing_id=v(ing_col),
            canonical_name=v(name_col),
            pack_size=v(pack_col),
        ))
    return specs


def build_sku_map(
    spreadsheet: Optional[gspread.Spreadsheet] = None,
) -> dict[tuple[str, str], SpecOption]:
    """Returns {(vendor_lower, sku_lower): SpecOption} for fast lookup."""
    specs = get_spec_options(spreadsheet)
    return {(s.vendor.lower(), s.sku.lower()): s for s in specs}


# ── RECIPE / BUILD DB ─────────────────────────────────────────────────────────

def get_recipe_db_rows(
    spreadsheet: Optional[gspread.Spreadsheet] = None,
) -> list[dict]:
    """Read 05_SYS_RECIPES_DB. Returns list of row dicts."""
    ss = spreadsheet or get_spreadsheet()
    ws = ss.worksheet(TAB_RECIPES_DB)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0]]
    return [dict(zip(header, row)) for row in rows[1:] if any(row)]


def get_build_db_rows(
    spreadsheet: Optional[gspread.Spreadsheet] = None,
) -> list[dict]:
    """Read 06_SYS_BUILD_DB. Returns list of row dicts."""
    ss = spreadsheet or get_spreadsheet()
    ws = ss.worksheet(TAB_BUILDS_DB)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0]]
    return [dict(zip(header, row)) for row in rows[1:] if any(row)]


# ── MULTI-VENDOR COMPARE TAB ──────────────────────────────────────────────────

def write_extended_compare_tab(
    spreadsheet: Optional[gspread.Spreadsheet] = None,
    dry_run: bool = False,
) -> dict:
    """
    Create or refresh 01B_MULTI_VENDOR_COMPARE with one row per canonical
    ingredient and one column per vendor showing their latest CPU.

    Returns a summary dict with counts.
    """
    ss = spreadsheet or get_spreadsheet()
    dump_rows = get_all_dump_rows(ss)
    ingredients = get_ingredient_registry(ss)

    # Build: (ing_id, vendor) → most recent CPU
    from collections import defaultdict
    latest: dict[tuple[str, str], tuple[str, float]] = {}  # → (date, cpu)
    for row in dump_rows:
        if not row.ing_id or not row.vendor:
            continue
        key = (row.ing_id, row.vendor)
        if key not in latest or row.date > latest[key][0]:
            latest[key] = (row.date, row.cpu)

    vendors = ALL_VENDOR_LABELS
    header = ["ING_ID", "Canonical_Name", "Category"] + vendors + [
        "BEST_CPU", "BEST_VENDOR", "Savings_vs_Worst"
    ]

    table_rows = [header]
    for ing in ingredients:
        row_data = [ing.ing_id, ing.name, ing.category]
        cpus: dict[str, float] = {}
        for v in vendors:
            key = (ing.ing_id, v)
            if key in latest:
                cpu = latest[key][1]
                cpus[v] = cpu
                row_data.append(round(cpu, 4))
            else:
                row_data.append("")

        if cpus:
            best_vendor = min(cpus, key=cpus.__getitem__)
            best_cpu = round(cpus[best_vendor], 4)
            worst_cpu = max(cpus.values())
            savings = round(worst_cpu - best_cpu, 4)
        else:
            best_vendor = ""
            best_cpu = ""
            savings = ""

        row_data += [best_cpu, best_vendor, savings]
        table_rows.append(row_data)

    if not dry_run:
        try:
            ws = ss.worksheet(TAB_COMPARE_EXTENDED)
            ws.clear()
        except gspread.WorksheetNotFound:
            ws = ss.add_worksheet(
                title=TAB_COMPARE_EXTENDED, rows=len(table_rows) + 10, cols=len(header)
            )
        ws.update(table_rows, value_input_option="USER_ENTERED")

        # Bold the header row
        ws.format("A1:Z1", {"textFormat": {"bold": True}})

    return {
        "ingredients": len(ingredients),
        "vendors": len(vendors),
        "rows_written": len(table_rows) - 1,
        "dump_rows_read": len(dump_rows),
    }
