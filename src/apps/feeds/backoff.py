"""Exponential backoff helper for feed fetch failures."""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from django.utils import timezone

MAX_ERROR_EXPONENT = 6
DISABLE_HOURS = 24


def next_attempt_at(
    *,
    base_seconds: int,
    consecutive_errors: int,
    now: datetime | None = None,
    jitter_range: tuple[float, float] = (0.5, 1.5),
) -> datetime:
    now = now or timezone.now()
    exponent = min(consecutive_errors, MAX_ERROR_EXPONENT)
    jitter = random.uniform(*jitter_range)
    delay = base_seconds * (2**exponent) * jitter
    return now + timedelta(seconds=delay)


def should_disable(consecutive_errors: int) -> bool:
    return consecutive_errors >= MAX_ERROR_EXPONENT


def disabled_until(now: datetime | None = None) -> datetime:
    return (now or timezone.now()) + timedelta(hours=DISABLE_HOURS)
