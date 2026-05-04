"""
vp — Vendor Pricing CLI for Creative Affairs Catering

Usage:
  vp auth                    Authorize Google Sheets access
  vp sheet check             Verify sheet connection and list tabs
  vp dump-status             Show DUMP row counts per vendor
  vp scrape                  Run automated vendor scrapers
  vp manual                  Manual price entry for local vendors
  vp import-csv              Import prices from a CSV file
  vp compare                 Compare prices for an ingredient across vendors
  vp best                    Best vendor per ingredient
  vp savings                 Top savings opportunities
  vp extend-compare          Create/refresh 01B_MULTI_VENDOR_COMPARE tab
  vp event report            Generate Longhorn Ballroom cost report
  vp web                     Start the local web dashboard
"""

import sys
import click
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel

console = Console()


# ── helpers ────────────────────────────────────────────────────────────────────

def _get_sheet():
    """Open the spreadsheet, exit with a helpful message on auth failure."""
    try:
        from .sheets import get_spreadsheet
        return get_spreadsheet()
    except Exception as e:
        console.print(f"[red]Could not connect to Google Sheets:[/red] {e}")
        console.print(
            "\n[yellow]Run [bold]vp auth[/bold] to set up credentials,[/yellow]"
            " then copy [bold].env.example[/bold] → [bold].env[/bold] and fill in"
            " GOOGLE_SERVICE_ACCOUNT_FILE and SPREADSHEET_ID."
        )
        sys.exit(1)


def _load_dump(ss=None):
    from .sheets import get_all_dump_rows
    ss = ss or _get_sheet()
    return get_all_dump_rows(ss), ss


def _load_registry(ss=None):
    from .sheets import get_ingredient_registry
    ss = ss or _get_sheet()
    return get_ingredient_registry(ss), ss


# ── root group ─────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Vendor Pricing Tracker — Creative Affairs Catering."""
    pass


# ── auth ───────────────────────────────────────────────────────────────────────

@cli.command()
def auth():
    """Authorize Google Sheets (opens browser for OAuth2 if no service account)."""
    try:
        from .sheets import get_spreadsheet
        ss = get_spreadsheet()
        console.print(f"[green]✓ Authorized.[/green] Spreadsheet: [bold]{ss.title}[/bold]")
    except Exception as e:
        console.print(f"[red]Auth failed:[/red] {e}")
        console.print(
            "\nEnsure GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_OAUTH_CREDENTIALS_FILE"
            " is set in your .env file."
        )
        sys.exit(1)


# ── sheet check ────────────────────────────────────────────────────────────────

@cli.command("sheet")
@click.argument("subcommand", default="check")
def sheet_cmd(subcommand):
    """Verify sheet connection and show tab list. Usage: vp sheet check"""
    if subcommand != "check":
        console.print(f"Unknown subcommand: {subcommand!r}. Try: vp sheet check")
        sys.exit(1)

    ss = _get_sheet()
    from .sheets import list_tabs, get_all_dump_rows, get_ingredient_registry
    tabs = list_tabs(ss)
    dump = get_all_dump_rows(ss)
    registry = get_ingredient_registry(ss)

    console.print(Panel(
        f"[bold green]✓ Connected[/bold green]\n"
        f"Spreadsheet: [cyan]{ss.title}[/cyan]\n"
        f"DUMP rows: [yellow]{len(dump)}[/yellow]   "
        f"Registry ingredients: [yellow]{len(registry)}[/yellow]",
        title="Google Sheets Status"
    ))

    t = Table(title="Tabs in Spreadsheet", box=box.SIMPLE)
    t.add_column("Tab Name")
    for tab in tabs:
        t.add_row(tab)
    console.print(t)


# ── dump-status ────────────────────────────────────────────────────────────────

@cli.command("dump-status")
def dump_status_cmd():
    """Show DUMP row counts and last-update date per vendor."""
    dump, _ = _load_dump()
    from .analysis import dump_status
    status = dump_status(dump)

    t = Table(title=f"Vendor Pricing Dump — {status['total_rows']} total rows", box=box.ROUNDED)
    t.add_column("Vendor", style="cyan")
    t.add_column("Rows", justify="right")
    t.add_column("Last Updated", style="yellow")

    for vendor, info in status["vendors"].items():
        t.add_row(vendor, str(info["rows"]), info["last_date"])

    console.print(t)


