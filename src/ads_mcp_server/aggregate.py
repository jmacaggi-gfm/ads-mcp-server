"""Pandas aggregations: account / campaign_type / ad / daily / comparisons."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pandas as pd

from .classify import classify_google_campaign
from .config import Thresholds
from .date_ranges import (
    DateWindow,
    eight_week_dow_dates,
    full_56d_window,
    prior_week_window,
    resolve_window,
    yesterday,
)
from .diagnose import diagnose

_RAW_NUMERIC = ("spend", "impressions", "clicks", "conversions")


def _safe_div(num: float, den: float) -> float | None:
    if den is None or den == 0 or pd.isna(den):
        return None
    return float(num) / float(den)


def _metric_block(df: pd.DataFrame) -> dict[str, float]:
    """Compute headline metrics from a slice."""
    if df.empty:
        return {
            "spend": 0.0,
            "impressions": 0,
            "clicks": 0,
            "ctr_pct": 0.0,
            "cpc_usd": 0.0,
            "conversions": 0.0,
            "cpa_usd": 0.0,
        }
    spend = float(df["spend"].sum())
    impressions = int(df["impressions"].sum())
    clicks = int(df["clicks"].sum())
    conversions = float(df["conversions"].sum())
    ctr_pct = (_safe_div(clicks, impressions) or 0.0) * 100.0
    cpc_usd = _safe_div(spend, clicks) or 0.0
    cpa_usd = _safe_div(spend, conversions) or 0.0
    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "ctr_pct": round(ctr_pct, 4),
        "cpc_usd": round(cpc_usd, 4),
        "conversions": round(conversions, 4),
        "cpa_usd": round(cpa_usd, 4),
    }


def _delta_pct(curr: dict[str, float], prior: dict[str, float]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in curr:
        c = curr[k]
        p = prior.get(k, 0)
        if p == 0:
            out[k] = None if c == 0 else float("inf")
        else:
            out[k] = round((c - p) / p * 100.0, 4)
    return out


def annotate_campaign_types(
    df: pd.DataFrame, classifier: Callable[[str | None], str]
) -> pd.DataFrame:
    """Add a `campaign_type` column derived from `campaign_name` via `classifier`."""
    df = df.copy()
    df["campaign_type"] = df["campaign_name"].apply(classifier)
    return df


def _campaign_types_in(df: pd.DataFrame) -> list[str]:
    """Return ordered list of distinct campaign_type values in df.

    Order: Brand/Non-Brand/Other first if Google taxonomy is detected,
    Prospecting/Retargeting first if Meta taxonomy is detected, then any
    extras alphabetically. Always include `Other` last when it appears.
    """
    if df.empty or "campaign_type" not in df.columns:
        return []
    present = set(df["campaign_type"].dropna().astype(str).unique())
    google_order = [t for t in ("Brand", "Non-Brand") if t in present]
    meta_order = [t for t in ("Prospecting", "Retargeting") if t in present]
    extras = sorted(present - set(google_order) - set(meta_order) - {"Other"})
    tail = ["Other"] if "Other" in present else []
    return google_order + meta_order + extras + tail


def filter_window(df: pd.DataFrame, window: DateWindow) -> pd.DataFrame:
    s = pd.to_datetime(window.start)
    e = pd.to_datetime(window.end)
    d = pd.to_datetime(df["date"])
    return df[(d >= s) & (d <= e)]


def by_campaign_type(df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Aggregate per campaign_type using whichever taxonomy is in the data."""
    out: dict[str, dict[str, float]] = {}
    for ct in _campaign_types_in(df):
        sub = df[df["campaign_type"] == ct]
        out[ct] = _metric_block(sub)
    return out


BY_AD_TOP_N = 50


