"""
Scheduler (Daily Pacer) - egyenletes napi hívás-elosztás.

Üzleti szabályok:
- earned_calls = (eltelt_idő_ma / nap_hossza) * max_calls_per_day
- Ha calls_today < floor(earned_calls) → ENGEDÉLYEZETT
- Ha nem:
  - P0: napi max burst_p0 extra hívás (pl. 8)
  - P1: napi max burst_p1 extra hívás (pl. 4)
  - P2: nincs burst, várni kell
- Ha elértük a napi limitet → SKIP (scheduler_daily_calls_cap)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import DAY_SECONDS, DEFAULT_BURST_P0, DEFAULT_BURST_P1, DEFAULT_MAX_CALLS_PER_DAY
from .state import State
from .utils import seconds_since_midnight


@dataclass
class SchedulerDecision:
    """Scheduler döntés eredménye."""

    allowed: bool
    reason: str
    wait_seconds: float = 0.0
    used_burst: bool = False
    burst_type: Optional[str] = None  # "p0" | "p1" | None


def compute_earned_calls(max_calls_per_day: int) -> float:
    """
    Kiszámolja, hány hívás "járna" eddig a nap folyamán.
    earned_calls = (eltelt_idő_ma / nap_hossza) * max_calls_per_day
    """
    elapsed = seconds_since_midnight()
    return (elapsed / DAY_SECONDS) * max_calls_per_day


def compute_wait_seconds(calls_today: int, max_calls_per_day: int) -> float:
    """
    Kiszámolja, mennyi időt kell várni, hogy a következő hívás "megérjen".
    """
    if max_calls_per_day <= 0:
        return 0.0

    # calls_today + 1 híváshoz szükséges idő
    needed_fraction = (calls_today + 1) / max_calls_per_day
    needed_seconds = needed_fraction * DAY_SECONDS
    elapsed = seconds_since_midnight()

    wait = needed_seconds - elapsed
    return max(0.0, wait)


def scheduler_check(
    state: State,
    priority: str,
    policy: Dict[str, Any],
    dry_run: bool = True,
) -> SchedulerDecision:
    """
    Ellenőrzi, hogy a scheduler engedélyezi-e a hívást.

    Args:
        state: Aktuális agent állapot
        priority: "P0", "P1", vagy "P2"
        policy: Policy konfiguráció
        dry_run: Ha True, nem alszunk, csak logolunk

    Returns:
        SchedulerDecision a döntéssel
    """
    # Scheduler konfig
    sched = policy.get("scheduler", {})
    enabled = bool(sched.get("enabled", True))

    if not enabled:
        return SchedulerDecision(allowed=True, reason="scheduler_disabled")

    max_calls = int(policy.get("max_calls_per_day", DEFAULT_MAX_CALLS_PER_DAY))
    burst_p0 = int(sched.get("burst_p0", DEFAULT_BURST_P0))
    burst_p1 = int(sched.get("burst_p1", DEFAULT_BURST_P1))

    # 1. Ellenőrzés: elértük-e a napi limitet?
    if state.calls_today >= max_calls:
        return SchedulerDecision(
            allowed=False,
            reason="scheduler_daily_calls_cap",
        )

    # 2. Kiszámoljuk az earned calls-t
    earned = compute_earned_calls(max_calls)
    earned_floor = math.floor(earned)

    # 3. Ha a hívásszám még a "megérdemelt" alatt van → OK
    if state.calls_today < earned_floor:
        return SchedulerDecision(allowed=True, reason="scheduler_within_pace")

    # 4. Túl vagyunk a pace-en → burst ellenőrzés prioritás alapján
    if priority == "P0":
        if state.burst_used_p0 < burst_p0:
            return SchedulerDecision(
                allowed=True,
                reason="scheduler_burst_p0",
                used_burst=True,
                burst_type="p0",
            )

    elif priority == "P1":
        if state.burst_used_p1 < burst_p1:
            return SchedulerDecision(
                allowed=True,
                reason="scheduler_burst_p1",
                used_burst=True,
                burst_type="p1",
            )

    # 5. P2 vagy kimerült burst → várni kell
    wait_secs = compute_wait_seconds(state.calls_today, max_calls)

    return SchedulerDecision(
        allowed=False,
        reason="scheduler_paced_wait",
        wait_seconds=wait_secs,
    )


def update_burst_counters(state: State, decision: SchedulerDecision) -> None:
    """
    Frissíti a burst számlálókat a döntés alapján.
    """
    if decision.used_burst:
        if decision.burst_type == "p0":
            state.burst_used_p0 += 1
        elif decision.burst_type == "p1":
            state.burst_used_p1 += 1
