"""Flask web dashboard — reads entirely from Google Sheets, no local DB."""

import json
from datetime import date, timedelta
from functools import lru_cache

from flask import Flask, render_template, request, jsonify

from .sheets import (
    get_spreadsheet,
    get_all_dump_rows,
    get_ingredient_registry,
    write_extended_compare_tab,
)
from .analysis import (
    compare_by_name,
    savings_opportunities,
    dump_status,
    best_per_ingredient,
)
from .reports import generate_event_report, render_html as report_html


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["SECRET_KEY"] = "vp-dashboard-local"

    @app.context_processor
    def inject_dates():
        today = date.today()
        return {
            "today_minus_14": (today - timedelta(days=14)).isoformat(),
            "today_minus_90": (today - timedelta(days=90)).isoformat(),
        }

    def _ss():
        return get_spreadsheet()

    # ── dashboard ────────────────────────────────────────────────────────────

    @app.route("/")
    def dashboard():
        try:
            ss = _ss()
            dump = get_all_dump_rows(ss)
            registry = get_ingredient_registry(ss)
            status = dump_status(dump)
            top_savings = savings_opportunities(dump, registry, top_n=8)
            return render_template(
                "dashboard.html",
                status=status,
                top_savings=top_savings,
                ingredient_count=len(registry),
            )
        except Exception as e:
            return render_template("error.html", error=str(e))

    # ── compare ──────────────────────────────────────────────────────────────

    @app.route("/compare")
    def compare():
        query = request.args.get("q", "").strip()
        results = []
        error = None
        if query:
            try:
                ss = _ss()
                dump = get_all_dump_rows(ss)
                registry = get_ingredient_registry(ss)
                results = compare_by_name(query, dump, registry)
            except Exception as e:
                error = str(e)
        return render_template("compare.html", query=query, results=results, error=error)

    # ── vendors ──────────────────────────────────────────────────────────────

    @app.route("/vendors")
    def vendors():
        try:
            ss = _ss()
            dump = get_all_dump_rows(ss)
            status = dump_status(dump)
            return render_template("vendors.html", status=status)
        except Exception as e:
            return render_template("error.html", error=str(e))

    @app.route("/vendors/refresh-compare", methods=["POST"])
    def refresh_compare():
        try:
            ss = _ss()
            summary = write_extended_compare_tab(ss)
            return jsonify({"ok": True, "summary": summary})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # ── event report ─────────────────────────────────────────────────────────

    @app.route("/report", methods=["GET", "POST"])
    def report():
        if request.method == "GET":
            return render_template("report_event.html", report_html=None, error=None)

        event_name = request.form.get("event_name", "Longhorn Ballroom").strip()
        try:
            guests = int(request.form.get("guests", "0"))
        except ValueError:
            guests = 0

        if guests <= 0:
            return render_template(
                "report_event.html",
                report_html=None,
                error="Guest count must be a positive number.",
            )

        try:
            ss = _ss()
            dump = get_all_dump_rows(ss)
            registry = get_ingredient_registry(ss)
            rpt = generate_event_report(
                event_name=event_name,
                guests=guests,
                dump_rows=dump,
                ingredients=registry,
                ss=ss,
            )
            html_content = report_html(rpt)
            return render_template(
                "report_event.html",
                report_html=html_content,
                error=None,
                event_name=event_name,
                guests=guests,
            )
        except Exception as e:
            return render_template("report_event.html", report_html=None, error=str(e))

    # ── API endpoints ─────────────────────────────────────────────────────────

    @app.route("/api/savings")
    def api_savings():
        try:
            ss = _ss()
            dump = get_all_dump_rows(ss)
            registry = get_ingredient_registry(ss)
            results = savings_opportunities(dump, registry, top_n=20)
            return jsonify([
                {
                    "ing_id": r.ing_id,
                    "name": r.canonical_name,
                    "best_vendor": r.prices[0].vendor if r.prices else "",
                    "best_cpu": r.prices[0].cpu if r.prices else 0,
                    "worst_cpu": r.prices[-1].cpu if r.prices else 0,
                    "savings": r.savings_vs_worst,
                    "uom": r.prices[0].uom if r.prices else "",
                }
                for r in results
            ])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/dump-status")
    def api_dump_status():
        try:
            ss = _ss()
            dump = get_all_dump_rows(ss)
            return jsonify(dump_status(dump))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return app
