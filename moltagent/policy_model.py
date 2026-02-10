"""
Policy Pydantic model és validáció.

SPEC §13.4 - Policy érvényesítés:
- Induláskor validálás
- Típusellenőrzés
- Default értékek hiányzó mezőkre
- Fix szabályok kikényszerítése (EN out, HU op)
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, ValidationError


# --- Nested config models ---

class SchedulerConfig(BaseModel):
    """Scheduler paraméterek (SPEC §8)."""
    enabled: bool = True
    burst_p0: int = Field(default=8, ge=0, le=50, description="P0 burst limit")
    burst_p1: int = Field(default=4, ge=0, le=50, description="P1 burst limit")


class ReplyConfig(BaseModel):
    """Válasz paraméterek (SPEC §6)."""
    max_replies_per_hour_p2: int = Field(default=2, ge=0, le=20, description="P2 hourly limit")
    reply_to_mentions_always: bool = True
    reply_to_questions_always: bool = True
    offtopic_question_mode: Literal["redirect", "skip"] = "redirect"


class DomainConfig(BaseModel):
    """Domain kontextus."""
    context: str = ""


class TopicsConfig(BaseModel):
    """Témakör szűrés (SPEC §5)."""
    allow_keywords: List[str] = Field(default_factory=list)
    block_keywords: List[str] = Field(default_factory=list)


class StyleConfig(BaseModel):
    """
    Válaszstílus (SPEC §10).

    FIGYELEM: language FIX "en" - nem felülírható!
    """
    language: Literal["en"] = Field(
        default="en",
        description="Output language - FIXED to 'en', cannot be changed"
    )
    max_sentences: int = Field(default=5, ge=1, le=20)
    format: Literal["steps", "bullet", "paragraph"] = "steps"


class OperatorConfig(BaseModel):
    """
    Operátor összefoglaló konfig (SPEC §10).

    FIGYELEM: language FIX "hu" - nem felülírható!
    """
    language: Literal["hu"] = Field(
        default="hu",
        description="Operator summary language - FIXED to 'hu', cannot be changed"
    )
    verbosity: Literal["short", "normal", "verbose"] = "short"


# --- Main policy model ---

class PolicyModel(BaseModel):
    """
    Policy konfiguráció model.

    SPEC §13 - Konfigurálható policy elemek.
    """
    # Költség és híváskorlát
    daily_budget_usd: float = Field(
        default=1.0,
        ge=0.01,
        le=100.0,
        description="Daily budget in USD"
    )
    max_calls_per_day: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum API calls per day"
    )
    min_seconds_between_calls: float = Field(
        default=1.0,
        ge=0.0,
        le=60.0,
        description="Minimum seconds between calls"
    )

    # Nested configs
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    reply: ReplyConfig = Field(default_factory=ReplyConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    topics: TopicsConfig = Field(default_factory=TopicsConfig)
    style: StyleConfig = Field(default_factory=StyleConfig)
    operator: OperatorConfig = Field(default_factory=OperatorConfig)

    @field_validator('daily_budget_usd')
    @classmethod
    def budget_precision(cls, v: float) -> float:
        """Round budget to 4 decimal places."""
        return round(v, 4)


# --- Validation functions ---

def validate_policy_file(path: str) -> Tuple[bool, Optional[PolicyModel], List[str]]:
    """
    Validálja a policy fájlt.

    Args:
        path: Policy fájl útvonala

    Returns:
        (success, policy_model, errors)
        - success: True ha a validáció sikeres
        - policy_model: PolicyModel instance vagy None
        - errors: Hiba üzenetek listája
    """
    errors: List[str] = []

    # 1. Fájl létezés ellenőrzése
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except FileNotFoundError:
        return (False, None, [f"Policy fájl nem található: {path}"])
    except PermissionError:
        return (False, None, [f"Policy fájl nem olvasható: {path}"])

    # 2. JSON parse
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        return (False, None, [f"Hibás JSON szintaxis: {e.msg} (sor {e.lineno}, karakter {e.colno})"])

    # 3. Pydantic validáció
    try:
        model = PolicyModel(**data)
        return (True, model, [])
    except ValidationError as e:
        for err in e.errors():
            field_path = ".".join(str(x) for x in err["loc"])
            msg = err["msg"]
            input_val = err.get("input", "")
            if input_val and str(input_val) != msg:
                errors.append(f"{field_path}: {msg} (kapott: {input_val!r})")
            else:
                errors.append(f"{field_path}: {msg}")
        return (False, None, errors)


def format_validation_result(
    success: bool,
    model: Optional[PolicyModel],
    errors: List[str],
    path: str
) -> str:
    """
    Formázza a validációs eredményt olvasható formába.

    Returns:
        Formázott string a konzolra
    """
    lines = []

    if success and model:
        lines.append(f"✅ Policy OK: {path}")
        lines.append(f"   - Budget: ${model.daily_budget_usd:.2f}/nap, max {model.max_calls_per_day} hívás")
        lines.append(f"   - Scheduler: {'enabled' if model.scheduler.enabled else 'disabled'}, "
                     f"burst P0={model.scheduler.burst_p0}, P1={model.scheduler.burst_p1}")
        lines.append(f"   - P2 limit: {model.reply.max_replies_per_hour_p2}/óra")
    else:
        lines.append(f"❌ Policy HIBA: {path}")
        for err in errors:
            lines.append(f"   - {err}")
        lines.append("")
        lines.append("Az agent nem indul el.")

    return "\n".join(lines)


def load_and_validate_policy(path: str) -> PolicyModel:
    """
    Betölti és validálja a policy fájlt.

    Raises:
        ValueError: Ha a validáció sikertelen

    Returns:
        Validált PolicyModel instance
    """
    success, model, errors = validate_policy_file(path)

    if not success or model is None:
        error_msg = format_validation_result(success, model, errors, path)
        raise ValueError(error_msg)

    return model


def policy_to_dict(model: PolicyModel) -> Dict[str, Any]:
    """
    Konvertálja a PolicyModel-t dict-té (visszafelé kompatibilitás).
    """
    return model.model_dump()
