"""Meta ad-set snapshot diff (Meta has no reliable change-event API)."""
from __future__ import annotations

import json
import time
from datetime import date
from glob import glob
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .logging_setup import get_logger

SNAP_DIR = PROJECT_ROOT / "snapshots"
RETENTION_DAYS = 56
log = get_logger(__name__)

DIFF_FIELDS = ("daily_budget_usd", "lifetime_budget_usd", "bid_amount_usd", "bid_strategy", "status")


def _ensure_dir() -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)


def _today_path(today: date) -> Path:
    return SNAP_DIR / f"meta_{today.isoformat()}.json"


def list_snapshots() -> list[Path]:
    _ensure_dir()
    return sorted(Path(p) for p in glob(str(SNAP_DIR / "meta_*.json")))


def write_snapshot(today: date, ad_sets: list[dict[str, Any]]) -> Path:
    _ensure_dir()
    path = _today_path(today)
    with path.open("w") as f:
        json.dump({"snapshot_date": today.isoformat(), "ad_sets": ad_sets}, f, indent=2)
    log.info("Wrote Meta snapshot: %s (%d ad sets)", path, len(ad_sets))
    return path


def prune_snapshots(retention_days: int = RETENTION_DAYS) -> int:
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for p in list_snapshots():
        if p.stat().st_mtime < cutoff:
            p.unlink()
            removed += 1
    if removed:
        log.info("Pruned %d old Meta snapshots", removed)
    return removed


def diff_against_prior(today: date) -> dict[str, list[dict[str, Any]]]:
    """Return {campaign_id: [changes]} between newest snapshot and the one before."""
    snaps = list_snapshots()
    today_path = _today_path(today)
    prior = [p for p in snaps if p != today_path]
    if not prior:
        return {}
    newest = today_path if today_path.exists() else snaps[-1]
    prior_path = prior[-1] if newest != prior[-1] else (prior[-2] if len(prior) >= 2 else None)
    if prior_path is None:
        return {}

    with newest.open() as f:
        new_data = json.load(f)
    with prior_path.open() as f:
        old_data = json.load(f)

    new_by_id = {a["id"]: a for a in new_data.get("ad_sets", [])}
    old_by_id = {a["id"]: a for a in old_data.get("ad_sets", [])}

    out: dict[str, list[dict[str, Any]]] = {}
    for adset_id, new_a in new_by_id.items():
        old_a = old_by_id.get(adset_id)
        if old_a is None:
            continue
        for field in DIFF_FIELDS:
            old_v = old_a.get(field)
            new_v = new_a.get(field)
            if old_v != new_v:
                campaign_id = str(new_a.get("campaign_id"))
                out.setdefault(campaign_id, []).append(
                    {
                        "date": new_data.get("snapshot_date"),
                        "adset_name": new_a.get("name"),
                        "campaign_name": new_a.get("campaign_name"),
                        "field": field,
                        "old_value": old_v,
                        "new_value": new_v,
                    }
                )
    return out
