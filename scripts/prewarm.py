"""Daily cache pre-warm. Runs Google (and optionally Meta) pulls so that
interactive Cowork tool calls hit warm cache.

Triggered by launchd at 6am local time:
    launchctl load ~/Library/LaunchAgents/com.jmacaggi.adsmcp.prewarm.plist

Run manually:
    ADS_MCP_ENV_FILE=... uv run python scripts/prewarm.py
    ADS_MCP_ENV_FILE=... uv run python scripts/prewarm.py --skip-meta
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ads_mcp_server import cache, google_ads, meta_ads, snapshots  # noqa: E402
from ads_mcp_server.config import get_app_config  # noqa: E402
from ads_mcp_server.logging_setup import get_logger  # noqa: E402

log = get_logger("prewarm")


def _prewarm_google(app, today: date) -> None:
    log.info("Prewarm Google: starting")
    t0 = time.time()
    df = google_ads.fetch_performance(app.google, today)
    cache.save_cache("google", df)
    settings = google_ads.fetch_settings(app.google)
    cache.save_settings_cache("google", settings)
    changes = google_ads.fetch_changes(app.google, today)
    cache.save_changes_cache("google", changes)
    cache.write_refresh_stamp("google", today)
    log.info("Prewarm Google: OK in %.1fs (%d perf rows, %d settings, %d campaigns w/ changes)",
             time.time() - t0, len(df), len(settings), len(changes))


def _prewarm_meta(app, today: date) -> None:
    log.info("Prewarm Meta: starting")
    t0 = time.time()
    df = meta_ads.fetch_performance(app.meta, today)
    cache.save_cache("meta", df)
    settings_adset, snapshot_records = meta_ads.fetch_settings(app.meta)
    settings = meta_ads.collapse_settings_to_campaign(settings_adset, df)
    cache.save_settings_cache("meta", settings)
    snapshots.write_snapshot(today, snapshot_records)
    snapshots.prune_snapshots()
    changes = snapshots.diff_against_prior(today)
    cache.save_changes_cache("meta", changes)
    ad_yest = meta_ads.fetch_ad_yesterday(app.meta, today)
    cache.save_ad_yesterday("meta", ad_yest)
    cache.write_refresh_stamp("meta", today)
    log.info("Prewarm Meta: OK in %.1fs (%d perf rows, %d settings, %d ad-yesterday rows)",
             time.time() - t0, len(df), len(settings), len(ad_yest))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-google", action="store_true")
    parser.add_argument("--skip-meta", action="store_true")
    args = parser.parse_args()

    app = get_app_config()
    today = date.today()
    failures: list[str] = []

    if not args.skip_google:
        if app.google.is_configured:
            try:
                _prewarm_google(app, today)
            except Exception as e:
                log.exception("Google prewarm failed: %s", e)
                failures.append(f"google: {e}")
        else:
            log.warning("Google not configured, skipping. Missing: %s", app.google.missing)

    if not args.skip_meta:
        if app.meta.is_configured:
            try:
                _prewarm_meta(app, today)
            except Exception as e:
                log.exception("Meta prewarm failed: %s", e)
                failures.append(f"meta: {e}")
        else:
            log.warning("Meta not configured, skipping. Missing: %s", app.meta.missing)

    if failures:
        for f in failures:
            log.error("FAILURE: %s", f)
        return 1
    log.info("Prewarm complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
