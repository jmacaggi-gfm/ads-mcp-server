from ads_mcp_server.meta_ads import _extract_action


def test_extract_action_match():
    row = {
        "actions": [
            {"action_type": "link_click", "value": "10"},
            {"action_type": "offsite_conversion.custom.StartFundraiser", "value": "5"},
        ],
        "cost_per_action_type": [
            {"action_type": "offsite_conversion.custom.StartFundraiser", "value": "12.5"},
        ],
    }
    conv, cpa = _extract_action(row, "offsite_conversion.custom.StartFundraiser")
    assert conv == 5.0
    assert cpa == 12.5


def test_extract_action_no_match():
    row = {
        "actions": [{"action_type": "link_click", "value": "10"}],
        "cost_per_action_type": [],
    }
    conv, cpa = _extract_action(row, "offsite_conversion.custom.StartFundraiser")
    assert conv == 0.0
    assert cpa is None


def test_extract_action_missing_keys():
    conv, cpa = _extract_action({}, "anything")
    assert conv == 0.0
    assert cpa is None


def test_extract_action_null_arrays():
    row = {"actions": None, "cost_per_action_type": None}
    conv, cpa = _extract_action(row, "purchase")
    assert conv == 0.0
    assert cpa is None