def by_ad(
    df: pd.DataFrame,
    settings: pd.DataFrame,
    yesterday_df: pd.DataFrame,
    thresholds: Thresholds,
) -> list[dict[str, Any]]:
    """Per-ad rollup over the requested window, with per-campaign diagnosis.

    Capped to top BY_AD_TOP_N (=50) ads by spend to keep response size manageable.
    """
    if df.empty:
        return []
    grouped = (
        df.groupby(["ad_id", "ad_name", "campaign_id", "campaign_name", "campaign_type"], dropna=False)
        .agg(
            spend=("spend", "sum"),
            impressions=("impressions", "sum"),
            clicks=("clicks", "sum"),
            conversions=("conversions", "sum"),
        )
        .reset_index()
    )

    # Yesterday spend + cpa per campaign for diagnosis
    if not yesterday_df.empty:
        yest_camp = (
            yesterday_df.groupby("campaign_id")
            .agg(spend_yesterday=("spend", "sum"), conv_yesterday=("conversions", "sum"))
            .reset_index()
        )
    else:
        yest_camp = pd.DataFrame(columns=["campaign_id", "spend_yesterday", "conv_yesterday"])

    # Yesterday SIS per ad if column present
    sis_col = "search_impression_share"
    if sis_col in yesterday_df.columns and not yesterday_df.empty:
        sis_per_ad = (
            yesterday_df.groupby("ad_id")[sis_col]
            .mean()
            .reset_index()
            .rename(columns={sis_col: "search_impression_share"})
        )
    else:
        sis_per_ad = pd.DataFrame(columns=["ad_id", "search_impression_share"])

    settings_slim = (
        settings[["campaign_id", "daily_budget_usd", "target_cpa_usd"]]
        if not settings.empty
        else pd.DataFrame(columns=["campaign_id", "daily_budget_usd", "target_cpa_usd"])
    )

    merged = (
        grouped.merge(yest_camp, on="campaign_id", how="left")
        .merge(sis_per_ad, on="ad_id", how="left")
        .merge(settings_slim, on="campaign_id", how="left")
    )

    rows: list[dict[str, Any]] = []
    for _, r in merged.sort_values("spend", ascending=False).head(BY_AD_TOP_N).iterrows():
        spend_y = r.get("spend_yesterday")
        conv_y = r.get("conv_yesterday")
        budget_cap = r.get("daily_budget_usd")
        target_cpa = r.get("target_cpa_usd")

        actual_cpa_y = _safe_div(spend_y, conv_y) if pd.notna(spend_y) and pd.notna(conv_y) else None
        budget_util = (
            round(_safe_div(spend_y, budget_cap) * 100.0, 4)
            if pd.notna(spend_y) and pd.notna(budget_cap) and budget_cap not in (0, None)
            else None
        )
        cpa_ratio = (
            round(actual_cpa_y / float(target_cpa), 4)
            if actual_cpa_y is not None and pd.notna(target_cpa) and float(target_cpa) > 0
            else None
        )

        rows.append(
            {
                "ad_name": r["ad_name"],
                "campaign_name": r["campaign_name"],
                "campaign_type": r["campaign_type"],
                **_metric_block(pd.DataFrame([{
                    "spend": r["spend"],
                    "impressions": r["impressions"],
                    "clicks": r["clicks"],
                    "conversions": r["conversions"],
                }])),
                "budget_cap_usd": float(budget_cap) if pd.notna(budget_cap) else None,
                "budget_utilization_pct": budget_util,
                "target_cpa_usd": float(target_cpa) if pd.notna(target_cpa) else None,
                "actual_cpa_yesterday_usd": (
                    round(actual_cpa_y, 4) if actual_cpa_y is not None else None
                ),
                "cpa_ratio": cpa_ratio,
                "diagnosis": diagnose(
                    budget_util,
                    cpa_ratio,
                    float(target_cpa) if pd.notna(target_cpa) else None,
                    thresholds,
                ),
                "search_impression_share": (
                    float(r["search_impression_share"])
                    if "search_impression_share" in r and pd.notna(r["search_impression_share"])
                    else None
                ),
            }
        )
    return rows


