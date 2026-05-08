from datetime import date

import pandas as pd

from ads_mcp_server import aggregate
from ads_mcp_server.aggregate import (
    _delta_pct,
    _metric_block,
    annotate_campaign_types,
    build_response,
    by_campaign_type,
    comparisons,
    daily_series,
)

from ads_mcp_server.classify import classify_google_campaign


def test_metric_block_empty():
    block = _metric_block(pd.DataFrame())
    assert block["spend"] == 0.0
    assert block["impressions"] == 0
    assert block["ctr_pct"] == 0.0


def test_metric_block_zero_clicks_no_div_zero():
    df = pd.DataFrame(
        [{"spend": 100.0, "impressions": 0, "clicks": 0, "conversions": 0.0}]
    )
    block = _metric_block(df)
    assert block["ctr_pct"] == 0.0
    assert block["cpc_usd"] == 0.0
    assert block["cpa_usd"] == 0.0


def test_delta_pct_zero_division():
    curr = {"spend": 100.0}
    prior = {"spend": 0}
    assert _delta_pct(curr, prior)["spend"] == float("inf")
    assert _delta_pct({"spend": 0}, {"spend": 0})["spend"] is None


def test_delta_pct_normal():
    curr = {"spend": 110.0}
    prior = {"spend": 100.0}
    assert _delta_pct(curr, prior)["spend"] == 10.0


def test_annotate_campaign_types(synthetic_56d):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    assert "campaign_type" in df.columns
    assert (df[df["campaign_name"] == "Brand_Search"]["campaign_type"] == "Brand").all()
    assert (df[df["campaign_name"] == "NonBrand_Generic"]["campaign_type"] == "Non-Brand").all()


def test_by_campaign_type_sums(synthetic_56d):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    by_type = by_campaign_type(df)
    # Synthetic data has only Brand + Non-Brand. by_campaign_type returns
    # only types actually present (Other absent here).
    assert "Brand" in by_type and "Non-Brand" in by_type
    assert "Other" not in by_type
    assert by_type["Brand"]["spend"] > 0
    assert by_type["Non-Brand"]["spend"] > 0


def test_daily_series_by_campaign_top_n_and_shape(synthetic_56d):
    from ads_mcp_server.aggregate import daily_series_by_campaign

    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    series = daily_series_by_campaign(df, top_n=20)
    # Synthetic has 2 campaigns — both fit under top_n
    assert len(series) == 56
    first = series[0]
    assert "date" in first
    assert "Brand_Search" in first and "NonBrand_Generic" in first
    metric_keys = {"spend", "impressions", "clicks", "ctr_pct", "cpc_usd", "conversions", "cpa_usd"}
    assert set(first["Brand_Search"].keys()) == metric_keys


def test_daily_series_by_campaign_top_n_caps(synthetic_56d):
    from ads_mcp_server.aggregate import daily_series_by_campaign

    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    series = daily_series_by_campaign(df, top_n=1)
    # Only 1 campaign retained: NonBrand_Generic has higher spend than Brand_Search
    first = series[0]
    assert "NonBrand_Generic" in first
    assert "Brand_Search" not in first


def test_build_response_includes_daily_by_campaign_flag(
    synthetic_56d, synthetic_settings, today, thresholds
):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    settings = synthetic_settings.copy()
    base = build_response(
        df_56d=df,
        settings=settings,
        date_range="last_7_days",
        breakdown="ad",
        today=today,
        thresholds=thresholds,
        platform="google",
        fetched_at="2026-05-07T00:00:00Z",
        data_source="api",
    )
    assert "daily_series_by_campaign" not in base

    with_flag = build_response(
        df_56d=df,
        settings=settings,
        date_range="last_7_days",
        breakdown="ad",
        today=today,
        thresholds=thresholds,
        platform="google",
        fetched_at="2026-05-07T00:00:00Z",
        data_source="api",
        include_daily_by_campaign=True,
    )
    assert "daily_series_by_campaign" in with_flag
    assert len(with_flag["daily_series_by_campaign"]) == 56


def test_daily_series_56_entries(synthetic_56d):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    series = daily_series(df)
    assert len(series) == 56
    assert series == sorted(series, key=lambda x: x["date"])


