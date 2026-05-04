"""Event cost report generator — reads recipe DB and DUMP, scales to guest count."""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import gspread
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from .models import DumpRow, Ingredient
from .analysis import get_best_vendor, VendorPrice


@dataclass
class RecipeLineCost:
    ing_id: str
    canonical_name: str
    base_qty: float
    unit: str
    scaled_qty: float
    best_vendor: str
    cpu: float
    line_cost: float
    last_updated: str
    missing_price: bool = False


@dataclass
class RecipeCost:
    recipe_name: str
    concept: str           # "HC" | "PH" | "TT" | "Other"
    base_servings: int
    scaled_servings: int
    scale_factor: float
    lines: list[RecipeLineCost] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return sum(l.line_cost for l in self.lines)

    @property
    def cost_per_serving(self) -> float:
        return self.subtotal / self.scaled_servings if self.scaled_servings else 0.0

    @property
    def missing_prices(self) -> list[str]:
        return [l.canonical_name for l in self.lines if l.missing_price]


@dataclass
class EventReport:
    event_name: str
    guests: int
    generated: str
    recipes: list[RecipeCost] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(r.subtotal for r in self.recipes)

    @property
    def cost_per_guest(self) -> float:
        return self.total_cost / self.guests if self.guests else 0.0

    @property
    def cost_by_category(self) -> dict[str, float]:
        # Placeholder — categories need to come from ingredient registry
        return {}

    @property
    def cost_by_vendor(self) -> dict[str, float]:
        vendor_totals: dict[str, float] = {}
        for recipe in self.recipes:
            for line in recipe.lines:
                if not line.missing_price:
                    vendor_totals[line.best_vendor] = (
                        vendor_totals.get(line.best_vendor, 0.0) + line.line_cost
                    )
        return dict(sorted(vendor_totals.items(), key=lambda x: -x[1]))


def generate_event_report(
    event_name: str,
    guests: int,
    dump_rows: list[DumpRow],
    ingredients: list[Ingredient],
    ss: Optional[gspread.Spreadsheet] = None,
    vendor_strategy: str = "best",
) -> EventReport:
    """
    Build a full event cost report by reading 05_SYS_RECIPES_DB and scaling
    each recipe to the target guest count.
    """
    from .sheets import get_recipe_db_rows

    report = EventReport(
        event_name=event_name,
        guests=guests,
        generated=date.today().isoformat(),
    )

    # Build ING_ID → ingredient lookup
    ing_map = {i.ing_id: i for i in ingredients}

    # Read recipe lines from 05_SYS_RECIPES_DB
    try:
        recipe_rows = get_recipe_db_rows(ss) if ss else []
    except Exception as e:
        report.warnings.append(f"Could not read recipe DB: {e}")
        recipe_rows = []

    if not recipe_rows:
        report.warnings.append(
            "05_SYS_RECIPES_DB is empty or could not be read. "
            "Add recipes to the sheet to generate a cost report."
        )
        return report

    # Determine column names (headers vary by sheet version)
    def col(row: dict, *keys: str) -> str:
        for k in keys:
            for attempt in [k, k.lower(), k.upper(), k.replace("_", " "), k.replace(" ", "_")]:
                if attempt in row:
                    return str(row[attempt]).strip()
        return ""

    def fcol(row: dict, *keys: str) -> float:
        v = col(row, *keys)
        try:
            return float(v.replace("$", "").replace(",", "")) if v else 0.0
        except ValueError:
            return 0.0

    # Group rows by recipe name
    recipes_dict: dict[str, list[dict]] = {}
    for row in recipe_rows:
        recipe_name = col(row, "Recipe_Name", "Recipe", "recipe_name", "Name")
        if recipe_name:
            recipes_dict.setdefault(recipe_name, []).append(row)

    stale_days = 14

    for recipe_name, lines in recipes_dict.items():
        if not lines:
            continue

        first = lines[0]
        base_servings_str = col(first, "Base_Servings", "Servings", "base_servings", "Batch_Size")
        try:
            base_servings = int(float(base_servings_str)) if base_servings_str else 10
        except ValueError:
            base_servings = 10

        base_servings = max(base_servings, 1)
        scale_factor = guests / base_servings
        concept = _infer_concept(recipe_name)

        recipe_cost = RecipeCost(
            recipe_name=recipe_name,
            concept=concept,
            base_servings=base_servings,
            scaled_servings=guests,
            scale_factor=scale_factor,
        )

        for line in lines:
            ing_id = col(line, "ING_ID", "Ing_ID", "ing_id")
            ing_name = col(line, "Canonical_Name", "Ingredient", "Name", "canonical_name")
            qty_str = col(line, "Qty", "Quantity", "qty", "Base_Qty")
            unit = col(line, "UOM", "Unit", "uom")

            if not ing_id and not ing_name:
                continue

            try:
                base_qty = float(qty_str.replace(",", "")) if qty_str else 0.0
            except ValueError:
                base_qty = 0.0

            scaled_qty = round(base_qty * scale_factor, 4)

            # Find best vendor price
            if vendor_strategy == "best":
                best = get_best_vendor(ing_id, dump_rows) if ing_id else None
            else:
                # Force a specific vendor
                slug = vendor_strategy
                from .models import VENDOR_NAMES
                forced_vendor = VENDOR_NAMES.get(slug, slug)
                best = _get_vendor_price(ing_id, forced_vendor, dump_rows)

            if best:
                line_cost = round(scaled_qty * best.cpu, 2)
                # Check price staleness
                if best.date < _cutoff_date(stale_days):
                    report.warnings.append(
                        f"{ing_name or ing_id}: price from {best.vendor} is "
                        f"from {best.date} (>{stale_days} days old)"
                    )
                recipe_cost.lines.append(RecipeLineCost(
                    ing_id=ing_id,
                    canonical_name=ing_name or (ing_map.get(ing_id, Ingredient("", "")).name),
                    base_qty=base_qty,
                    unit=unit,
                    scaled_qty=scaled_qty,
                    best_vendor=best.vendor,
                    cpu=best.cpu,
                    line_cost=line_cost,
                    last_updated=best.date,
                ))
            else:
                report.warnings.append(
                    f"{ing_name or ing_id}: no price data — excluded from total"
                )
                recipe_cost.lines.append(RecipeLineCost(
                    ing_id=ing_id,
                    canonical_name=ing_name or ing_id,
                    base_qty=base_qty,
                    unit=unit,
                    scaled_qty=scaled_qty,
                    best_vendor="NO PRICE",
                    cpu=0.0,
                    line_cost=0.0,
                    last_updated="",
                    missing_price=True,
                ))

        report.recipes.append(recipe_cost)

    return report


