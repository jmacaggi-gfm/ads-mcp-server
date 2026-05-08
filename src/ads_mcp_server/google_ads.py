"""Google Ads API client: performance, settings, change events."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .config import GoogleAdsConfig
from .date_ranges import full_56d_window
from .logging_setup import get_logger
from .retry import RateLimitError, with_backoff

log = get_logger(__name__)


def _build_client(cfg: GoogleAdsConfig):
    from google.ads.googleads.client import GoogleAdsClient

    creds = {
        "developer_token": cfg.developer_token,
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "refresh_token": cfg.refresh_token,
        "use_proto_plus": True,
    }
    if cfg.login_customer_id:
        creds["login_customer_id"] = cfg.login_customer_id
    return GoogleAdsClient.load_from_dict(creds)


PERF_QUERY_TEMPLATE = """
SELECT
  segments.date,
  campaign.id,
  campaign.name,
  campaign.status,
  ad_group.id,
  ad_group.name,
  ad_group_ad.ad.id,
  ad_group_ad.ad.name,
  ad_group_ad.status,
  metrics.cost_micros,
  metrics.impressions,
  metrics.clicks,
  metrics.ctr,
  metrics.average_cpc,
  metrics.conversions,
  metrics.cost_per_conversion
FROM ad_group_ad
WHERE segments.date BETWEEN '{start}' AND '{end}'
  AND campaign.advertising_channel_type = 'SEARCH'
  AND campaign.status != 'REMOVED'
"""

# Impression share metrics are only valid at the campaign resource for
# Search campaigns. Pulled separately and joined on (campaign_id, date).
CAMPAIGN_IS_QUERY_TEMPLATE = """
SELECT
  campaign.id,
  campaign.name,
  segments.date,
  metrics.search_impression_share,
  metrics.search_budget_lost_impression_share,
  metrics.search_rank_lost_impression_share
FROM campaign
WHERE segments.date BETWEEN '{start}' AND '{end}'
"""

SETTINGS_QUERY = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  campaign.bidding_strategy_type,
  campaign.target_cpa.target_cpa_micros,
  campaign.maximize_conversions.target_cpa_micros,
  campaign.target_roas.target_roas,
  campaign_budget.amount_micros,
  campaign_budget.explicitly_shared
FROM campaign
WHERE campaign.status = 'ENABLED'
"""

CHANGE_QUERY_TEMPLATE = """
SELECT
  change_event.change_date_time,
  change_event.change_resource_type,
  change_event.changed_fields,
  change_event.campaign,
  change_event.old_resource,
  change_event.new_resource
FROM change_event
WHERE change_event.change_date_time >= '{start} 00:00:00'
  AND change_event.change_date_time <= '{end} 23:59:59'
  AND change_event.change_resource_type IN ('CAMPAIGN', 'CAMPAIGN_BUDGET')
ORDER BY change_event.change_date_time DESC
LIMIT 10000
"""


def _classify_google_exception(e: Exception) -> Exception:
    msg = str(e)
    if "RESOURCE_EXHAUSTED" in msg or "RATE_LIMIT" in msg or "QUOTA" in msg:
        return RateLimitError(msg)
    return e


@with_backoff()
def _execute(client, customer_id: str, query: str) -> list[Any]:
    service = client.get_service("GoogleAdsService")
    try:
        stream = service.search_stream(customer_id=customer_id, query=query)
        rows = []
        for batch in stream:
            for row in batch.results:
                rows.append(row)
        return rows
    except Exception as e:
        raise _classify_google_exception(e)


def _micros_to_usd(micros) -> float | None:
    if micros is None:
        return None
    return float(micros) / 1_000_000.0


def fetch_performance(cfg: GoogleAdsConfig, today: date) -> pd.DataFrame:
    """Pull last-56-day ad×day performance across all configured customers."""
    client = _build_client(cfg)
    window = full_56d_window(today)
    q = PERF_QUERY_TEMPLATE.format(start=window.start.isoformat(), end=window.end.isoformat())

    records: list[dict[str, Any]] = []
    for cid in cfg.customer_ids:
        log.info("Google perf pull: customer=%s window=%s..%s", cid, window.start, window.end)
        rows = _execute(client, cid, q)
        for r in rows:
            records.append(
                {
                    "customer_id": cid,
                    "date": r.segments.date,
                    "campaign_id": str(r.campaign.id),
                    "campaign_name": r.campaign.name,
                    "campaign_status": r.campaign.status.name,
                    "ad_group_id": str(r.ad_group.id),
                    "ad_group_name": r.ad_group.name,
                    "ad_id": str(r.ad_group_ad.ad.id),
                    "ad_name": r.ad_group_ad.ad.name or f"ad_{r.ad_group_ad.ad.id}",
                    "ad_status": r.ad_group_ad.status.name,
                    "spend": _micros_to_usd(r.metrics.cost_micros) or 0.0,
                    "impressions": int(r.metrics.impressions),
                    "clicks": int(r.metrics.clicks),
                    "ctr_pct_raw": float(r.metrics.ctr) * 100.0,
                    "cpc_usd_raw": _micros_to_usd(r.metrics.average_cpc) or 0.0,
                    "conversions": float(r.metrics.conversions),
                    "cpa_usd_raw": _micros_to_usd(r.metrics.cost_per_conversion),
                }
            )

    perf_df = pd.DataFrame.from_records(records)
    is_df = _fetch_campaign_impression_share(client, cfg, today)
    return _join_impression_share(perf_df, is_df)


