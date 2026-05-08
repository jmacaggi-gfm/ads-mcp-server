"""Snapshot diff tests using a temp dir."""
from datetime import date, timedelta

import pytest

from ads_mcp_server import snapshots


@pytest.fixture(autouse=True)
def temp_snap_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAP_DIR", tmp_path)
    yield tmp_path


def _adset(adset_id, daily_budget, bid_strategy="LOWEST_COST_WITHOUT_CAP", bid_amount=None):
    return {
        "id": adset_id,
        "name": f"adset_{adset_id}",
        "campaign_id": f"camp_{adset_id}",
        "campaign_name": f"Campaign {adset_id}",
        "status": "ACTIVE",
        "bid_strategy": bid_strategy,
        "bid_amount_usd": bid_amount,
        "daily_budget_usd": daily_budget,
        "lifetime_budget_usd": None,
        "optimization_goal": "OFFSITE_CONVERSIONS",
    }


def test_first_snapshot_returns_empty_diff():
    today = date(2026, 5, 7)
    snapshots.write_snapshot(today, [_adset("1", 100.0)])
    diff = snapshots.diff_against_prior(today)
    assert diff == {}


def test_budget_change_detected():
    yesterday = date(2026, 5, 6)
    today = date(2026, 5, 7)
    snapshots.write_snapshot(yesterday, [_adset("1", 100.0)])
    snapshots.write_snapshot(today, [_adset("1", 150.0)])
    diff = snapshots.diff_against_prior(today)
    assert "camp_1" in diff
    changes = diff["camp_1"]
    field_changes = {c["field"]: c for c in changes}
    assert "daily_budget_usd" in field_changes
    assert field_changes["daily_budget_usd"]["old_value"] == 100.0
    assert field_changes["daily_budget_usd"]["new_value"] == 150.0


def test_no_diff_when_unchanged():
    yesterday = date(2026, 5, 6)
    today = date(2026, 5, 7)
    snapshots.write_snapshot(yesterday, [_adset("1", 100.0)])
    snapshots.write_snapshot(today, [_adset("1", 100.0)])
    diff = snapshots.diff_against_prior(today)
    assert diff == {}


def test_new_adset_no_old_value_skipped():
    """New ad sets without prior snapshot entry are skipped (not error)."""
    yesterday = date(2026, 5, 6)
    today = date(2026, 5, 7)
    snapshots.write_snapshot(yesterday, [_adset("1", 100.0)])
    snapshots.write_snapshot(today, [_adset("1", 100.0), _adset("2", 200.0)])
    diff = snapshots.diff_against_prior(today)
    # Only existing adset 1 is compared; new adset 2 is silently ignored
    assert diff == {}


def test_prune_removes_old_snapshots(monkeypatch, temp_snap_dir):
    """Files older than retention_days are deleted."""
    import os
    import time

    # Create one fresh, one old (mtime backdated)
    fresh = temp_snap_dir / "meta_2026-05-07.json"
    old = temp_snap_dir / "meta_2025-01-01.json"
    fresh.write_text("{}")
    old.write_text("{}")
    old_mtime = time.time() - 200 * 86400
    os.utime(old, (old_mtime, old_mtime))

    removed = snapshots.prune_snapshots(retention_days=56)
    assert removed == 1
    assert fresh.exists()
    assert not old.exists()
