"""Response shape models. Loose by design — server returns plain dicts."""
from __future__ import annotations

from typing import Any, TypedDict


class Metadata(TypedDict, total=False):
    platform: str
    fetched_at: str
    date_range_start: str
    date_range_end: str
    currency: str
    breakdown: str
    data_source: str  # "api" | "csv_override" | "cache"


METRIC_FIELDS = (
    "spend",
    "impressions",
    "clicks",
    "ctr_pct",
    "cpc_usd",
    "conversions",
    "cpa_usd",
)

CAMPAIGN_TYPES = ("Brand", "Non-Brand", "Other")


def empty_metric_block() -> dict[str, float]:
    return {k: 0.0 for k in METRIC_FIELDS}


def error_response(platform: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "error": message,
        "platform": platform,
        **extra,
    }