def _get_vendor_price(
    ing_id: str,
    vendor_name: str,
    dump_rows: list[DumpRow],
) -> Optional[VendorPrice]:
    """Get latest price for a specific vendor."""
    from .analysis import VendorPrice
    best_row: Optional[DumpRow] = None
    for row in dump_rows:
        if row.ing_id == ing_id and row.vendor == vendor_name:
            if best_row is None or row.date > best_row.date:
                best_row = row
    if not best_row:
        return None
    return VendorPrice(
        vendor=best_row.vendor, sku=best_row.sku,
        description=best_row.vendor_description,
        pack_size=best_row.pack_size, pack_unit=best_row.pack_unit,
        pack_price=best_row.pack_price, net_qty=best_row.net_qty,
        uom=best_row.uom, cpu=best_row.cpu, date=best_row.date,
    )


def _infer_concept(recipe_name: str) -> str:
    upper = recipe_name.upper()
    if "HC" in upper or "HAPPY CHICK" in upper:
        return "HC"
    if "PH" in upper or "PIE HOLE" in upper:
        return "PH"
    if "TT" in upper or "TIKI TACO" in upper or "TACO" in upper:
        return "TT"
    return "Other"


def _cutoff_date(days: int) -> str:
    from datetime import timedelta
    return (date.today() - timedelta(days=days)).isoformat()


# ── Rich terminal renderer ─────────────────────────────────────────────────────

def render_terminal(report: EventReport, console: Console) -> None:
    console.print(Panel(
        f"[bold]CREATIVE AFFAIRS CATERING — EVENT COST REPORT[/bold]\n"
        f"Event:        [cyan]{report.event_name}[/cyan]\n"
        f"Guest Count:  [yellow]{report.guests:,}[/yellow]\n"
        f"Generated:    {report.generated}",
        box=box.DOUBLE,
    ))

    if not report.recipes:
        console.print("[yellow]No recipe data found.[/yellow]")
        return

    for recipe in report.recipes:
        t = Table(
            title=(
                f"{recipe.recipe_name}  "
                f"(base {recipe.base_servings} servings → ×{recipe.scale_factor:.1f} → "
                f"{recipe.scaled_servings:,} guests)"
            ),
            box=box.ROUNDED,
        )
        t.add_column("Ingredient")
        t.add_column("Qty (scaled)", justify="right")
        t.add_column("UOM")
        t.add_column("Best Vendor", style="cyan")
        t.add_column("CPU", justify="right")
        t.add_column("Line Total", justify="right", style="bold")

        for line in recipe.lines:
            if line.missing_price:
                t.add_row(
                    line.canonical_name,
                    f"{line.scaled_qty:,.2f}",
                    line.unit,
                    "[red]NO PRICE[/red]",
                    "—",
                    "[red]$0.00[/red]",
                )
            else:
                t.add_row(
                    line.canonical_name,
                    f"{line.scaled_qty:,.2f}",
                    line.unit,
                    line.best_vendor,
                    f"${line.cpu:.4f}",
                    f"${line.line_cost:,.2f}",
                )

        console.print(t)
        console.print(
            f"  Recipe Subtotal: [bold green]${recipe.subtotal:,.2f}[/bold green]   "
            f"Cost/Guest: [bold]${recipe.cost_per_serving:.2f}[/bold]\n"
        )

    # Vendor spend summary
    vendor_totals = report.cost_by_vendor
    if vendor_totals:
        vt = Table(title="Vendor Spend Summary", box=box.SIMPLE)
        vt.add_column("Vendor", style="cyan")
        vt.add_column("Total", justify="right", style="bold")
        for vendor, total in vendor_totals.items():
            vt.add_row(vendor, f"${total:,.2f}")
        console.print(vt)

    console.print(Panel(
        f"[bold green]TOTAL EVENT COST:   ${report.total_cost:,.2f}[/bold green]\n"
        f"[bold]COST PER GUEST:     ${report.cost_per_guest:.2f}[/bold]",
        box=box.DOUBLE,
    ))

    if report.warnings:
        console.print("\n[yellow]⚠ WARNINGS:[/yellow]")
        for w in report.warnings:
            console.print(f"  · {w}")


