"""
Tests for moltagent.state (State management and idempotency)
"""
import json
import os
import pytest
from unittest.mock import patch

from moltagent.state import State, load_state, save_state, ensure_today


@pytest.fixture
def temp_state_file(tmp_path):
    """Temporary state file for testing."""
    return str(tmp_path / "test_state.json")


@pytest.fixture
def mock_today():
    """Mock today's date."""
    with patch("moltagent.state.day_key_local", return_value="2026-02-03"):
        with patch("moltagent.state.hour_key_local", return_value="2026-02-03-12"):
            yield


class TestState:
    """Tests for State dataclass."""

    def test_default_values(self):
        """State should have sensible defaults."""
        state = State(day_key="2026-02-03")

        assert state.spent_usd == 0.0
        assert state.calls_today == 0
        assert state.burst_used_p0 == 0
        assert state.burst_used_p1 == 0
        assert state.replied_event_ids == set()

    def test_has_replied_false(self):
        """has_replied returns False for new events."""
        state = State(day_key="2026-02-03")

        assert state.has_replied("e1") is False

    def test_has_replied_true(self):
        """has_replied returns True for replied events."""
        state = State(day_key="2026-02-03", replied_event_ids={"e1", "e2"})

        assert state.has_replied("e1") is True
        assert state.has_replied("e2") is True
        assert state.has_replied("e3") is False

    def test_mark_replied(self):
        """mark_replied adds event to set."""
        state = State(day_key="2026-02-03")

        state.mark_replied("e1")
        state.mark_replied("e2")

        assert state.has_replied("e1") is True
        assert state.has_replied("e2") is True

    def test_mark_replied_idempotent(self):
        """mark_replied is idempotent."""
        state = State(day_key="2026-02-03")

        state.mark_replied("e1")
        state.mark_replied("e1")
        state.mark_replied("e1")

        assert len(state.replied_event_ids) == 1


class TestLoadState:
    """Tests for load_state function."""

    def test_missing_file_creates_new(self, temp_state_file, mock_today):
        """Missing file should create fresh state."""
        state = load_state(temp_state_file)

        assert state.day_key == "2026-02-03"
        assert state.calls_today == 0
        assert state.replied_event_ids == set()

    def test_loads_existing_state(self, temp_state_file, mock_today):
        """Should load existing state from file."""
        data = {
            "day_key": "2026-02-03",
            "spent_usd": 0.05,
            "calls_today": 10,
            "last_call_ts": 1234567890.0,
            "p2_replies_this_hour": 1,
            "hour_key": "2026-02-03-12",
            "burst_used_p0": 2,
            "burst_used_p1": 1,
            "replied_event_ids": ["e1", "e2", "e3"],
        }
        with open(temp_state_file, "w") as f:
            json.dump(data, f)

        state = load_state(temp_state_file)

        assert state.spent_usd == 0.05
        assert state.calls_today == 10
        assert state.burst_used_p0 == 2
        assert state.replied_event_ids == {"e1", "e2", "e3"}

    def test_new_day_resets_counters(self, temp_state_file, mock_today):
        """New day should reset daily counters but keep replied_event_ids."""
        data = {
            "day_key": "2026-02-02",  # Yesterday
            "spent_usd": 0.50,
            "calls_today": 100,
            "burst_used_p0": 5,
            "burst_used_p1": 3,
            "replied_event_ids": ["e1", "e2"],
        }
        with open(temp_state_file, "w") as f:
            json.dump(data, f)

        state = load_state(temp_state_file)

        assert state.day_key == "2026-02-03"
        assert state.spent_usd == 0.0
        assert state.calls_today == 0
        assert state.burst_used_p0 == 0
        assert state.burst_used_p1 == 0
        # replied_event_ids should persist!
        assert state.replied_event_ids == {"e1", "e2"}


class TestSaveState:
    """Tests for save_state function."""

    def test_saves_all_fields(self, temp_state_file):
        """Should save all state fields to file."""
        state = State(
            day_key="2026-02-03",
            spent_usd=0.123,
            calls_today=42,
            last_call_ts=9999.0,
            p2_replies_this_hour=2,
            hour_key="2026-02-03-15",
            burst_used_p0=3,
            burst_used_p1=1,
            replied_event_ids={"e5", "e10", "e3"},
        )

        save_state(state, temp_state_file)

        with open(temp_state_file) as f:
            data = json.load(f)

        assert data["day_key"] == "2026-02-03"
        assert data["spent_usd"] == 0.123
        assert data["calls_today"] == 42
        assert data["burst_used_p0"] == 3
        assert data["burst_used_p1"] == 1
        # replied_event_ids should be sorted list
        assert data["replied_event_ids"] == ["e10", "e3", "e5"]


class TestEnsureToday:
    """Tests for ensure_today function."""

    def test_same_day_no_change(self, temp_state_file, mock_today):
        """Same day should not reset counters."""
        state = State(
            day_key="2026-02-03",
            hour_key="2026-02-03-12",
            calls_today=50,
            burst_used_p0=2,
        )

        result = ensure_today(state)

        assert result.calls_today == 50
        assert result.burst_used_p0 == 2

    def test_new_day_resets(self, temp_state_file, mock_today):
        """New day should reset daily counters."""
        state = State(
            day_key="2026-02-02",
            hour_key="2026-02-02-23",
            calls_today=150,
            burst_used_p0=8,
            burst_used_p1=4,
        )

        with patch("moltagent.state.save_state"):
            result = ensure_today(state)

        assert result.day_key == "2026-02-03"
        assert result.calls_today == 0
        assert result.burst_used_p0 == 0
        assert result.burst_used_p1 == 0

    def test_new_hour_resets_p2(self, temp_state_file, mock_today):
        """New hour should reset p2_replies_this_hour."""
        state = State(
            day_key="2026-02-03",
            hour_key="2026-02-03-11",  # Previous hour
            p2_replies_this_hour=5,
        )

        with patch("moltagent.state.save_state"):
            result = ensure_today(state)

        assert result.hour_key == "2026-02-03-12"
        assert result.p2_replies_this_hour == 0