def daily_series(df_56d: pd.DataFrame) -> list[dict[str, Any]]:
    """One entry per date; nested {campaign_type: metric_block}."""
    if df_56d.empty:
        return []
    out: list[dict[str, Any]] = []
    df = df_56d.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    types = _campaign_types_in(df)
    for d, day_df in df.groupby("date"):
        entry: dict[str, Any] = {"date": d.isoformat()}
        for ct in types:
            entry[ct] = _metric_block(day_df[day_df["campaign_type"] == ct])
        out.append(entry)
    out.sort(key=lambda e: e["date"])
    return out


def comparisons(df_56d: pd.DataFrame, today: date) -> dict[str, Any]:
    """WoW + vs 8-week DoW avg."""
    last_w = filter_window(df_56d, resolve_window("last_week", today))
    prior_w = filter_window(df_56d, prior_week_window(today))
    last_block = _metric_block(last_w)
    prior_block = _metric_block(prior_w)

    yest_window = resolve_window("yesterday", today)
    yest_df = filter_window(df_56d, yest_window)
    dow_dates = eight_week_dow_dates(today)
    dow_set = {d.isoformat() for d in dow_dates}
    df = df_56d.copy()
    df["__d"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    dow_df = df[df["__d"].isin(dow_set)].drop(columns="__d")

    yest_block = _metric_block(yest_df)
    if not dow_df.empty:
        per_day = (
            dow_df.groupby(pd.to_datetime(dow_df["date"]).dt.date)
            .agg({c: "sum" for c in _RAW_NUMERIC})
            .reset_index(drop=True)
        )
        avg_block = _metric_block(per_day.assign(
            **{c: per_day[c].mean() for c in _RAW_NUMERIC}
        ).head(1))
    else:
        avg_block = _metric_block(pd.DataFrame())

    return {
        "wow": {
            "last_week": last_block,
            "prior_week": prior_block,
            "delta_pct": _delta_pct(last_block, prior_block),
        },
        "vs_8w_avg": {
            "yesterday": yest_block,
            "avg": avg_block,
            "delta_pct": _delta_pct(yest_block, avg_block),
        },
    }


def campaign_settings_block(
    settings: pd.DataFrame,
    df_56d: pd.DataFrame,
    today: date,
    thresholds: Thresholds,
    change_history: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Per-campaign settings + yesterday perf + diagnosis + change_history."""
    if settings.empty:
        return []
    change_history = change_history or {}
    yest_window = resolve_window("yesterday", today)
    yest_df = filter_window(df_56d, yest_window)
    if not yest_df.empty:
        yest_camp = (
            yest_df.groupby("campaign_id")
            .agg(
                spend_yesterday=("spend", "sum"),
                conv_yesterday=("conversions", "sum"),
            )
            .reset_index()
        )
    else:
        yest_camp = pd.DataFrame(columns=["campaign_id", "spend_yesterday", "conv_yesterday"])

    sis_col = "search_impression_share"
    if sis_col in yest_df.columns and not yest_df.empty:
        sis_camp = (
            yest_df.groupby("campaign_id")[sis_col]
            .mean()
            .reset_index()
            .rename(columns={sis_col: "search_impression_share"})
        )
    else:
        sis_camp = pd.DataFrame(columns=["campaign_id", "search_impression_share"])

    merged = settings.merge(yest_camp, on="campaign_id", how="left").merge(
        sis_camp, on="campaign_id", how="left"
    )

    rows: list[dict[str, Any]] = []
    for _, r in merged.iterrows():
        spend_y = r.get("spend_yesterday")
        conv_y = r.get("conv_yesterday")
        budget_cap = r.get("daily_budget_usd")
        target_cpa = r.get("target_cpa_usd")
        actual_cpa_y = (
            _safe_div(spend_y, conv_y) if pd.notna(spend_y) and pd.notna(conv_y) else None
        )
        budget_util = (
            round(_safe_div(spend_y, budget_cap) * 100.0, 4)
            if pd.notna(spend_y) and pd.notna(budget_cap) and budget_cap not in (0, None)
            else None
        )
        cpa_ratio = (
            round(actual_cpa_y / float(target_cpa), 4)
            if actual_cpa_y is not None and pd.notna(target_cpa) and float(target_cpa) > 0
            else None
        )
        # Use pre-annotated campaign_type if present (server pre-classifies).
        if "campaign_type" in r and isinstance(r.get("campaign_type"), str):
            campaign_type = r["campaign_type"]
        else:
            # Fallback: Google taxonomy. Meta callers must pre-annotate.
            campaign_type = classify_google_campaign(r.get("campaign_name"))
        rows.append(
            {
                "campaign_name": r.get("campaign_name"),
                "campaign_type": campaign_type,
                "target_cpa_usd": float(target_cpa) if pd.notna(target_cpa) else None,
                "actual_cpa_yesterday_usd": (
                    round(actual_cpa_y, 4) if actual_cpa_y is not None else None
                ),
                "cpa_ratio": cpa_ratio,
                "diagnosis": diagnose(
                    budget_util,
                    cpa_ratio,
                    float(target_cpa) if pd.notna(target_cpa) else None,
                    thresholds,
                ),
                "daily_budget_usd": float(budget_cap) if pd.notna(budget_cap) else None,
                "budget_utilization_pct": budget_util,
            }
        )
    return rows


def build_response(
    df_56d: pd.DataFrame,
    settings: pd.DataFrame,
    date_range: str,
    breakdown: str,
    today: date,
    thresholds: Thresholds,
    platform: str,
    fetched_at: str,
    data_source: str,
    change_history: dict[str, list[dict[str, Any]]] | None = None,
    df_ad_grain: pd.DataFrame | None = None,
    include_campaign_settings: bool = False,
) -> dict[str, Any]:
    """Assemble full response shape.

    `df_ad_grain` (optional): ad-level data, may cover only yesterday (Meta).
    If provided, it is used for the by_ad table. Otherwise df_56d is used
    (Google: ad-level for the full 56d).
    """
    full_window = full_56d_window(today)
    sel_window = resolve_window(date_range, today)
    df_sel = filter_window(df_56d, sel_window)
    yest_df = filter_window(df_56d, resolve_window("yesterday", today))

    if df_ad_grain is not None and not df_ad_grain.empty:
        ad_source = df_ad_grain
        ad_yest = filter_window(df_ad_grain, resolve_window("yesterday", today))
        ad_sel = filter_window(df_ad_grain, sel_window)
        # If sel_window extends beyond ad_grain coverage, fall back to all rows
        if ad_sel.empty:
            ad_sel = ad_source
        by_ad_rows = by_ad(ad_sel, settings, ad_yest, thresholds)
    else:
        by_ad_rows = by_ad(df_sel, settings, yest_df, thresholds)

    metadata = {
        "platform": platform,
        "fetched_at": fetched_at,
        "date_range_start": sel_window.start.isoformat(),
        "date_range_end": sel_window.end.isoformat(),
        "currency": "USD",
        "breakdown": breakdown,
        "data_source": data_source,
        "raw_window_start": full_window.start.isoformat(),
        "raw_window_end": full_window.end.isoformat(),
    }
    if df_ad_grain is not None and not df_ad_grain.empty:
        ad_dates = pd.to_datetime(df_ad_grain["date"]).dt.date
        metadata["ad_grain_window"] = (
            f"{ad_dates.min().isoformat()}..{ad_dates.max().isoformat()}"
        )
        metadata["ad_grain_note"] = (
            "Meta ad-level data is pulled for yesterday only. by_ad reflects "
            "yesterday regardless of date_range."
        )

    response = {
        "metadata": metadata,
        "account": _metric_block(df_sel),
        "by_campaign_type": by_campaign_type(df_sel),
        "by_ad": by_ad_rows,
        "daily_series": daily_series(df_56d),
        "comparisons": comparisons(df_56d, today),
    }
    if include_campaign_settings:
        response["campaign_settings"] = campaign_settings_block(
            settings, df_56d, today, thresholds, change_history
        )
    return response