# ── scrape ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--vendor", default="all",
              help="Vendor slug: pfg|sysco|usfoods|samsclub|walmart|restaurant_depot|chef_store|all")
@click.option("--ingredient", default=None, help="Limit to one ingredient name")
@click.option("--dry-run", is_flag=True, help="Print rows without writing to sheet")
def scrape(vendor, ingredient, dry_run):
    """Run automated vendor scrapers and append results to the DUMP tab."""
    from .scrapers import get_scraper, SCRAPER_VENDORS

    if vendor == "all":
        slugs = SCRAPER_VENDORS
    else:
        slugs = [vendor]

    ss = _get_sheet()
    ingredients, _ = _load_registry(ss)
    if ingredient:
        ingredients = [i for i in ingredients if ingredient.lower() in i.name.lower()]
        if not ingredients:
            console.print(f"[red]No ingredient found matching: {ingredient!r}[/red]")
            sys.exit(1)

    total_added = 0
    total_skipped = 0

    for slug in slugs:
        scraper = get_scraper(slug)
        if scraper is None:
            console.print(f"[yellow]No auto-scraper for '{slug}' — use vp manual instead.[/yellow]")
            continue

        console.print(f"\n[cyan]Scraping {slug}...[/cyan]")
        try:
            rows = scraper.scrape(ingredients)
        except Exception as e:
            console.print(f"  [red]Error:[/red] {e}")
            continue

        if dry_run:
            t = Table(title=f"{slug} — {len(rows)} rows (dry run)", box=box.SIMPLE)
            t.add_column("Vendor")
            t.add_column("SKU")
            t.add_column("Description")
            t.add_column("CPU", justify="right")
            t.add_column("UOM")
            t.add_column("ING_ID")
            for r in rows[:25]:
                t.add_row(r.vendor, r.sku, r.vendor_description[:40],
                          f"${r.cpu:.4f}", r.uom, r.ing_id)
            if len(rows) > 25:
                t.add_row("...", f"(+{len(rows)-25} more)", "", "", "", "")
            console.print(t)
        else:
            from .sheets import append_dump_rows
            added, skipped = append_dump_rows(rows, ss)
            console.print(f"  [green]+{added} rows added[/green]  {skipped} skipped (duplicate)")
            total_added += added
            total_skipped += skipped

    if not dry_run:
        console.print(
            f"\n[bold green]Done.[/bold green] "
            f"Total: {total_added} added, {total_skipped} skipped."
        )


# ── manual ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--vendor", required=True,
              help="Vendor slug: brothers|chefs_produce|sprouts|restaurant_depot|chef_store|...")
@click.option("--ingredient", default=None, help="Filter to one ingredient name")
@click.option("--invoice", default=None, help="Invoice reference label")
@click.option("--dry-run", is_flag=True, help="Preview rows without writing")
def manual(vendor, ingredient, invoice, dry_run):
    """Interactive manual price entry for a vendor."""
    from .importer import manual_entry
    from .sheets import append_dump_rows

    ingredients, ss = _load_registry()

    rows = manual_entry(vendor, ingredients, ing_filter=ingredient, invoice_ref=invoice)

    if not rows:
        console.print("[yellow]No prices entered.[/yellow]")
        return

    if dry_run:
        _print_rows_table(rows, title=f"Preview — {len(rows)} rows (dry run)")
    else:
        added, skipped = append_dump_rows(rows, ss)
        console.print(
            f"[green]✓ {added} rows written to DUMP.[/green]  {skipped} skipped (duplicate)."
        )


# ── import-csv ─────────────────────────────────────────────────────────────────

