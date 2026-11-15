"""Bounded request pacing that learns independently for each source host."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Callable


@dataclass
class HostPacing:
    delay: float
    latency: float | None = None
    successes: int = 0
    requests: int = 0
    errors: int = 0
    last_started: float | None = None
    not_before: float = 0.0


class AdaptivePacer:
    def __init__(self, initial: float, minimum: float, maximum: float, *,
                 clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None):
        if not all(math.isfinite(value) for value in (initial, minimum, maximum)) or not 0 < minimum <= initial <= maximum:
            raise ValueError("Request delays must satisfy 0 < minimum <= initial <= maximum")
        self.initial, self.minimum, self.maximum = initial, minimum, maximum
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.hosts: dict[str, HostPacing] = {}

    def state(self, host: str) -> HostPacing:
        if host not in self.hosts:
            self.hosts[host] = HostPacing(self.initial)
        return self.hosts[host]

    def start(self, host: str, floor: float = 0) -> float:
        state = self.state(host)
        due = state.not_before
        if state.last_started is not None:
            due = max(due, state.last_started + max(state.delay, floor))
        self.sleep(max(0, due - self.clock()))
        started = self.clock()
        state.last_started = started
        state.requests += 1
        return started

    def success(self, host: str, started: float) -> tuple[float, float]:
        state = self.state(host)
        latency = max(0, self.clock() - started)
        state.latency = latency if state.latency is None else 0.75 * state.latency + 0.25 * latency
        state.successes += 1
        before = state.delay
        target = min(self.maximum, max(self.minimum, 1.5 * state.latency))
        if target > state.delay:
            state.delay = target
        elif state.successes >= 3:
            state.delay = max(target, state.delay * 0.75)
            state.successes = 0
        return before, state.delay

    def failure(self, host: str, *, retry_after: float | None = None) -> tuple[float, float]:
        state = self.state(host)
        before = state.delay
        state.delay = min(self.maximum, max(self.minimum, state.delay * 2))
        state.successes = 0
        state.errors += 1
        if retry_after is not None:
            state.not_before = max(state.not_before, self.clock() + retry_after)
        return before, state.delay

    def summary(self) -> dict[str, dict]:
        return {host: {"delay_seconds": round(state.delay, 3),
                       "latency_seconds": round(state.latency, 3) if state.latency is not None else None,
                       "requests": state.requests, "errors": state.errors}
                for host, state in self.hosts.items()}


def retry_after_seconds(value: str | None, *, now: float | None = None) -> float | None:
    """Read either form of Retry-After; callers decide whether a wait is acceptable."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        parsed = parsedate_to_datetime(stripped)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, parsed.timestamp() - (time.time() if now is None else now))
    except (ValueError, TypeError, OverflowError):
        return None
