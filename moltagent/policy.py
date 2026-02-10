"""
Policy betöltés és alapértelmezések.

SPEC §13 - Policy modell.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .config import POLICY_FILE
from .policy_model import (
    PolicyModel,
    validate_policy_file,
    load_and_validate_policy,
    policy_to_dict,
    format_validation_result,
)


def load_policy(path: str = POLICY_FILE, validate: bool = True) -> Dict[str, Any]:
    """
    Betölti a policy.json fájlt.

    Args:
        path: Policy fájl útvonala
        validate: Ha True, Pydantic validációt futtat

    Returns:
        Policy dict

    Raises:
        ValueError: Ha validate=True és a validáció sikertelen
    """
    if validate:
        model = load_and_validate_policy(path)
        return policy_to_dict(model)
    else:
        # Legacy mód - nincs validáció
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


def validate_policy(path: str = POLICY_FILE) -> tuple:
    """
    Validálja a policy fájlt explicit módon.

    Returns:
        (success, model_or_none, errors)
    """
    return validate_policy_file(path)


def get_validation_message(path: str = POLICY_FILE) -> str:
    """
    Visszaadja a validációs eredményt olvasható formában.
    """
    success, model, errors = validate_policy_file(path)
    return format_validation_result(success, model, errors, path)
