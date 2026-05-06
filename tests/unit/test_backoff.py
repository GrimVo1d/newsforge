from datetime import datetime, timezone, timedelta

from apps.feeds.backoff import (
    DISABLE_HOURS,
    disabled_until,
    next_attempt_at,
    should_disable,
)


def test_next_attempt_grows_with_errors():
    now = datetime(2026, 5, 6, tzinfo=timezone.utc)
    later1 = next_attempt_at(base_seconds=60, consecutive_errors=1, now=now, jitter_range=(1.0, 1.0))
    later3 = next_attempt_at(base_seconds=60, consecutive_errors=3, now=now, jitter_range=(1.0, 1.0))
    assert (later1 - now).total_seconds() == 60 * 2
    assert (later3 - now).total_seconds() == 60 * 8


def test_should_disable_triggers_at_six():
    assert not should_disable(5)
    assert should_disable(6)
    assert should_disable(10)


def test_disabled_until_is_24h_ahead():
    now = datetime(2026, 5, 6, tzinfo=timezone.utc)
    assert disabled_until(now) - now == timedelta(hours=DISABLE_HOURS)
