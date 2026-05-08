"""Campaign-name classifiers.

Two distinct taxonomies:

* Google Ads — Brand / Non-Brand / Other.
  Substring "brand" appears inside "non-brand" / "nonbrand", so the
  Non-Brand check MUST run first. Anything without an explicit keyword
  falls into "Other".

* Meta Ads — Prospecting / Retargeting.
  Brand/Non-Brand makes no sense on social. Retargeting is detected from
  configurable keywords; everything else is Prospecting.
"""
from __future__ import annotations

from collections.abc import Callable

NONBRAND_TOKENS = ("nonbrand", "non-brand", "non_brand")


def classify_google_campaign(name: str | None) -> str:
    """Strict 3-way classifier for Google Ads campaign names.

    Order matters: Non-Brand first (because "brand" is a substring of
    "nonbrand"), Brand second, fallback Other.
    """
    if not isinstance(name, str) or not name:
        return "Other"
    n = name.lower()
    if any(tok in n for tok in NONBRAND_TOKENS):
        return "Non-Brand"
    if "brand" in n:
        return "Brand"
    return "Other"


def classify_meta_campaign(name: str | None, retargeting_keywords: list[str]) -> str:
    """Prospecting / Retargeting classifier for Meta campaign names.

    Retargeting keywords default examples: 'rt', 'retarget', 'rmk', 'remarket'.
    Anything not matched is Prospecting.
    """
    if not isinstance(name, str) or not name:
        return "Prospecting"
    n = name.lower()
    if any(kw in n for kw in retargeting_keywords):
        return "Retargeting"
    return "Prospecting"


def google_classifier() -> Callable[[str | None], str]:
    return classify_google_campaign


def meta_classifier(retargeting_keywords: list[str]) -> Callable[[str | None], str]:
    def _fn(name: str | None) -> str:
        return classify_meta_campaign(name, retargeting_keywords)

    return _fn
