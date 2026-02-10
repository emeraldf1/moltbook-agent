"""
Policy validáció tesztek.

SPEC §13.4 - Policy érvényesítés
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

from moltagent.policy_model import (
    PolicyModel,
    SchedulerConfig,
    ReplyConfig,
    StyleConfig,
    OperatorConfig,
    validate_policy_file,
    load_and_validate_policy,
    policy_to_dict,
    format_validation_result,
)
from moltagent.policy import load_policy, validate_policy, get_validation_message


# --- Fixtures ---

@pytest.fixture
def valid_policy() -> Dict[str, Any]:
    """Érvényes policy dict."""
    return {
        "daily_budget_usd": 1.0,
        "max_calls_per_day": 200,
        "min_seconds_between_calls": 1.0,
        "scheduler": {
            "enabled": True,
            "burst_p0": 8,
            "burst_p1": 4
        },
        "reply": {
            "max_replies_per_hour_p2": 2,
            "reply_to_mentions_always": True,
            "reply_to_questions_always": True,
            "offtopic_question_mode": "redirect"
        },
        "style": {
            "language": "en",
            "max_sentences": 5,
            "format": "steps"
        },
        "operator": {
            "language": "hu",
            "verbosity": "short"
        }
    }


@pytest.fixture
def policy_file(valid_policy: Dict[str, Any]) -> str:
    """Létrehoz egy ideiglenes policy fájlt."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(valid_policy, f)
        return f.name


# --- PolicyModel tesztek ---

class TestPolicyModel:
    """PolicyModel unit tesztek."""

    def test_valid_policy_creates_model(self, valid_policy: Dict[str, Any]):
        """AC-1: Érvényes policy betöltődik."""
        model = PolicyModel(**valid_policy)
        assert model.daily_budget_usd == 1.0
        assert model.max_calls_per_day == 200

    def test_default_values_used(self):
        """AC-5: Hiányzó opcionális mező → default."""
        model = PolicyModel()  # Minden default
        assert model.daily_budget_usd == 1.0
        assert model.max_calls_per_day == 200
        assert model.scheduler.enabled is True
        assert model.scheduler.burst_p0 == 8
        assert model.style.language == "en"
        assert model.operator.language == "hu"

    def test_budget_precision(self):
        """Budget 4 tizedesjegyre kerekítve."""
        model = PolicyModel(daily_budget_usd=1.23456789)
        assert model.daily_budget_usd == 1.2346

    def test_budget_type_error(self):
        """AC-3: Típushiba."""
        with pytest.raises(Exception):  # ValidationError
            PolicyModel(daily_budget_usd="abc")

    def test_budget_out_of_range_low(self):
        """AC-4: Érték túl kicsi."""
        with pytest.raises(Exception):
            PolicyModel(daily_budget_usd=0.001)  # min 0.01

    def test_budget_out_of_range_high(self):
        """AC-4: Érték túl nagy."""
        with pytest.raises(Exception):
            PolicyModel(daily_budget_usd=999.0)  # max 100

    def test_max_calls_out_of_range(self):
        """AC-4: max_calls_per_day túl nagy."""
        with pytest.raises(Exception):
            PolicyModel(max_calls_per_day=9999)  # max 1000

    def test_fixed_style_language_en(self):
        """AC-6: style.language fix 'en'."""
        model = PolicyModel()
        assert model.style.language == "en"

    def test_fixed_style_language_error(self):
        """AC-6: style.language != 'en' hibát dob."""
        with pytest.raises(Exception):
            PolicyModel(style={"language": "hu"})

    def test_fixed_operator_language_hu(self):
        """AC-6: operator.language fix 'hu'."""
        model = PolicyModel()
        assert model.operator.language == "hu"

    def test_fixed_operator_language_error(self):
        """AC-6: operator.language != 'hu' hibát dob."""
        with pytest.raises(Exception):
            PolicyModel(operator={"language": "en"})

    def test_scheduler_burst_limits(self):
        """Scheduler burst limitek validálva."""
        with pytest.raises(Exception):
            PolicyModel(scheduler={"burst_p0": 100})  # max 50

    def test_reply_p2_limit(self):
        """Reply P2 limit validálva."""
        with pytest.raises(Exception):
            PolicyModel(reply={"max_replies_per_hour_p2": 100})  # max 20


