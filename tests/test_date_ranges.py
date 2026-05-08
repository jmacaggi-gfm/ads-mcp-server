from datetime import date

from ads_mcp_server.date_ranges import (
    eight_week_dow_dates,
    full_56d_window,
    prior_week_window,
    resolve_window,
)


def test_yesterday_window():
    today = date(2026, 5, 7)  # Thu
    w = resolve_window("yesterday", today)
    assert w.start == date(2026, 5, 6)
    assert w.end == date(2026, 5, 6)


def test_last_7_days():
    today = date(2026, 5, 7)
    w = resolve_window("last_7_days", today)
    assert w.start == date(2026, 4, 30)
    assert w.end == date(2026, 5, 6)
    assert (w.end - w.start).days == 6


def test_last_14_days():
    today = date(2026, 5, 7)
    w = resolve_window("last_14_days", today)
    assert w.end == date(2026, 5, 6)
    assert w.start == date(2026, 4, 23)


def test_last_week_alias_equals_last_7():
    today = date(2026, 5, 7)
    a = resolve_window("last_week", today)
    b = resolve_window("last_7_days", today)
    assert a.start == b.start and a.end == b.end


def test_prior_week_is_days_8_to_14():
    today = date(2026, 5, 7)
    w = prior_week_window(today)
    assert w.end == date(2026, 4, 29)  # 8 days before today
    assert w.start == date(2026, 4, 23)  # 14 days before today


def test_8w_dow_picks_same_weekday():
    """Yesterday=Wed 2026-05-06. Prior 8 Wednesdays are 7,14,...,56 days before today."""
    today = date(2026, 5, 7)
    dates = eight_week_dow_dates(today)
    assert len(dates) == 8
    for d in dates:
        assert d.weekday() == date(2026, 5, 6).weekday()
    # Most recent should be 7 days before yesterday = Wed 2026-04-29
    assert dates[0] == date(2026, 4, 29)
    # Oldest = 56 days before yesterday = 2026-03-11
    assert dates[-1] == date(2026, 3, 11)


def test_full_56d_window_inclusive():
    today = date(2026, 5, 7)
    w = full_56d_window(today)
    assert w.end == date(2026, 5, 6)
    assert (w.end - w.start).days == 55  # 56 days inclusive
