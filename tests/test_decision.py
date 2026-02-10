"""
Tests for moltagent.decision (Reply decision logic)
"""
import pytest
from unittest.mock import patch, MagicMock

from moltagent.decision import should_reply, keyword_hit, _check_budget, _check_soft_cap
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


class TestBudgetHardCap:
    """Tests for budget hard cap (SPEC §7)."""

    def test_budget_exhausted_skip(self, base_state, base_policy):
        """Budget elérve → SKIP budget_exhausted (AC-1)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 1.0  # Exactly at limit
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "budget_exhausted"
        assert "budget" in decision
        assert decision["budget"]["spent_usd"] == 1.0
        assert decision["budget"]["daily_budget_usd"] == 1.0

    def test_budget_over_limit_skip(self, base_state, base_policy):
        """Budget túllépve → SKIP budget_exhausted"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 1.5  # Over limit
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "budget_exhausted"

    def test_daily_calls_cap_skip(self, base_state, base_policy):
        """Max hívásszám elérve → SKIP daily_calls_cap (AC-2)"""
        base_policy["max_calls_per_day"] = 100
        base_state.calls_today = 100  # Exactly at limit
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "daily_calls_cap"
        assert "budget" in decision
        assert decision["budget"]["calls_today"] == 100
        assert decision["budget"]["max_calls_per_day"] == 100

    def test_budget_info_in_decision(self, base_state, base_policy):
        """Budget info a döntésben (AC-3)"""
        base_policy["daily_budget_usd"] = 0.5
        base_policy["max_calls_per_day"] = 50
        base_state.spent_usd = 0.6
        base_state.calls_today = 10
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert "budget" in decision
        budget = decision["budget"]
        assert budget["spent_usd"] == 0.6
        assert budget["daily_budget_usd"] == 0.5
        assert budget["calls_today"] == 10
        assert budget["max_calls_per_day"] == 50

    def test_budget_priority_preserved_p0(self, base_state, base_policy):
        """P0 esemény budget SKIP-nél is P0 marad (AC-4)"""
        base_policy["daily_budget_usd"] = 0.01
        base_state.spent_usd = 1.0
        event = {
            "id": "e1",
            "text": "@agent help!",
            "meta": {"mentions_me": True},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "budget_exhausted"
        assert decision["priority"] == "P0"  # Priority preserved!

    def test_budget_priority_preserved_p1(self, base_state, base_policy):
        """P1 esemény budget SKIP-nél is P1 marad"""
        base_policy["daily_budget_usd"] = 0.01
        base_state.spent_usd = 1.0
        event = {
            "id": "e1",
            "text": "How do I set a rate limit?",
            "meta": {"is_question": True},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "budget_exhausted"
        assert decision["priority"] == "P1"  # Priority preserved!

    def test_dedup_before_budget(self, base_state, base_policy):
        """Duplicate event előbb fut mint budget check (AC-5)"""
        base_policy["daily_budget_usd"] = 0.01
        base_state.spent_usd = 1.0  # Budget exhausted
        base_state.replied_event_ids = {"e1"}  # Already replied
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        # Dedup should win over budget
        assert decision["reply"] is False
        assert decision["reason"] == "duplicate_event"

    def test_budget_before_scheduler(self, base_state, base_policy):
        """Budget check előbb fut mint scheduler (AC-6)"""
        base_policy["daily_budget_usd"] = 0.01
        base_policy["scheduler"]["enabled"] = True
        base_state.spent_usd = 1.0  # Budget exhausted
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        # Scheduler should not even be called if budget is exhausted
        with patch("moltagent.decision.ensure_today", return_value=base_state):
            with patch("moltagent.decision.scheduler_check") as mock_sched:
                decision = should_reply(event, base_policy, base_state)
                # Scheduler should NOT be called
                mock_sched.assert_not_called()

        assert decision["reply"] is False
        assert decision["reason"] == "budget_exhausted"

    def test_budget_ok_allows_reply(self, base_state, base_policy):
        """Budget OK → valid reply allowed"""
        base_policy["daily_budget_usd"] = 10.0
        base_policy["max_calls_per_day"] = 200
        base_state.spent_usd = 0.5
        base_state.calls_today = 10
        event = {
            "id": "e1",
            "text": "Tell me about agents?",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["reason"] == "relevant_question"

    def test_check_budget_helper_exhausted(self, base_state, base_policy):
        """_check_budget helper: budget exhausted"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 1.5

        result = _check_budget(base_state, base_policy, "P1")

        assert result is not None
        assert result["reason"] == "budget_exhausted"
        assert result["priority"] == "P1"

    def test_check_budget_helper_calls_cap(self, base_state, base_policy):
        """_check_budget helper: calls cap reached"""
        base_policy["max_calls_per_day"] = 50
        base_state.calls_today = 50

        result = _check_budget(base_state, base_policy, "P2")

        assert result is not None
        assert result["reason"] == "daily_calls_cap"
        assert result["priority"] == "P2"

    def test_check_budget_helper_ok(self, base_state, base_policy):
        """_check_budget helper: budget OK returns None"""
        base_policy["daily_budget_usd"] = 10.0
        base_policy["max_calls_per_day"] = 200
        base_state.spent_usd = 1.0
        base_state.calls_today = 50

        result = _check_budget(base_state, base_policy, "P0")

        assert result is None


class TestBudgetSoftCap:
    """Tests for budget soft cap (SPEC §7b)."""

    def test_soft_cap_blocks_p2_at_80_percent(self, base_state, base_policy):
        """P2 SKIP 80% felett (AC-1)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.80  # Exactly at 80%
        event = {
            "id": "e1",
            "text": "Budget stuff.",  # P2 (relevant statement)
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "soft_cap_p2_blocked"
        assert decision["priority"] == "P2"
        assert decision["budget"]["soft_cap_percentage"] == 0.80

    def test_soft_cap_allows_p0_at_80_percent(self, base_state, base_policy):
        """P0 átmegy 80% felett (AC-2)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.80  # At 80%
        event = {
            "id": "e1",
            "text": "@agent help with budget!",
            "meta": {"mentions_me": True},
        }

        # Scheduler mock (engedélyez)
        mock_sched = MagicMock()
        mock_sched.allowed = True
        mock_sched.reason = "scheduler_within_pace"
        mock_sched.used_burst = False
        mock_sched.burst_type = None

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            with patch("moltagent.decision.scheduler_check", return_value=mock_sched):
                decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P0"

    def test_soft_cap_allows_p1_at_80_percent(self, base_state, base_policy):
        """P1 átmegy 80% felett (AC-3)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.85  # Over 80%
        event = {
            "id": "e1",
            "text": "How do I set a budget?",  # P1 (relevant question)
            "meta": {"is_question": True},
        }

        # Scheduler mock
        mock_sched = MagicMock()
        mock_sched.allowed = True
        mock_sched.reason = "scheduler_within_pace"
        mock_sched.used_burst = False
        mock_sched.burst_type = None

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            with patch("moltagent.decision.scheduler_check", return_value=mock_sched):
                decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P1"

    def test_soft_cap_allows_p2_below_80_percent(self, base_state, base_policy):
        """P2 átmegy 80% alatt (AC-4)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.79  # Just below 80%
        event = {
            "id": "e1",
            "text": "Budget stuff.",  # P2 (relevant statement)
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is True
        assert decision["priority"] == "P2"

    def test_soft_cap_budget_info_in_decision(self, base_state, base_policy):
        """Budget info tartalmazza: soft_cap_threshold, soft_cap_percentage (AC-5)"""
        base_policy["daily_budget_usd"] = 2.0
        base_state.spent_usd = 1.60  # 80% of 2.0
        event = {
            "id": "e1",
            "text": "Budget stuff.",
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        assert decision["reason"] == "soft_cap_p2_blocked"
        budget = decision["budget"]
        assert budget["spent_usd"] == 1.60
        assert budget["daily_budget_usd"] == 2.0
        assert budget["soft_cap_threshold"] == 1.60
        assert budget["soft_cap_percentage"] == 0.80

    def test_hard_cap_before_soft_cap(self, base_state, base_policy):
        """Hard cap (100%) előbb fut → budget_exhausted reason (AC-6)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 1.0  # 100% - hard cap
        event = {
            "id": "e1",
            "text": "Budget stuff.",  # P2
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["reply"] is False
        # Hard cap reason, NOT soft cap
        assert decision["reason"] == "budget_exhausted"

    def test_soft_cap_priority_preserved(self, base_state, base_policy):
        """Priority megőrződik a SKIP döntésben (AC-7)"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.90  # Over 80%
        event = {
            "id": "e1",
            "text": "Budget stuff.",  # P2
            "meta": {},
        }

        with patch("moltagent.decision.ensure_today", return_value=base_state):
            decision = should_reply(event, base_policy, base_state)

        assert decision["priority"] == "P2"  # Priority preserved

    def test_check_soft_cap_helper_blocks_p2(self, base_state, base_policy):
        """_check_soft_cap helper: blocks P2 at 80%"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.80

        result = _check_soft_cap(base_state, base_policy, "P2")

        assert result is not None
        assert result["reason"] == "soft_cap_p2_blocked"
        assert result["priority"] == "P2"

    def test_check_soft_cap_helper_allows_p0(self, base_state, base_policy):
        """_check_soft_cap helper: allows P0 at 80%"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.90

        result = _check_soft_cap(base_state, base_policy, "P0")

        assert result is None  # P0 always passes

    def test_check_soft_cap_helper_allows_p1(self, base_state, base_policy):
        """_check_soft_cap helper: allows P1 at 80%"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.95

        result = _check_soft_cap(base_state, base_policy, "P1")

        assert result is None  # P1 always passes

    def test_check_soft_cap_helper_ok_below_80(self, base_state, base_policy):
        """_check_soft_cap helper: allows P2 below 80%"""
        base_policy["daily_budget_usd"] = 1.0
        base_state.spent_usd = 0.50

        result = _check_soft_cap(base_state, base_policy, "P2")

        assert result is None