@cli.command("import-csv")
@click.option("--vendor", required=True, help="Vendor slug")
@click.option("--file", "filepath", required=True, help="Path to CSV file")
@click.option("--invoice", default=None, help="Invoice reference label")
@click.option("--dry-run", is_flag=True, help="Preview rows without writing")
def import_csv_cmd(vendor, filepath, invoice, dry_run):
    """Import vendor prices from a CSV file."""
    from .importer import import_csv
    from .sheets import append_dump_rows

    ingredients, ss = _load_registry()
    rows, result = import_csv(vendor, filepath, ingredients, invoice_ref=invoice)

    if result.errors:
        console.print(f"[yellow]Warnings ({len(result.errors)}):[/yellow]")
        for err in result.errors[:10]:
            console.print(f"  · {err}")
        if len(result.errors) > 10:
            console.print(f"  ... and {len(result.errors)-10} more")

    if not rows:
        console.print("[red]No rows to import.[/red]")
        return

    if dry_run:
        _print_rows_table(rows, title=f"Preview — {len(rows)} rows (dry run)")
    else:
        added, skipped = append_dump_rows(rows, ss)
        console.print(
            f"[green]✓ {added} rows written to DUMP.[/green]  {skipped} skipped (duplicate)."
        )


# ── compare ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--ingredient", required=True, help="Ingredient name to look up")
def compare(ingredient):
    """Compare prices for an ingredient across all vendors."""
    from .analysis import compare_by_name

    dump, ss = _load_dump()
    registry, _ = _load_registry(ss)

    results = compare_by_name(ingredient, dump, registry)
    if not results:
        console.print(f"[yellow]No ingredient found matching: {ingredient!r}[/yellow]")
        return

    for result in results:
        t = Table(
            title=f"{result.canonical_name} ({result.ing_id})",
            box=box.ROUNDED
        )
        t.add_column("Vendor", style="cyan")
        t.add_column("CPU", justify="right", style="bold")
        t.add_column("UOM")
        t.add_column("Pack Size")
        t.add_column("Pack Price", justify="right")
        t.add_column("Last Updated", style="dim")

        for i, p in enumerate(result.prices):
            style = "bold green" if i == 0 else ""
            t.add_row(
                p.vendor,
                f"${p.cpu:.4f}",
                p.uom,
                p.pack_size,
                f"${p.pack_price:.2f}",
                p.date,
                style=style,
            )

        if result.savings_vs_worst > 0:
            t.caption = (
                f"Savings potential: [green]${result.savings_vs_worst:.4f}/{result.prices[0].uom}[/green]"
                f" vs worst vendor"
            )
        console.print(t)


# ── best ───────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--category", default=None, help="Filter by ingredient category")
def best(category):
    """Show best (cheapest) vendor per ingredient."""
    from .analysis import best_per_ingredient

    dump, ss = _load_dump()
    registry, _ = _load_registry(ss)

    results = best_per_ingredient(dump, registry, category_filter=category)

    title = f"Best Vendor Per Ingredient"
    if category:
        title += f" — {category}"

    t = Table(title=title, box=box.ROUNDED)
    t.add_column("ING_ID", style="dim")
    t.add_column("Ingredient")
    t.add_column("Best Vendor", style="cyan")
    t.add_column("CPU", justify="right", style="green")
    t.add_column("UOM")
    t.add_column("Last Updated", style="dim")

    no_price = 0
    for ing, vp in results:
        if vp:
            t.add_row(ing.ing_id, ing.name, vp.vendor, f"${vp.cpu:.4f}", vp.uom, vp.date)
        else:
            t.add_row(ing.ing_id, ing.name, "[red]NO PRICE[/red]", "—", "—", "—")
            no_price += 1

    console.print(t)
    if no_price:
        console.print(f"[yellow]{no_price} ingredients have no price data.[/yellow]")


# ── savings ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--top", default=10, help="Number of results to show")
def savings(top):
    """Show top savings opportunities (biggest price spread across vendors)."""
    from .analysis import savings_opportunities

    dump, ss = _load_dump()
    registry, _ = _load_registry(ss)

    results = savings_opportunities(dump, registry, top_n=top)

    t = Table(
        title=f"Top {top} Savings Opportunities",
        box=box.ROUNDED,
        caption="Switch to the cheapest vendor to capture these savings per unit."
    )
    t.add_column("#", style="dim", justify="right")
    t.add_column("Ingredient")
    t.add_column("Best Vendor", style="green")
    t.add_column("Best CPU", justify="right", style="green")
    t.add_column("Worst Vendor", style="red")
    t.add_column("Worst CPU", justify="right", style="red")
    t.add_column("Savings/Unit", justify="right", style="bold yellow")
    t.add_column("UOM")

    for i, result in enumerate(results, 1):
        best = result.prices[0]
        worst = result.prices[-1]
        t.add_row(
            str(i),
            result.canonical_name,
            best.vendor,
            f"${best.cpu:.4f}",
            worst.vendor,
            f"${worst.cpu:.4f}",
            f"${result.savings_vs_worst:.4f}",
            best.uom,
        )

    console.print(t)


