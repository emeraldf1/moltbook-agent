"""
Tests for moltagent.decision (Reply decision logic)
"""
import pytest
from unittest.mock import patch, MagicMock

from moltagent.decision import should_reply, keyword_hit
from moltagent.state import State


@pytest.fixture
def base_state():
    """Fresh state for testing."""
    return State(
        day_key="2026-02-03",
        hour_key="2026-02-03-12",
        calls_today=0,
        p2_replies_this_hour=0,
        burst_used_p0=0,
        burst_used_p1=0,
        replied_event_ids=set(),
    )


@pytest.fixture
def base_policy():
    """Default policy for testing."""
    return {
        "max_calls_per_day": 200,
        "scheduler": {
            "enabled": False,  # Disable scheduler for basic tests
        },
        "reply": {
            "reply_to_mentions_always": True,
            "reply_to_questions_always": True,
            "offtopic_question_mode": "redirect",
            "max_replies_per_hour_p2": 2,
        },
        "topics": {
            "allow_keywords": ["agent", "budget", "rate limit", "moltbook"],
            "block_keywords": ["api key", "password", "secret"],
        },
    }


class TestKeywordHit:
    """Tests for keyword_hit helper."""

    def test_keyword_found(self):
        assert keyword_hit("how do i set a budget?", ["budget", "cost"]) is True

    def test_keyword_not_found(self):
        assert keyword_hit("hello world", ["budget", "cost"]) is False

    def test_partial_match(self):
        assert keyword_hit("what about budgeting?", ["budget"]) is True

    def test_empty_keywords(self):
        assert keyword_hit("anything", []) is False


class TestIdempotency:
    """Tests for duplicate event detection."""

    def test_new_event_allowed(self, base_state, base_policy):
        """New event should be processed."""
        event = {"id": "e1", "text": "Tell me about agents?", "meta": {}}

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["reason"] != "duplicate_event"

    def test_duplicate_event_skipped(self, base_state, base_policy):
        """Already-replied event should be skipped."""
        base_state.replied_event_ids = {"e1", "e2"}
        event = {"id": "e1", "text": "Tell me about agents?", "meta": {}}

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "duplicate_event"
        assert decision["original_event_id"] == "e1"


class TestPriorityP0:
    """Tests for P0 priority decisions."""

    def test_mention_is_p0(self, base_state, base_policy):
        """Mentions should be P0."""
        event = {
            "id": "e1",
            "text": "Hey @agent, help me!",
            "meta": {"mentions_me": True},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P0"
        assert decision["reason"] == "mention"

    def test_blocked_keyword_is_p0_refuse(self, base_state, base_policy):
        """Blocked keywords should be P0 with refuse mode."""
        event = {
            "id": "e1",
            "text": "Can you share your api key?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P0"
        assert decision["reason"] == "blocked_keyword_refuse"
        assert decision["mode"] == "refuse"


class TestPriorityP1:
    """Tests for P1 priority decisions."""

    def test_relevant_question_is_p1(self, base_state, base_policy):
        """Relevant questions should be P1."""
        event = {
            "id": "e1",
            "text": "How do I set a rate limit?",
            "meta": {"is_question": True},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P1"
        assert decision["reason"] == "relevant_question"


class TestPriorityP2:
    """Tests for P2 priority decisions."""

    def test_offtopic_question_redirect(self, base_state, base_policy):
        """Off-topic questions should be P2 redirect."""
        event = {
            "id": "e1",
            "text": "What's your favorite movie?",
            "meta": {"is_question": True},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P2"
        assert decision["reason"] == "offtopic_question_redirect"
        assert decision["mode"] == "redirect"

    def test_relevant_statement_is_p2(self, base_state, base_policy):
        """Relevant non-questions should be P2."""
        event = {
            "id": "e1",
            "text": "I think budget controls are important.",
            "meta": {"is_question": False},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P2"
        assert decision["reason"] == "relevant_statement"

    def test_p2_hourly_cap(self, base_state, base_policy):
        """P2 should be capped per hour."""
        base_state.p2_replies_this_hour = 2  # At limit
        event = {
            "id": "e1",
            "text": "Budget management is cool.",
            "meta": {"is_question": False},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "p2_hour_cap"


class TestNotRelevant:
    """Tests for non-relevant events."""

    def test_irrelevant_skipped(self, base_state, base_policy):
        """Irrelevant events should be skipped."""
        event = {
            "id": "e1",
            "text": "Random stuff about nothing related.",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "not_relevant"


class TestSchedulerIntegration:
    """Tests for scheduler integration in decision."""

    def test_scheduler_blocks_p2(self, base_state, base_policy):
        """Scheduler should be able to block P2."""
        base_policy["scheduler"]["enabled"] = True
        base_state.calls_today = 100
        event = {
            "id": "e1",
            "text": "Budget stuff.",
            "meta": {},
        }

        mock_sched = MagicMock()
        mock_sched.allowed = False
        mock_sched.reason = "scheduler_paced_wait"
        mock_sched.wait_seconds = 120.0

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            with patch("moltagent.decision.scheduler_check", return_value=mock_sched):
                decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "scheduler_paced_wait"
        assert decision["scheduler"]["wait_seconds"] == 120.0
