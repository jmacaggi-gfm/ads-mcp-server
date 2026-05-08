"""MCP entrypoint exposing 3 tools: get_google_ads_report, get_meta_ads_report, get_campaign_settings."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from . import aggregate, cache, google_ads, meta_ads, snapshots
from .classify import google_classifier, meta_classifier
from .config import AppConfig, get_app_config
from .date_ranges import VALID_RANGES
from .logging_setup import get_logger
from .schema import error_response

log = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    return date.today()


def _ensure_google_56d(app: AppConfig) -> tuple[pd.DataFrame, str]:
    if not app.google.is_configured:
        return pd.DataFrame(), "miss"
    today = _today()
    df, source = cache.load_cached("google", today)
    if df is None:
        df = google_ads.fetch_performance(app.google, today)
        cache.save_cache("google", df)
        cache.write_refresh_stamp("google", today)
        source = "api"
    df = aggregate.annotate_campaign_types(df, google_classifier())
    return df, source


def _ensure_meta_56d(app: AppConfig) -> tuple[pd.DataFrame, str]:
    if not app.meta.is_configured:
        return pd.DataFrame(), "miss"
    today = _today()
    df, source = cache.load_cached("meta", today)
    if df is None:
        df = meta_ads.fetch_performance(app.meta, today)
        cache.save_cache("meta", df)
        cache.write_refresh_stamp("meta", today)
        source = "api"
    df = aggregate.annotate_campaign_types(
        df, meta_classifier(app.meta_retargeting_keywords)
    )
    return df, source


def _settings_with_types(settings: pd.DataFrame, classifier) -> pd.DataFrame:
    """Add campaign_type column via the platform's classifier."""
    if settings.empty:
        return settings
    settings = settings.copy()
    settings["campaign_type"] = settings["campaign_name"].apply(classifier)
    return settings


# ----------------------------------------------------------------
# Tool implementations (sync, return dicts)
# ----------------------------------------------------------------


def get_google_ads_report_impl(
    date_range: str,
    breakdown: str,
    include_campaign_settings: bool = False,
    include_daily_by_campaign: bool = False,
) -> dict[str, Any]:
    if date_range not in VALID_RANGES:
        return error_response("google", f"Invalid date_range. Use one of {VALID_RANGES}")
    if breakdown not in ("account", "campaign_type", "ad"):
        return error_response("google", f"Invalid breakdown: {breakdown}")
    app = get_app_config()
    if not app.google.is_configured:
        return error_response(
            "google",
            "Missing Google Ads credentials",
            missing_keys=app.google.missing,
        )
    try:
        today = _today()
        df_56d, source = _ensure_google_56d(app)
        settings = cache.load_settings_cache("google", today)
        if settings is None:
            settings = google_ads.fetch_settings(app.google)
            cache.save_settings_cache("google", settings)
        settings = _settings_with_types(settings, google_classifier())
        changes = cache.load_changes_cache("google", today)
        if changes is None:
            changes = google_ads.fetch_changes(app.google, today)
            cache.save_changes_cache("google", changes)
        return aggregate.build_response(
            df_56d=df_56d,
            settings=settings,
            date_range=date_range,
            breakdown=breakdown,
            today=_today(),
            thresholds=app.thresholds,
            platform="google",
            fetched_at=_now_iso(),
            data_source=source,
            change_history=changes,
            include_campaign_settings=include_campaign_settings,
            include_daily_by_campaign=include_daily_by_campaign,
        )
    except Exception as e:
        log.exception("Google tool failed")
        return error_response("google", str(e))


