"""Parquet cache + optional CSV override + JSON cache for non-tabular blobs.

Cache-validity rule: a 56-day perf cache is considered fresh if it contains
yesterday's date. Settings + changes are tied to the same daily refresh —
they refresh once per day alongside perf.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from glob import glob
from pathlib import Path
from typing import Any

import pandas as pd

from .config import PROJECT_ROOT
from .logging_setup import get_logger

CACHE_DIR = PROJECT_ROOT / "cache"
EXTERNAL_DIR = CACHE_DIR / "external"
log = get_logger(__name__)


def _parquet_path(platform: str) -> Path:
    return CACHE_DIR / f"{platform}_56d.parquet"


def _settings_path(platform: str) -> Path:
    return CACHE_DIR / f"{platform}_settings.parquet"


def _changes_path(platform: str) -> Path:
    return CACHE_DIR / f"{platform}_changes.json"


def _stamp_path(platform: str) -> Path:
    """File whose mtime records the date of the last refresh."""
    return CACHE_DIR / f"{platform}_lastrefresh.txt"


def _has_yesterday(df: pd.DataFrame, today: date) -> bool:
    """True if df includes a row dated yesterday."""
    if df.empty or "date" not in df.columns:
        return False
    yest = (today - timedelta(days=1)).isoformat()
    return yest in df["date"].astype(str).values


def write_refresh_stamp(platform: str, today: date) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _stamp_path(platform).write_text(today.isoformat())


def read_refresh_stamp(platform: str) -> date | None:
    p = _stamp_path(platform)
    if not p.exists():
        return None
    try:
        return date.fromisoformat(p.read_text().strip())
    except ValueError:
        return None


def load_settings_cache(platform: str, today: date) -> pd.DataFrame | None:
    """Return cached settings if last refresh stamp is today, else None."""
    stamp = read_refresh_stamp(platform)
    p = _settings_path(platform)
    if stamp == today and p.exists():
        log.info("Loading settings cache: %s", p)
        return pd.read_parquet(p)
    return None


def save_settings_cache(platform: str, df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _settings_path(platform)
    df.to_parquet(p, index=False)
    log.info("Saved settings cache: %s (%d rows)", p, len(df))


def load_changes_cache(platform: str, today: date) -> dict[str, list[dict[str, Any]]] | None:
    stamp = read_refresh_stamp(platform)
    p = _changes_path(platform)
    if stamp == today and p.exists():
        log.info("Loading changes cache: %s", p)
        with p.open() as f:
            return json.load(f)
    return None


def save_changes_cache(platform: str, changes: dict[str, list[dict[str, Any]]]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _changes_path(platform)
    with p.open("w") as f:
        json.dump(changes, f, default=str)
    log.info("Saved changes cache: %s", p)


def _ad_yesterday_path(platform: str) -> Path:
    return CACHE_DIR / f"{platform}_ad_yesterday.parquet"


def load_ad_yesterday(platform: str, today: date) -> pd.DataFrame | None:
    """Load yesterday-only ad-level cache. Fresh iff it contains yesterday's date."""
    p = _ad_yesterday_path(platform)
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    if _has_yesterday(df, today):
        log.info("Loading ad-yesterday cache: %s", p)
        return df
    return None


def save_ad_yesterday(platform: str, df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _ad_yesterday_path(platform)
    df.to_parquet(p, index=False)
    log.info("Saved ad-yesterday cache: %s (%d rows)", p, len(df))


def find_csv_override(platform: str) -> Path | None:
    """Return newest CSV in cache/external/ matching platform_*.csv, if any."""
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
    matches = sorted(
        glob(str(EXTERNAL_DIR / f"{platform}_*.csv")),
        key=lambda p: Path(p).stat().st_mtime,
        reverse=True,
    )
    if not matches:
        return None
    return Path(matches[0])


def load_cached(platform: str, today: date) -> tuple[pd.DataFrame | None, str]:
    """
    Returns (df, source). source ∈ {"csv_override", "cache", "miss"}.
    Cache is fresh iff it contains yesterday's date (one refresh per day).
    CSV override wins if it contains yesterday's date.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    parquet = _parquet_path(platform)
    csv = find_csv_override(platform)

    if csv is not None:
        log.info("Inspecting CSV override: %s", csv)
        try:
            df_csv = pd.read_csv(csv)
            if _has_yesterday(df_csv, today):
                return df_csv, "csv_override"
        except Exception as e:
            log.warning("CSV override unreadable, falling back: %s", e)

    if parquet.exists():
        df = pd.read_parquet(parquet)
        if _has_yesterday(df, today):
            log.info("Loading parquet cache: %s", parquet)
            return df, "cache"

    return None, "miss"


def save_cache(platform: str, df: pd.DataFrame) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _parquet_path(platform)
    df.to_parquet(path, index=False)
    log.info("Saved cache: %s (%d rows)", path, len(df))