# ── HTML renderer ──────────────────────────────────────────────────────────────

def render_html(report: EventReport) -> str:
    recipes_html = ""
    for recipe in report.recipes:
        rows_html = ""
        for line in recipe.lines:
            style = 'color:red' if line.missing_price else ''
            rows_html += (
                f"<tr style='{style}'>"
                f"<td>{line.canonical_name}</td>"
                f"<td>{line.scaled_qty:,.2f}</td>"
                f"<td>{line.unit}</td>"
                f"<td>{'NO PRICE' if line.missing_price else line.best_vendor}</td>"
                f"<td>{'—' if line.missing_price else f'${line.cpu:.4f}'}</td>"
                f"<td><strong>{'$0.00' if line.missing_price else f'${line.line_cost:,.2f}'}</strong></td>"
                f"</tr>"
            )

        recipes_html += f"""
        <div class="recipe-section">
          <h3>{recipe.recipe_name}
            <small>(base {recipe.base_servings} → ×{recipe.scale_factor:.1f} → {recipe.scaled_servings:,} guests)</small>
          </h3>
          <table class="price-table">
            <thead>
              <tr><th>Ingredient</th><th>Qty (scaled)</th><th>UOM</th>
                  <th>Best Vendor</th><th>CPU</th><th>Line Total</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
          <p class="subtotal">Subtotal: <strong>${recipe.subtotal:,.2f}</strong>
             &nbsp;&nbsp; Cost/Guest: <strong>${recipe.cost_per_serving:.2f}</strong></p>
        </div>
        """

    vendor_rows = "".join(
        f"<tr><td>{v}</td><td>${t:,.2f}</td></tr>"
        for v, t in report.cost_by_vendor.items()
    )

    warnings_html = ""
    if report.warnings:
        items = "".join(f"<li>{w}</li>" for w in report.warnings)
        warnings_html = f"<div class='warnings'><h4>⚠ Warnings</h4><ul>{items}</ul></div>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{report.event_name} — Cost Report</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 0 auto; padding: 20px; }}
  h1 {{ color: #333; border-bottom: 2px solid #333; }}
  .meta {{ background: #f5f5f5; padding: 10px 20px; border-radius: 4px; margin-bottom: 20px; }}
  .price-table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; }}
  .price-table th {{ background: #333; color: white; padding: 6px 10px; text-align: left; }}
  .price-table td {{ padding: 5px 10px; border-bottom: 1px solid #eee; }}
  .price-table tr:nth-child(even) {{ background: #fafafa; }}
  .subtotal {{ text-align: right; font-size: 1.05em; color: #2a7a2a; }}
  .recipe-section {{ margin-bottom: 30px; }}
  .totals {{ background: #e8f5e9; padding: 15px 25px; border-radius: 4px; font-size: 1.2em; }}
  .vendor-table {{ width: 400px; border-collapse: collapse; }}
  .vendor-table td {{ padding: 4px 10px; border-bottom: 1px solid #ddd; }}
  .warnings {{ background: #fff3cd; padding: 10px 20px; border-radius: 4px; margin-top: 20px; }}
  @media print {{ .no-print {{ display:none; }} body {{ max-width: 100%; }} }}
</style>
</head>
<body>
<h1>Creative Affairs Catering — Event Cost Report</h1>
<div class="meta">
  <strong>Event:</strong> {report.event_name} &nbsp;|&nbsp;
  <strong>Guests:</strong> {report.guests:,} &nbsp;|&nbsp;
  <strong>Generated:</strong> {report.generated}
</div>

{recipes_html}

<h3>Vendor Spend Summary</h3>
<table class="vendor-table">
  <thead><tr><th>Vendor</th><th>Total</th></tr></thead>
  <tbody>{vendor_rows}</tbody>
</table>

<div class="totals" style="margin-top:20px;">
  TOTAL EVENT COST: <strong>${report.total_cost:,.2f}</strong><br>
  COST PER GUEST: <strong>${report.cost_per_guest:.2f}</strong>
</div>

{warnings_html}
</body>
</html>"""
