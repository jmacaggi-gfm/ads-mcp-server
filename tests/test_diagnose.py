from ads_mcp_server.diagnose import diagnose


def test_budget_constrained(thresholds):
    # 96% utilization (above 95% threshold)
    assert diagnose(96.0, 0.5, 25.0, thresholds) == "budget_constrained"


def test_tcpa_restricting(thresholds):
    # cpa_ratio 0.95 > 0.90
    assert diagnose(50.0, 0.95, 25.0, thresholds) == "tcpa_restricting"


def test_tcpa_has_headroom(thresholds):
    # cpa_ratio 0.5 < 0.70
    assert diagnose(50.0, 0.5, 25.0, thresholds) == "tcpa_has_headroom"


def test_no_target_set(thresholds):
    assert diagnose(50.0, None, None, thresholds) == "no_target_set"


def test_healthy(thresholds):
    # ratio between 0.70 and 0.90, target set, util ok
    assert diagnose(50.0, 0.80, 25.0, thresholds) == "healthy"


def test_budget_constrained_overrides_other_signals(thresholds):
    """High utilization classifies as budget_constrained even if cpa is healthy."""
    assert diagnose(99.0, 0.80, 25.0, thresholds) == "budget_constrained"
