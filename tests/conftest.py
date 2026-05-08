"""Shared fixtures."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from ads_mcp_server.config import Thresholds


@pytest.fixture
def thresholds() -> Thresholds:
    return Thresholds(budget_util=0.95, cpa_restricting=0.90, cpa_headroom=0.70)


@pytest.fixture
def today() -> date:
    return date(2026, 5, 7)  # Thursday → yesterday is Wed 2026-05-06


@pytest.fixture
def synthetic_56d(today: date) -> pd.DataFrame:
    """56 days of ad×day data, 2 ads, deterministic."""
    rows = []
    yesterday = today - timedelta(days=1)
    start = yesterday - timedelta(days=55)
    for i in range(56):
        d = start + timedelta(days=i)
        # day-of-week-varying values so we can verify 8-week DoW selector
        dow = d.weekday()
        rows.append(
            {
                "date": d.isoformat(),
                "campaign_id": "1",
                "campaign_name": "Brand_Search",
                "ad_id": "100",
                "ad_name": "ad_a",
                "spend": 100.0 + dow,
                "impressions": 1000 + dow * 10,
                "clicks": 50 + dow,
                "conversions": 5.0 + dow * 0.1,
                "search_impression_share": 0.8,
            }
        )
        rows.append(
            {
                "date": d.isoformat(),
                "campaign_id": "2",
                "campaign_name": "NonBrand_Generic",
                "ad_id": "200",
                "ad_name": "ad_b",
                "spend": 200.0 + dow,
                "impressions": 2000 + dow * 10,
                "clicks": 60 + dow,
                "conversions": 4.0 + dow * 0.1,
                "search_impression_share": None,
            }
        )
    return pd.DataFrame.from_records(rows)


@pytest.fixture
def synthetic_settings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "campaign_id": "1",
                "campaign_name": "Brand_Search",
                "status": "ENABLED",
                "bidding_strategy": "TARGET_CPA",
                "target_cpa_usd": 25.0,
                "daily_budget_usd": 500.0,
                "budget_shared": False,
            },
            {
                "campaign_id": "2",
                "campaign_name": "NonBrand_Generic",
                "status": "ENABLED",
                "bidding_strategy": "MAXIMIZE_CONVERSIONS",
                "target_cpa_usd": None,
                "daily_budget_usd": 1000.0,
                "budget_shared": True,
            },
        ]
    )
