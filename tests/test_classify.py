"""Classifier tests: Google (Brand/Non-Brand/Other) + Meta (Prospecting/Retargeting)."""
from ads_mcp_server.classify import (
    classify_google_campaign,
    classify_meta_campaign,
)


# ---------- Google ----------


def test_google_brand():
    assert classify_google_campaign("US_Brand_Search") == "Brand"
    assert classify_google_campaign("gofundme_brand") == "Brand"


def test_google_nonbrand_first_priority():
    """Critical: 'brand' is a substring of 'nonbrand' — Non-Brand check must run first."""
    assert classify_google_campaign("US_NonBrand_Search") == "Non-Brand"
    assert classify_google_campaign("US_Non-Brand_Search") == "Non-Brand"
    assert classify_google_campaign("US_non_brand_Search") == "Non-Brand"
    assert classify_google_campaign("nonbrand_generic") == "Non-Brand"


def test_google_other_default():
    """Campaigns without explicit brand or nonbrand keyword fall to Other."""
    assert classify_google_campaign("United Kingdom - June") == "Other"
    assert classify_google_campaign("Display_Prospecting") == "Other"
    assert classify_google_campaign("PMax_Catchall") == "Other"


def test_google_case_insensitive():
    assert classify_google_campaign("us_BRAND_search") == "Brand"
    assert classify_google_campaign("us_NONBRAND_search") == "Non-Brand"


def test_google_none_or_empty_or_nan():
    assert classify_google_campaign(None) == "Other"
    assert classify_google_campaign("") == "Other"
    # NaN from pandas comes through as float
    assert classify_google_campaign(float("nan")) == "Other"


# ---------- Meta ----------

RT_KW = ["rt", "retarget", "rmk", "remarket"]


def test_meta_retargeting_keywords():
    assert classify_meta_campaign("US_RT_lookalike", RT_KW) == "Retargeting"
    assert classify_meta_campaign("Retargeting - DR", RT_KW) == "Retargeting"
    assert classify_meta_campaign("RMK_donors_30d", RT_KW) == "Retargeting"
    assert classify_meta_campaign("Remarket_engaged", RT_KW) == "Retargeting"


def test_meta_prospecting_default():
    assert classify_meta_campaign("US_DR_Broad", RT_KW) == "Prospecting"
    assert classify_meta_campaign("Brand_Awareness", RT_KW) == "Prospecting"


def test_meta_no_brand_logic():
    """Meta classifier must NEVER return Brand or Non-Brand."""
    out = classify_meta_campaign("US_Brand_Search", RT_KW)
    assert out not in ("Brand", "Non-Brand")
    assert out == "Prospecting"


def test_meta_none_or_empty_or_nan():
    assert classify_meta_campaign(None, RT_KW) == "Prospecting"
    assert classify_meta_campaign("", RT_KW) == "Prospecting"
    assert classify_meta_campaign(float("nan"), RT_KW) == "Prospecting"
