"""
Tests for moltagent.scheduler (Daily Pacer)
"""
import pytest
from unittest.mock import patch

from moltagent.scheduler import (
    compute_earned_calls,
    compute_wait_seconds,
    scheduler_check,
    update_burst_counters,
    SchedulerDecision,
)
from moltagent.state import State


@pytest.fixture
def base_state():
    """Fresh state for testing."""
    return State(
        day_key="2026-02-03",
        calls_today=0,
        burst_used_p0=0,
        burst_used_p1=0,
    )


@pytest.fixture
def base_policy():
    """Default policy for testing."""
    return {
        "max_calls_per_day": 200,
        "scheduler": {
            "enabled": True,
            "burst_p0": 8,
            "burst_p1": 4,
        },
    }


class TestComputeEarnedCalls:
    """Tests for earned_calls calculation."""

    def test_midnight(self):
        """At midnight, earned_calls should be 0."""
        with patch("moltagent.scheduler.seconds_since_midnight", return_value=0):
            assert compute_earned_calls(200) == 0.0

    def test_noon(self):
        """At noon (43200s), earned_calls should be half of max."""
        with patch("moltagent.scheduler.seconds_since_midnight", return_value=43200):
            assert compute_earned_calls(200) == 100.0

    def test_end_of_day(self):
        """At end of day, earned_calls should be max."""
        with patch("moltagent.scheduler.seconds_since_midnight", return_value=86400):
            assert compute_earned_calls(200) == 200.0

    def test_quarter_day(self):
        """At 6am (21600s), earned_calls should be 25% of max."""
        with patch("moltagent.scheduler.seconds_since_midnight", return_value=21600):
            assert compute_earned_calls(200) == 50.0


class TestComputeWaitSeconds:
    """Tests for wait time calculation."""

    def test_no_calls_no_wait(self):
        """With 0 calls, should have minimal wait."""
        with patch("moltagent.scheduler.seconds_since_midnight", return_value=0):
            wait = compute_wait_seconds(0, 200)
            # First call needs 1/200 of the day = 432 seconds
            assert wait == pytest.approx(432.0, rel=0.01)

    def test_at_pace_no_wait(self):
        """If at pace, wait should be minimal."""
        # At noon with 100 calls, next call earns at 100.5/200 * 86400 = 43416s
        with patch("moltagent.scheduler.seconds_since_midnight", return_value=43200):
            wait = compute_wait_seconds(100, 200)
            # Should wait until 43632s (101/200 * 86400)
            assert wait == pytest.approx(432.0, rel=0.01)


class TestSchedulerCheck:
    """Tests for scheduler_check decision logic."""

    def test_scheduler_disabled(self, base_state, base_policy):
        """When scheduler is disabled, always allow."""
        base_policy["scheduler"]["enabled"] = False

        decision = scheduler_check(base_state, "P2", base_policy)

        assert decision.allowed is True
        assert decision.reason == "scheduler_disabled"

    def test_within_pace_allowed(self, base_state, base_policy):
        """When under earned calls, should allow."""
        # Simulate being at noon with 50 calls (earned = 100)
        base_state.calls_today = 50

        with patch("moltagent.scheduler.compute_earned_calls", return_value=100.0):
            decision = scheduler_check(base_state, "P1", base_policy)

        assert decision.allowed is True
        assert decision.reason == "scheduler_within_pace"

    def test_daily_cap_reached(self, base_state, base_policy):
        """When daily limit reached, should deny."""
        base_state.calls_today = 200

        decision = scheduler_check(base_state, "P0", base_policy)

        assert decision.allowed is False
        assert decision.reason == "scheduler_daily_calls_cap"

    def test_p0_burst_allowed(self, base_state, base_policy):
        """P0 can use burst when over pace."""
        base_state.calls_today = 100
        base_state.burst_used_p0 = 0

        with patch("moltagent.scheduler.compute_earned_calls", return_value=50.0):
            decision = scheduler_check(base_state, "P0", base_policy)

        assert decision.allowed is True
        assert decision.reason == "scheduler_burst_p0"
        assert decision.used_burst is True
        assert decision.burst_type == "p0"

    def test_p0_burst_exhausted(self, base_state, base_policy):
        """P0 denied when burst exhausted."""
        base_state.calls_today = 100
        base_state.burst_used_p0 = 8  # All used

        with patch("moltagent.scheduler.compute_earned_calls", return_value=50.0):
            with patch("moltagent.scheduler.compute_wait_seconds", return_value=120.0):
                decision = scheduler_check(base_state, "P0", base_policy)

        assert decision.allowed is False
        assert decision.reason == "scheduler_paced_wait"
        assert decision.wait_seconds == 120.0

    def test_p1_burst_allowed(self, base_state, base_policy):
        """P1 can use burst when over pace."""
        base_state.calls_today = 100
        base_state.burst_used_p1 = 0

        with patch("moltagent.scheduler.compute_earned_calls", return_value=50.0):
            decision = scheduler_check(base_state, "P1", base_policy)

        assert decision.allowed is True
        assert decision.reason == "scheduler_burst_p1"
        assert decision.used_burst is True
        assert decision.burst_type == "p1"

    def test_p2_no_burst(self, base_state, base_policy):
        """P2 cannot use burst, must wait."""
        base_state.calls_today = 100

        with patch("moltagent.scheduler.compute_earned_calls", return_value=50.0):
            with patch("moltagent.scheduler.compute_wait_seconds", return_value=300.0):
                decision = scheduler_check(base_state, "P2", base_policy)

        assert decision.allowed is False
        assert decision.reason == "scheduler_paced_wait"
        assert decision.wait_seconds == 300.0


class TestUpdateBurstCounters:
    """Tests for burst counter updates."""

    def test_no_burst_used(self, base_state):
        """No update when burst not used."""
        decision = SchedulerDecision(allowed=True, reason="scheduler_within_pace")

        update_burst_counters(base_state, decision)

        assert base_state.burst_used_p0 == 0
        assert base_state.burst_used_p1 == 0

    def test_p0_burst_incremented(self, base_state):
        """P0 burst counter incremented."""
        decision = SchedulerDecision(
            allowed=True,
            reason="scheduler_burst_p0",
            used_burst=True,
            burst_type="p0",
        )

        update_burst_counters(base_state, decision)

        assert base_state.burst_used_p0 == 1
        assert base_state.burst_used_p1 == 0

    def test_p1_burst_incremented(self, base_state):
        """P1 burst counter incremented."""
        decision = SchedulerDecision(
            allowed=True,
            reason="scheduler_burst_p1",
            used_burst=True,
            burst_type="p1",
        )

        update_burst_counters(base_state, decision)

        assert base_state.burst_used_p0 == 0
        assert base_state.burst_used_p1 == 1
