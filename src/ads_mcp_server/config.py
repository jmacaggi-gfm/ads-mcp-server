"""Environment loading and config validation."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env() -> None:
    """Load .env from ADS_MCP_ENV_FILE if set, else from project root."""
    override = os.environ.get("ADS_MCP_ENV_FILE")
    if override:
        load_dotenv(override, override=False)
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _csv_env(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [s.strip().lower() for s in raw.split(",") if s.strip()]


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass
class GoogleAdsConfig:
    developer_token: str
    client_id: str
    client_secret: str
    refresh_token: str
    customer_ids: list[str]
    login_customer_id: str | None
    missing: list[str] = field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        return not self.missing


@dataclass
class MetaAdsConfig:
    app_id: str
    app_secret: str
    access_token: str
    ad_account_id: str
    conversion_event_name: str
    missing: list[str] = field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        return not self.missing


@dataclass
class Thresholds:
    budget_util: float
    cpa_restricting: float
    cpa_headroom: float


@dataclass
class AppConfig:
    google: GoogleAdsConfig
    meta: MetaAdsConfig
    meta_retargeting_keywords: list[str]
    thresholds: Thresholds
    cache_ttl_seconds: int


def get_google_config() -> GoogleAdsConfig:
    keys = {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "developer_token",
        "GOOGLE_ADS_CLIENT_ID": "client_id",
        "GOOGLE_ADS_CLIENT_SECRET": "client_secret",
        "GOOGLE_ADS_REFRESH_TOKEN": "refresh_token",
        "GOOGLE_ADS_CUSTOMER_IDS": "customer_ids_raw",
    }
    values: dict[str, str] = {}
    missing: list[str] = []
    for env_key in keys:
        v = os.environ.get(env_key, "").strip()
        if not v:
            missing.append(env_key)
        values[env_key] = v
    customer_ids = [c.strip() for c in values["GOOGLE_ADS_CUSTOMER_IDS"].split(",") if c.strip()]
    return GoogleAdsConfig(
        developer_token=values["GOOGLE_ADS_DEVELOPER_TOKEN"],
        client_id=values["GOOGLE_ADS_CLIENT_ID"],
        client_secret=values["GOOGLE_ADS_CLIENT_SECRET"],
        refresh_token=values["GOOGLE_ADS_REFRESH_TOKEN"],
        customer_ids=customer_ids,
        login_customer_id=os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "").strip() or None,
        missing=missing,
    )


def get_meta_config() -> MetaAdsConfig:
    # ACCESS_TOKEN + AD_ACCOUNT_ID are required for read-only insights.
    # APP_ID + APP_SECRET are optional when using a long-lived system user token.
    required = ["META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"]
    optional = ["META_APP_ID", "META_APP_SECRET"]
    values: dict[str, str] = {}
    missing: list[str] = []
    for env_key in required + optional:
        v = os.environ.get(env_key, "").strip()
        values[env_key] = v
        if env_key in required and not v:
            missing.append(env_key)
    return MetaAdsConfig(
        app_id=values["META_APP_ID"],
        app_secret=values["META_APP_SECRET"],
        access_token=values["META_ACCESS_TOKEN"],
        ad_account_id=values["META_AD_ACCOUNT_ID"],
        conversion_event_name=os.environ.get(
            "META_CONVERSION_EVENT_NAME", "offsite_conversion.fb_pixel_purchase"
        ),
        missing=missing,
    )


def get_app_config() -> AppConfig:
    load_env()
    return AppConfig(
        google=get_google_config(),
        meta=get_meta_config(),
        meta_retargeting_keywords=_csv_env(
            "META_RETARGETING_KEYWORDS", "rt,retarget,rmk,remarket"
        ),
        thresholds=Thresholds(
            budget_util=_float_env("BUDGET_UTIL_THRESHOLD", 0.95),
            cpa_restricting=_float_env("CPA_RESTRICTING_THRESHOLD", 0.90),
            cpa_headroom=_float_env("CPA_HEADROOM_THRESHOLD", 0.70),
        ),
        cache_ttl_seconds=_int_env("CACHE_TTL_SECONDS", 3600),
    )
