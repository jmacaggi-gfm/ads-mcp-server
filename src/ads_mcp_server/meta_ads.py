"""Meta Marketing API client: insights + ad-set settings + snapshot diff."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .config import MetaAdsConfig
from .date_ranges import full_56d_window
from .logging_setup import get_logger
from .retry import RateLimitError, with_backoff

log = get_logger(__name__)

CAMPAIGN_INSIGHT_FIELDS = [
    "date_start",
    "campaign_id",
    "campaign_name",
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "actions",
    "cost_per_action_type",
    "reach",
    "frequency",
]

AD_INSIGHT_FIELDS = [
    "date_start",
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "actions",
    "cost_per_action_type",
    "reach",
    "frequency",
]

ADSET_FIELDS = [
    "id",
    "name",
    "campaign_id",
    "status",
    "bid_strategy",
    "bid_amount",
    "daily_budget",
    "lifetime_budget",
    "optimization_goal",
]


def _init_meta_api(cfg: MetaAdsConfig) -> None:
    from facebook_business.api import FacebookAdsApi

    kwargs: dict[str, str] = {"access_token": cfg.access_token}
    if cfg.app_id:
        kwargs["app_id"] = cfg.app_id
    if cfg.app_secret:
        kwargs["app_secret"] = cfg.app_secret
    FacebookAdsApi.init(**kwargs)


def _classify_meta_exception(e: Exception) -> Exception:
    msg = str(e)
    msg_lower = msg.lower()
    rate_signals = (
        "rate limit",
        "user request limit",
        "request limit reached",
        "(#17)",
        "(#80004)",
        "code 17",
        "\"code\": 17",
        "2446079",
    )
    if any(s in msg_lower for s in rate_signals):
        return RateLimitError(msg)
    return e


@with_backoff()
def _fetch_insights(account, params: dict[str, Any], fields: list[str]):
    try:
        return list(account.get_insights(fields=fields, params=params))
    except Exception as e:
        raise _classify_meta_exception(e)


@with_backoff()
def _fetch_adsets(account):
    """Pull active + recently-paused ad sets only.

    Filtering server-side avoids paginating through thousands of archived
    ad sets, which is the primary cause of rate-limit (code 17) errors on
    accounts with deep history.
    """
    params = {
        "limit": 500,
        "filtering": [
            {
                "field": "effective_status",
                "operator": "IN",
                "value": ["ACTIVE", "PAUSED"],
            }
        ],
    }
    try:
        return list(account.get_ad_sets(fields=ADSET_FIELDS, params=params))
    except Exception as e:
        raise _classify_meta_exception(e)


def _extract_action(row, action_type: str) -> tuple[float, float | None]:
    """Return (conversions, cpa_usd) for a given action_type, else (0, None)."""
    actions = row.get("actions") or []
    cpas = row.get("cost_per_action_type") or []
    conv = 0.0
    cpa = None
    for a in actions:
        if a.get("action_type") == action_type:
            conv = float(a.get("value", 0) or 0)
            break
    for c in cpas:
        if c.get("action_type") == action_type:
            try:
                cpa = float(c.get("value", 0) or 0)
            except (TypeError, ValueError):
                cpa = None
            break
    return conv, cpa


def _row_to_record(d: dict[str, Any], event_name: str, ad_grain: bool) -> dict[str, Any]:
    conv, cpa = _extract_action(d, event_name)
    spend = float(d.get("spend", 0) or 0)
    impressions = int(float(d.get("impressions", 0) or 0))
    clicks = int(float(d.get("clicks", 0) or 0))
    rec = {
        "date": d.get("date_start"),
        "campaign_id": str(d.get("campaign_id")),
        "campaign_name": d.get("campaign_name"),
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr_pct_raw": float(d.get("ctr", 0) or 0),
        "cpc_usd_raw": float(d.get("cpc", 0) or 0),
        "conversions": conv,
        "cpa_usd_raw": cpa,
        "reach": int(float(d.get("reach", 0) or 0)),
        "frequency": float(d.get("frequency", 0) or 0),
    }
    if ad_grain:
        rec.update(
            {
                "adset_id": str(d.get("adset_id")),
                "adset_name": d.get("adset_name"),
                "ad_id": str(d.get("ad_id")),
                "ad_name": d.get("ad_name"),
            }
        )
    else:
        # Use campaign as the synthetic ad row so by_campaign_type/daily_series work
        rec.update(
            {
                "adset_id": None,
                "adset_name": None,
                "ad_id": str(d.get("campaign_id")),
                "ad_name": d.get("campaign_name"),
            }
        )
    return rec


def fetch_performance(cfg: MetaAdsConfig, today: date) -> pd.DataFrame:
    """Campaign-daily insights for the full 56-day window.

    Chunked into 7-day windows to stay under Meta's response-size cap
    (which manifests as a 400 'Service temporarily unavailable' error
    when the result set is too large for a single request).
    """
    from datetime import timedelta

    from facebook_business.adobjects.adaccount import AdAccount

    _init_meta_api(cfg)
    account = AdAccount(cfg.ad_account_id)
    window = full_56d_window(today)

    all_records: list[dict[str, Any]] = []
    chunk_start = window.start
    while chunk_start <= window.end:
        chunk_end = min(chunk_start + timedelta(days=6), window.end)
        params = {
            "level": "campaign",
            "time_increment": 1,
            "limit": 1000,
            "time_range": {
                "since": chunk_start.isoformat(),
                "until": chunk_end.isoformat(),
            },
        }
        log.info("Meta perf chunk: %s..%s", chunk_start, chunk_end)
        rows = _fetch_insights(account, params, CAMPAIGN_INSIGHT_FIELDS)
        all_records.extend(
            _row_to_record(
                r if isinstance(r, dict) else dict(r),
                cfg.conversion_event_name,
                ad_grain=False,
            )
            for r in rows
        )
        chunk_start = chunk_end + timedelta(days=1)
    return pd.DataFrame.from_records(all_records)


def fetch_ad_yesterday(cfg: MetaAdsConfig, today: date) -> pd.DataFrame:
    """Ad-level insights for yesterday only (small, fast)."""
    from datetime import timedelta

    from facebook_business.adobjects.adaccount import AdAccount

    _init_meta_api(cfg)
    account = AdAccount(cfg.ad_account_id)
    yest = today - timedelta(days=1)
    params = {
        "level": "ad",
        "time_increment": 1,
        "limit": 1000,
        "time_range": {"since": yest.isoformat(), "until": yest.isoformat()},
    }
    log.info("Meta ad-level pull: %s only", yest)
    rows = _fetch_insights(account, params, AD_INSIGHT_FIELDS)
    records = [
        _row_to_record(r if isinstance(r, dict) else dict(r), cfg.conversion_event_name, ad_grain=True)
        for r in rows
    ]
    return pd.DataFrame.from_records(records)


def fetch_settings(cfg: MetaAdsConfig) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Returns (settings_df, raw_adset_records_for_snapshot)."""
    from facebook_business.adobjects.adaccount import AdAccount

    _init_meta_api(cfg)
    account = AdAccount(cfg.ad_account_id)
    log.info("Meta ad-set settings pull")
    raw = _fetch_adsets(account)

    settings: list[dict[str, Any]] = []
    snapshot: list[dict[str, Any]] = []
    for a in raw:
        d = a if isinstance(a, dict) else dict(a)
        bid_strategy = d.get("bid_strategy")
        bid_amount_cents = d.get("bid_amount")
        bid_amount_usd = float(bid_amount_cents) / 100.0 if bid_amount_cents else None
        daily_budget = (
            float(d.get("daily_budget")) / 100.0 if d.get("daily_budget") else None
        )
        lifetime_budget = (
            float(d.get("lifetime_budget")) / 100.0 if d.get("lifetime_budget") else None
        )
        target_cpa_usd = bid_amount_usd if bid_strategy == "COST_CAP" else None

        settings.append(
            {
                "campaign_id": str(d.get("campaign_id")),
                "campaign_name": None,  # Meta ad-set lacks campaign_name; joined later from perf
                "status": d.get("status"),
                "bidding_strategy": bid_strategy,
                "target_cpa_usd": target_cpa_usd,
                "daily_budget_usd": daily_budget,
                "lifetime_budget_usd": lifetime_budget,
                "budget_shared": False,
                "optimization_goal": d.get("optimization_goal"),
                "adset_id": str(d.get("id")),
                "adset_name": d.get("name"),
            }
        )
        snapshot.append(
            {
                "id": str(d.get("id")),
                "name": d.get("name"),
                "campaign_id": str(d.get("campaign_id")),
                "campaign_name": None,
                "status": d.get("status"),
                "bid_strategy": bid_strategy,
                "bid_amount_usd": bid_amount_usd,
                "daily_budget_usd": daily_budget,
                "lifetime_budget_usd": lifetime_budget,
                "optimization_goal": d.get("optimization_goal"),
            }
        )
    return pd.DataFrame.from_records(settings), snapshot


def collapse_settings_to_campaign(
    settings_df: pd.DataFrame, perf_df: pd.DataFrame
) -> pd.DataFrame:
    """Roll ad-set settings up to campaign level: sum budgets, take min target_cpa."""
    if settings_df.empty:
        return settings_df
    # Pull campaign_name from perf
    if not perf_df.empty:
        names = (
            perf_df[["campaign_id", "campaign_name"]]
            .drop_duplicates("campaign_id")
            .set_index("campaign_id")["campaign_name"]
            .to_dict()
        )
    else:
        names = {}
    grouped = (
        settings_df.groupby("campaign_id")
        .agg(
            status=("status", "first"),
            bidding_strategy=("bidding_strategy", "first"),
            target_cpa_usd=("target_cpa_usd", "min"),
            daily_budget_usd=("daily_budget_usd", "sum"),
            lifetime_budget_usd=("lifetime_budget_usd", "sum"),
            budget_shared=("budget_shared", "first"),
        )
        .reset_index()
    )
    grouped["campaign_name"] = grouped["campaign_id"].map(names)
    return grouped