# --- validate_policy_file tesztek ---

class TestValidatePolicyFile:
    """Fájl validáció tesztek."""

    def test_valid_file(self, policy_file: str):
        """AC-1: Érvényes policy fájl."""
        success, model, errors = validate_policy_file(policy_file)
        assert success is True
        assert model is not None
        assert len(errors) == 0
        os.unlink(policy_file)

    def test_missing_file(self):
        """AC-7: Policy fájl nem található."""
        success, model, errors = validate_policy_file("/nonexistent/policy.json")
        assert success is False
        assert model is None
        assert "nem található" in errors[0]

    def test_invalid_json(self):
        """AC-2: Hibás JSON."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{ "budget": 1.0, }')  # Extra vessző
            path = f.name

        success, model, errors = validate_policy_file(path)
        assert success is False
        assert "JSON" in errors[0]
        os.unlink(path)

    def test_type_error_in_file(self):
        """AC-3: Típushiba a fájlban."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"daily_budget_usd": "abc"}, f)
            path = f.name

        success, model, errors = validate_policy_file(path)
        assert success is False
        assert "daily_budget_usd" in errors[0]
        os.unlink(path)

    def test_value_out_of_range_in_file(self):
        """AC-4: Érték túl nagy a fájlban."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"daily_budget_usd": 999.0}, f)
            path = f.name

        success, model, errors = validate_policy_file(path)
        assert success is False
        assert "daily_budget_usd" in errors[0]
        os.unlink(path)

    def test_minimal_valid_policy(self):
        """Minimális érvényes policy (csak defaults)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({}, f)  # Üres - minden default
            path = f.name

        success, model, errors = validate_policy_file(path)
        assert success is True
        assert model is not None
        assert model.daily_budget_usd == 1.0
        os.unlink(path)


# --- format_validation_result tesztek ---

class TestFormatValidationResult:
    """Formázás tesztek."""

    def test_success_format(self, valid_policy: Dict[str, Any]):
        """AC-8: Sikeres validáció logolva."""
        model = PolicyModel(**valid_policy)
        result = format_validation_result(True, model, [], "policy.json")
        assert "✅ Policy OK" in result
        assert "Budget:" in result
        assert "$1.00/nap" in result

    def test_error_format(self):
        """Hiba formázás."""
        result = format_validation_result(
            False, None, ["daily_budget_usd: érték túl nagy"], "policy.json"
        )
        assert "❌ Policy HIBA" in result
        assert "daily_budget_usd" in result
        assert "nem indul el" in result


# --- load_policy tesztek ---

class TestLoadPolicy:
    """load_policy wrapper tesztek."""

    def test_load_with_validation(self, policy_file: str):
        """load_policy validációval."""
        policy = load_policy(policy_file, validate=True)
        assert isinstance(policy, dict)
        assert policy["daily_budget_usd"] == 1.0
        os.unlink(policy_file)

    def test_load_without_validation(self, policy_file: str):
        """load_policy validáció nélkül (legacy)."""
        policy = load_policy(policy_file, validate=False)
        assert isinstance(policy, dict)
        os.unlink(policy_file)

    def test_load_invalid_raises(self):
        """Hibás policy ValueError-t dob."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"daily_budget_usd": "abc"}, f)
            path = f.name

        with pytest.raises(ValueError) as exc_info:
            load_policy(path, validate=True)

        assert "HIBA" in str(exc_info.value)
        os.unlink(path)


# --- get_validation_message tesztek ---

class TestGetValidationMessage:
    """Validációs üzenet tesztek."""

    def test_valid_message(self, policy_file: str):
        """Érvényes policy üzenet."""
        msg = get_validation_message(policy_file)
        assert "✅" in msg
        os.unlink(policy_file)

    def test_invalid_message(self):
        """Hibás policy üzenet."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"daily_budget_usd": 999.0}, f)
            path = f.name

        msg = get_validation_message(path)
        assert "❌" in msg
        os.unlink(path)