def get_meta_ads_report_impl(date_range: str, breakdown: str) -> dict[str, Any]:
    if date_range not in VALID_RANGES:
        return error_response("meta", f"Invalid date_range. Use one of {VALID_RANGES}")
    if breakdown not in ("account", "campaign_type", "ad"):
        return error_response("meta", f"Invalid breakdown: {breakdown}")
    app = get_app_config()
    if not app.meta.is_configured:
        return error_response(
            "meta",
            "Missing Meta credentials",
            missing_keys=app.meta.missing,
        )
    try:
        today = _today()
        df_56d, source = _ensure_meta_56d(app)
        settings = cache.load_settings_cache("meta", today)
        if settings is None:
            settings_adset, snapshot_records = meta_ads.fetch_settings(app.meta)
            settings = meta_ads.collapse_settings_to_campaign(settings_adset, df_56d)
            cache.save_settings_cache("meta", settings)
            snapshots.write_snapshot(today, snapshot_records)
            snapshots.prune_snapshots()
        settings = _settings_with_types(
            settings, meta_classifier(app.meta_retargeting_keywords)
        )
        changes = cache.load_changes_cache("meta", today)
        if changes is None:
            changes = snapshots.diff_against_prior(today)
            cache.save_changes_cache("meta", changes)

        # Ad-level yesterday: cached separately so per-tool calls reuse it
        ad_yesterday = cache.load_ad_yesterday("meta", today)
        if ad_yesterday is None:
            ad_yesterday = meta_ads.fetch_ad_yesterday(app.meta, today)
            cache.save_ad_yesterday("meta", ad_yesterday)
        ad_yesterday = (
            aggregate.annotate_campaign_types(
                ad_yesterday, meta_classifier(app.meta_retargeting_keywords)
            )
            if not ad_yesterday.empty
            else ad_yesterday
        )

        return aggregate.build_response(
            df_56d=df_56d,
            settings=settings,
            date_range=date_range,
            breakdown=breakdown,
            today=today,
            thresholds=app.thresholds,
            platform="meta",
            fetched_at=_now_iso(),
            data_source=source,
            change_history=changes,
            df_ad_grain=ad_yesterday,
            include_campaign_settings=True,
        )
    except Exception as e:
        log.exception("Meta tool failed")
        return error_response("meta", str(e))


def get_campaign_settings_impl(platform: str) -> dict[str, Any]:
    if platform not in ("google", "meta", "both"):
        return error_response(platform, "platform must be google|meta|both")
    out: dict[str, Any] = {"fetched_at": _now_iso()}
    if platform in ("google", "both"):
        out["google"] = get_google_ads_report_impl(
            "yesterday", "account", include_campaign_settings=True
        ).get("campaign_settings", [])
    if platform in ("meta", "both"):
        out["meta"] = get_meta_ads_report_impl("yesterday", "account").get(
            "campaign_settings", []
        )
    return out


# ----------------------------------------------------------------
# MCP wiring
# ----------------------------------------------------------------


def build_mcp_server():
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server = Server("ads-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_google_ads_report",
                description=(
                    "Pull Google Ads performance. Returns account totals, "
                    "campaign-type breakdown, top-50 per-ad rows with diagnosis, "
                    "56-day daily series, and WoW + 8-week DoW comparisons. "
                    "Set include_campaign_settings=True to also return per-campaign "
                    "settings (target CPA, daily budget, diagnosis, utilization) "
                    "for ENABLED campaigns only."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date_range": {
                            "type": "string",
                            "enum": list(VALID_RANGES),
                        },
                        "breakdown": {
                            "type": "string",
                            "enum": ["account", "campaign_type", "ad"],
                        },
                        "include_campaign_settings": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "If true, attach campaign_settings list to "
                                "the response. Defaults to false to keep "
                                "payload small."
                            ),
                        },
                        "include_daily_by_campaign": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "If true, attach daily_series_by_campaign to "
                                "the response: same shape as daily_series but "
                                "keyed by campaign_name (top 20 by 56-day spend)."
                            ),
                        },
                    },
                    "required": ["date_range", "breakdown"],
                },
            ),
            Tool(
                name="get_meta_ads_report",
                description=(
                    "Pull Meta Ads performance. Same shape as get_google_ads_report. "
                    "Conversions filtered to META_CONVERSION_EVENT_NAME."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "date_range": {
                            "type": "string",
                            "enum": list(VALID_RANGES),
                        },
                        "breakdown": {
                            "type": "string",
                            "enum": ["account", "campaign_type", "ad"],
                        },
                    },
                    "required": ["date_range", "breakdown"],
                },
            ),
            Tool(
                name="get_campaign_settings",
                description="Current campaign settings + 56-day change history per platform.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "enum": ["google", "meta", "both"],
                        }
                    },
                    "required": ["platform"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        import json

        if name == "get_google_ads_report":
            result = get_google_ads_report_impl(
                arguments["date_range"],
                arguments["breakdown"],
                include_campaign_settings=bool(arguments.get("include_campaign_settings", False)),
                include_daily_by_campaign=bool(arguments.get("include_daily_by_campaign", False)),
            )
        elif name == "get_meta_ads_report":
            result = get_meta_ads_report_impl(
                arguments["date_range"], arguments["breakdown"]
            )
        elif name == "get_campaign_settings":
            result = get_campaign_settings_impl(arguments["platform"])
        else:
            result = {"error": f"Unknown tool: {name}"}
        return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]

    return server


async def _run() -> None:
    from mcp.server.stdio import stdio_server

    server = build_mcp_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
