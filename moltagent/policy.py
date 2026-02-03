"""
Policy betöltés és alapértelmezések.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from .config import POLICY_FILE


def load_policy(path: str = POLICY_FILE) -> Dict[str, Any]:
    """Betölti a policy.json fájlt."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_scheduler_config(policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    Scheduler konfiguráció a policy-ból.
    Ha nincs megadva, alapértelmezéseket használ.
    """
    sched = policy.get("scheduler", {})
    return {
        "max_calls_per_day": int(policy.get("max_calls_per_day", 200)),
        "burst_p0": int(sched.get("burst_p0", 8)),
        "burst_p1": int(sched.get("burst_p1", 4)),
        "enabled": bool(sched.get("enabled", True)),
    }
