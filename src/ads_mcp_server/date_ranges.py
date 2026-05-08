"""Date range resolution and 8-week DoW selector."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

VALID_RANGES = ("yesterday", "last_7_days", "last_week", "last_14_days")


@dataclass
class DateWindow:
    start: date
    end: date

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range((self.end - self.start).days + 1)]


def yesterday(today: date) -> date:
    return today - timedelta(days=1)


def resolve_window(label: str, today: date) -> DateWindow:
    """Resolve a label to an inclusive [start, end] window."""
    y = yesterday(today)
    if label == "yesterday":
        return DateWindow(y, y)
    if label == "last_7_days":
        return DateWindow(y - timedelta(days=6), y)
    if label == "last_14_days":
        return DateWindow(y - timedelta(days=13), y)
    if label == "last_week":
        return DateWindow(y - timedelta(days=6), y)
    raise ValueError(f"Unknown date_range: {label!r}. Use one of {VALID_RANGES}")


def prior_week_window(today: date) -> DateWindow:
    """Days 8-14 ago (the week before last_7_days)."""
    y = yesterday(today)
    end = y - timedelta(days=7)
    start = end - timedelta(days=6)
    return DateWindow(start, end)


def eight_week_dow_dates(today: date) -> list[date]:
    """8 dates matching yesterday's weekday: 7,14,...,56 days before today.

    With today=Wed and yesterday=Tue, returns the prior 8 Tuesdays
    (excluding yesterday itself).
    """
    y = yesterday(today)
    return [y - timedelta(days=7 * i) for i in range(1, 9)]


def full_56d_window(today: date) -> DateWindow:
    """Last 56 days ending yesterday (inclusive)."""
    y = yesterday(today)
    return DateWindow(y - timedelta(days=55), y)
