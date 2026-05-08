"""Integration smoke test: hit real Google Ads + Meta APIs through tool impls.

Run from project root:
    ADS_MCP_ENV_FILE=/Users/jmacaggi/marketing-ds/decision_science/.env \
        uv run python scripts/integration_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

# Make src importable when run via `uv run python scripts/...`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ads_mcp_server import server as srv  # noqa: E402

DATE_RANGES = ("yesterday", "last_7_days", "last_week", "last_14_days")
BREAKDOWNS = ("account", "campaign_type", "ad")


def _summarize(label: str, result: dict[str, Any]) -> dict[str, Any]:
    if "error" in result:
        return {"label": label, "status": "ERROR", "detail": result["error"][:300]}
    md = result.get("metadata", {})
    n_ads = len(result.get("by_ad", []))
    n_days = len(result.get("daily_series", []))
    n_settings = len(result.get("campaign_settings", []))
    acct = result.get("account", {})
    return {
        "label": label,
        "status": "OK",
        "data_source": md.get("data_source"),
        "window": f"{md.get('date_range_start')}..{md.get('date_range_end')}",
        "spend": acct.get("spend"),
        "n_ads": n_ads,
        "n_days": n_days,
        "n_settings": n_settings,
        "n_changes": sum(len(v) for v in (result.get("campaign_settings") or [])
                          if isinstance(v, dict) for v in [v.get("change_history", [])]),
    }


def run_all() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # Google Ads
    for dr in DATE_RANGES:
        for bd in BREAKDOWNS:
            label = f"google {dr}/{bd}"
            print(f"→ {label}", flush=True)
            t0 = time.time()
            res = srv.get_google_ads_report_impl(dr, bd)
            elapsed = time.time() - t0
            row = _summarize(label, res)
            row["elapsed_s"] = round(elapsed, 2)
            out.append(row)
            print(f"  {row}", flush=True)

    # Meta Ads
    for dr in DATE_RANGES:
        for bd in BREAKDOWNS:
            label = f"meta {dr}/{bd}"
            print(f"→ {label}", flush=True)
            t0 = time.time()
            res = srv.get_meta_ads_report_impl(dr, bd)
            elapsed = time.time() - t0
            row = _summarize(label, res)
            row["elapsed_s"] = round(elapsed, 2)
            out.append(row)
            print(f"  {row}", flush=True)

    # Settings tool
    for plat in ("google", "meta", "both"):
        label = f"settings {plat}"
        print(f"→ {label}", flush=True)
        t0 = time.time()
        res = srv.get_campaign_settings_impl(plat)
        elapsed = time.time() - t0
        if "error" in res:
            row = {"label": label, "status": "ERROR", "detail": res["error"][:300]}
        else:
            row = {
                "label": label,
                "status": "OK",
                "google_n": len(res.get("google", [])) if "google" in res else None,
                "meta_n": len(res.get("meta", [])) if "meta" in res else None,
            }
        row["elapsed_s"] = round(elapsed, 2)
        out.append(row)
        print(f"  {row}", flush=True)

    return out


if __name__ == "__main__":
    results = run_all()
    print("\n\n=== SUMMARY ===")
    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_err = sum(1 for r in results if r["status"] == "ERROR")
    print(f"OK: {n_ok}  ERROR: {n_err}  TOTAL: {len(results)}")
    print(json.dumps(results, indent=2, default=str))
