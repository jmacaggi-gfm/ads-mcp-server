"""Five-state campaign diagnosis."""
from __future__ import annotations

from .config import Thresholds


def diagnose(
    budget_utilization_pct: float | None,
    cpa_ratio: float | None,
    target_cpa_usd: float | None,
    thresholds: Thresholds,
) -> str:
    """
    States:
      budget_constrained, tcpa_restricting, tcpa_has_headroom,
      no_target_set, healthy
    """
    util_frac = (budget_utilization_pct or 0.0) / 100.0
    if util_frac > thresholds.budget_util:
        return "budget_constrained"
    if cpa_ratio is not None and cpa_ratio > thresholds.cpa_restricting:
        return "tcpa_restricting"
    if cpa_ratio is not None and cpa_ratio < thresholds.cpa_headroom:
        return "tcpa_has_headroom"
    if target_cpa_usd is None:
        return "no_target_set"
    return "healthy"