# ── extend-compare ─────────────────────────────────────────────────────────────

@cli.command("extend-compare")
@click.option("--dry-run", is_flag=True, help="Preview without writing to sheet")
def extend_compare(dry_run):
    """Create or refresh the 01B_MULTI_VENDOR_COMPARE tab in the spreadsheet."""
    from .sheets import write_extended_compare_tab

    ss = _get_sheet()
    console.print("[cyan]Building multi-vendor compare tab...[/cyan]")
    summary = write_extended_compare_tab(ss, dry_run=dry_run)

    status = "[yellow](dry run — nothing written)[/yellow]" if dry_run else "[green]✓ Written to sheet[/green]"
    console.print(
        f"{status}\n"
        f"  Ingredients: {summary['ingredients']}\n"
        f"  Vendors: {summary['vendors']}\n"
        f"  Rows written: {summary['rows_written']}\n"
        f"  DUMP rows read: {summary['dump_rows_read']}"
    )
    if not dry_run:
        console.print("\nOpen your spreadsheet and look for tab [bold]01B_MULTI_VENDOR_COMPARE[/bold].")


# ── event ──────────────────────────────────────────────────────────────────────

@cli.group()
def event():
    """Event cost reporting commands."""
    pass


@event.command("report")
@click.option("--event", "event_name", default="Longhorn Ballroom", help="Event name")
@click.option("--guests", required=True, type=int, help="Guest count to scale recipes to")
@click.option("--output", default="terminal",
              type=click.Choice(["terminal", "html"]), help="Output format")
@click.option("--vendor-strategy", default="best",
              help="'best' or a vendor slug to force (e.g. pfg)")
def event_report(event_name, guests, output, vendor_strategy):
    """Generate a full event cost report scaled to guest count."""
    from .reports import generate_event_report, render_terminal, render_html

    ss = _get_sheet()
    dump, _ = _load_dump(ss)
    registry, _ = _load_registry(ss)

    console.print(f"[cyan]Building report for '{event_name}' — {guests} guests...[/cyan]")

    report = generate_event_report(
        event_name=event_name,
        guests=guests,
        dump_rows=dump,
        ingredients=registry,
        ss=ss,
        vendor_strategy=vendor_strategy,
    )

    if output == "terminal":
        render_terminal(report, console)
    elif output == "html":
        html = render_html(report)
        out_path = f"event_report_{event_name.lower().replace(' ', '_')}.html"
        with open(out_path, "w") as f:
            f.write(html)
        console.print(f"[green]✓ HTML report saved to:[/green] {out_path}")


# ── web ────────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--port", default=5555, help="Port to listen on")
@click.option("--debug", is_flag=True, help="Enable Flask debug mode")
def web(port, debug):
    """Start the local web dashboard at http://localhost:<port>"""
    from .web import create_app
    app = create_app()
    console.print(
        f"[green]Starting dashboard at[/green] http://localhost:{port}\n"
        "Press Ctrl+C to stop."
    )
    app.run(host="0.0.0.0", port=port, debug=debug)


# ── internal helpers ───────────────────────────────────────────────────────────

def _print_rows_table(rows, title="Rows"):
    t = Table(title=title, box=box.SIMPLE)
    t.add_column("Vendor")
    t.add_column("SKU")
    t.add_column("Description")
    t.add_column("Pack Price", justify="right")
    t.add_column("Net Qty", justify="right")
    t.add_column("UOM")
    t.add_column("CPU", justify="right")
    t.add_column("ING_ID")
    for r in rows[:30]:
        t.add_row(
            r.vendor, r.sku, r.vendor_description[:35],
            f"${r.pack_price:.2f}", str(r.net_qty), r.uom,
            f"${r.cpu:.4f}", r.ing_id,
        )
    if len(rows) > 30:
        t.add_row("...", f"(+{len(rows)-30} more)", "", "", "", "", "", "")
    console.print(t)


if __name__ == "__main__":
    cli()