def test_8w_dow_avg_uses_only_matching_weekday(synthetic_56d, today):
    """vs_8w_avg should average exactly 8 days, all matching yesterday's DoW."""
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    cmp = comparisons(df, today)
    yest = cmp["vs_8w_avg"]["yesterday"]
    avg = cmp["vs_8w_avg"]["avg"]
    # yesterday = Wed (dow=2). All synthetic Wed rows share spend = 100+2 and 200+2
    # = 102 + 202 = 304. Average across 8 Weds = same 304.
    assert yest["spend"] == 304.0
    assert avg["spend"] == 304.0
    assert cmp["vs_8w_avg"]["delta_pct"]["spend"] == 0.0


def test_wow_delta(synthetic_56d, today):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    cmp = comparisons(df, today)
    last = cmp["wow"]["last_week"]
    prior = cmp["wow"]["prior_week"]
    assert last["spend"] > 0
    assert prior["spend"] > 0
    # Synthetic data is identical week over week → delta should be 0
    assert cmp["wow"]["delta_pct"]["spend"] == 0.0


def test_build_response_full_shape(synthetic_56d, synthetic_settings, today, thresholds):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    settings = synthetic_settings.copy()
    settings["campaign_type"] = settings["campaign_name"].apply(
        lambda n: "Brand" if "Brand" in n else "Non-Brand"
    )
    resp = build_response(
        df_56d=df,
        settings=settings,
        date_range="last_7_days",
        breakdown="ad",
        today=today,
        thresholds=thresholds,
        platform="google",
        fetched_at="2026-05-07T00:00:00Z",
        data_source="api",
    )
    assert "metadata" in resp
    assert "account" in resp
    assert "by_campaign_type" in resp
    assert "by_ad" in resp and len(resp["by_ad"]) == 2
    assert "daily_series" in resp and len(resp["daily_series"]) == 56
    assert "comparisons" in resp
    # campaign_settings is excluded by default (token-saving)
    assert "campaign_settings" not in resp
    assert resp["metadata"]["data_source"] == "api"
    assert resp["metadata"]["currency"] == "USD"

    # When include_campaign_settings=True, the key is present and slim (8 fields)
    resp_with_settings = build_response(
        df_56d=df,
        settings=settings,
        date_range="last_7_days",
        breakdown="ad",
        today=today,
        thresholds=thresholds,
        platform="google",
        fetched_at="2026-05-07T00:00:00Z",
        data_source="api",
        include_campaign_settings=True,
    )
    assert "campaign_settings" in resp_with_settings
    cs = resp_with_settings["campaign_settings"]
    assert len(cs) == 2
    expected_keys = {
        "campaign_name",
        "campaign_type",
        "target_cpa_usd",
        "actual_cpa_yesterday_usd",
        "cpa_ratio",
        "diagnosis",
        "daily_budget_usd",
        "budget_utilization_pct",
    }
    assert set(cs[0].keys()) == expected_keys


def test_by_ad_sorted_by_spend_desc(synthetic_56d, synthetic_settings, today, thresholds):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    sub = aggregate.filter_window(df, aggregate.resolve_window("last_7_days", today))
    yest = aggregate.filter_window(df, aggregate.resolve_window("yesterday", today))
    rows = aggregate.by_ad(sub, synthetic_settings, yest, thresholds)
    spends = [r["spend"] for r in rows]
    assert spends == sorted(spends, reverse=True)


def test_diagnosis_in_by_ad_output(synthetic_56d, synthetic_settings, today, thresholds):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    sub = aggregate.filter_window(df, aggregate.resolve_window("last_7_days", today))
    yest = aggregate.filter_window(df, aggregate.resolve_window("yesterday", today))
    rows = aggregate.by_ad(sub, synthetic_settings, yest, thresholds)
    valid = {"budget_constrained", "tcpa_restricting", "tcpa_has_headroom", "no_target_set", "healthy"}
    assert all(r["diagnosis"] in valid for r in rows)


def test_budget_util_rounded(synthetic_56d, synthetic_settings, today, thresholds):
    df = annotate_campaign_types(synthetic_56d, classify_google_campaign)
    sub = aggregate.filter_window(df, aggregate.resolve_window("yesterday", today))
    yest = sub
    rows = aggregate.by_ad(sub, synthetic_settings, yest, thresholds)
    for r in rows:
        if r["budget_utilization_pct"] is not None:
            # Rounded to 4 decimal places, no float artifact
            s = f"{r['budget_utilization_pct']}"
            assert len(s.split(".")[-1]) <= 4 if "." in s else True