def _fetch_campaign_impression_share(client, cfg: GoogleAdsConfig, today: date) -> pd.DataFrame:
    """Pull search_impression_share metrics at campaign×date grain."""
    window = full_56d_window(today)
    q = CAMPAIGN_IS_QUERY_TEMPLATE.format(
        start=window.start.isoformat(), end=window.end.isoformat()
    )
    records: list[dict[str, Any]] = []
    for cid in cfg.customer_ids:
        log.info("Google IS pull: customer=%s window=%s..%s", cid, window.start, window.end)
        try:
            rows = _execute(client, cid, q)
        except Exception as e:
            # Display-only or non-Search accounts may reject IS query — skip silently
            log.warning("Campaign IS pull failed for %s: %s", cid, e)
            continue
        for r in rows:
            records.append(
                {
                    "customer_id": cid,
                    "campaign_id": str(r.campaign.id),
                    "date": r.segments.date,
                    "search_impression_share": (
                        float(r.metrics.search_impression_share)
                        if r.metrics.search_impression_share
                        else None
                    ),
                    "search_budget_lost_impression_share": (
                        float(r.metrics.search_budget_lost_impression_share)
                        if r.metrics.search_budget_lost_impression_share
                        else None
                    ),
                    "search_rank_lost_impression_share": (
                        float(r.metrics.search_rank_lost_impression_share)
                        if r.metrics.search_rank_lost_impression_share
                        else None
                    ),
                }
            )
    return pd.DataFrame.from_records(records)


def _join_impression_share(perf: pd.DataFrame, is_df: pd.DataFrame) -> pd.DataFrame:
    """Left-join campaign-level IS metrics onto ad-level perf rows."""
    if perf.empty:
        return perf
    if is_df.empty:
        for col in (
            "search_impression_share",
            "search_budget_lost_impression_share",
            "search_rank_lost_impression_share",
        ):
            perf[col] = None
        return perf
    keys = ["customer_id", "campaign_id", "date"] if "customer_id" in is_df.columns else ["campaign_id", "date"]
    return perf.merge(is_df, on=keys, how="left")


def fetch_settings(cfg: GoogleAdsConfig) -> pd.DataFrame:
    client = _build_client(cfg)
    records: list[dict[str, Any]] = []
    for cid in cfg.customer_ids:
        log.info("Google settings pull: customer=%s", cid)
        rows = _execute(client, cid, SETTINGS_QUERY)
        for r in rows:
            tcpa_main = _micros_to_usd(r.campaign.target_cpa.target_cpa_micros)
            tcpa_maxconv = _micros_to_usd(
                r.campaign.maximize_conversions.target_cpa_micros
            )
            target_cpa = tcpa_main if tcpa_main else tcpa_maxconv
            records.append(
                {
                    "customer_id": cid,
                    "campaign_id": str(r.campaign.id),
                    "campaign_name": r.campaign.name,
                    "status": r.campaign.status.name,
                    "bidding_strategy": r.campaign.bidding_strategy_type.name,
                    "target_cpa_usd": target_cpa if target_cpa else None,
                    "target_roas": (
                        float(r.campaign.target_roas.target_roas)
                        if r.campaign.target_roas.target_roas
                        else None
                    ),
                    "daily_budget_usd": _micros_to_usd(r.campaign_budget.amount_micros),
                    "budget_shared": bool(r.campaign_budget.explicitly_shared),
                }
            )
    return pd.DataFrame.from_records(records)


def _extract_resource_values(resource) -> dict[str, float | None]:
    """Pull tcpa/budget from a ChangedResource oneof. Returns {} if neither populated."""
    out: dict[str, float | None] = {}
    if resource is None:
        return out
    # campaign sub-message
    try:
        camp = getattr(resource, "campaign", None)
        if camp is not None:
            tcpa_main = getattr(getattr(camp, "target_cpa", None), "target_cpa_micros", 0) or 0
            tcpa_maxconv = (
                getattr(getattr(camp, "maximize_conversions", None), "target_cpa_micros", 0)
                or 0
            )
            tcpa = tcpa_main or tcpa_maxconv
            if tcpa:
                out["target_cpa"] = _micros_to_usd(tcpa)
    except Exception:
        pass
    try:
        budget = getattr(resource, "campaign_budget", None)
        if budget is not None:
            amt = getattr(budget, "amount_micros", 0) or 0
            if amt:
                out["budget"] = _micros_to_usd(amt)
    except Exception:
        pass
    return out


def fetch_changes(cfg: GoogleAdsConfig, today: date) -> dict[str, list[dict[str, Any]]]:
    """Returns {campaign_id: [change events]}.

    Google's change_event API caps history at 29 days. Window is clamped
    to that even though perf cache is 56d.
    """
    from datetime import timedelta

    client = _build_client(cfg)
    perf_window = full_56d_window(today)
    start = max(perf_window.start, today - timedelta(days=29))
    q = CHANGE_QUERY_TEMPLATE.format(start=start.isoformat(), end=perf_window.end.isoformat())

    out: dict[str, list[dict[str, Any]]] = {}
    for cid in cfg.customer_ids:
        log.info("Google change_event pull: customer=%s", cid)
        try:
            rows = _execute(client, cid, q)
        except Exception as e:
            log.warning("change_event pull failed for %s: %s", cid, e)
            continue
        for r in rows:
            campaign_resource = r.change_event.campaign
            campaign_id = campaign_resource.split("/")[-1] if campaign_resource else None
            old_vals = _extract_resource_values(r.change_event.old_resource)
            new_vals = _extract_resource_values(r.change_event.new_resource)
            ts = str(r.change_event.change_date_time)

            for field in ("target_cpa", "budget"):
                old_v = old_vals.get(field)
                new_v = new_vals.get(field)
                if old_v == new_v:
                    continue
                if old_v is None and new_v is None:
                    continue
                out.setdefault(campaign_id, []).append(
                    {
                        "date": ts,
                        "field": field,
                        "old_value": old_v,
                        "new_value": new_v,
                    }
                )
    return out
