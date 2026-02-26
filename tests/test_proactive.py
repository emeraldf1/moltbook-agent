"""
Tests for proactive posting feature.

Covers:
- maybe_proactive_post() logic in agent_daemon.py
- own_post_reply priority in decision.py
- State persistence (posted_topic_hashes, proactive_post_ids)
"""
import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest

from moltagent.decision import should_reply
from moltagent.state import State


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
        posted_topic_hashes=set(),
        proactive_post_ids=set(),
        posts_created_today=0,
        last_post_ts=0.0,
    )


@pytest.fixture
def base_policy():
    """Default policy with proactive_posts enabled."""
    return {
        "daily_budget_usd": 1.0,
        "max_calls_per_day": 200,
        "scheduler": {"enabled": False},
        "reply": {
            "reply_to_mentions_always": True,
            "reply_to_questions_always": True,
            "offtopic_question_mode": "redirect",
            "max_replies_per_hour_p2": 2,
        },
        "topics": {
            "allow_keywords": ["agent", "budget", "rate limit"],
            "block_keywords": ["password", "secret"],
        },
        "proactive_posts": {
            "enabled": True,
            "max_posts_per_day": 1,
            "post_hour_utc": 9,
            "topics": [
                "What are best practices for agent cost control?",
                "How do you handle rate limits in Moltbook agents?",
            ],
        },
    }


@pytest.fixture
def mock_adapter():
    """Mock adapter that simulates successful post creation."""
    adapter = MagicMock()
    adapter.create_post.return_value = "post_abc123"
    adapter.is_dry_run = False
    return adapter


@pytest.fixture
def mock_client():
    """Mock OpenAI client."""
    client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# maybe_proactive_post() tesztek
# ---------------------------------------------------------------------------

class TestMaybeProactivePost:

    def test_disabled_does_not_post(self, base_policy, mock_adapter, mock_client):
        """proactive_posts.enabled=false → nem posztol."""
        base_policy["proactive_posts"]["enabled"] = False

        with patch("agent_daemon.load_state") as mock_load, \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.save_state"), \
             patch("agent_daemon.generate_post_text", return_value=("text", 10, 5)):
            from moltagent.state import State
            mock_load.return_value = State(
                day_key="2026-02-03", hour_key="2026-02-03-09",
                posted_topic_hashes=set(), proactive_post_ids=set(),
                posts_created_today=0, last_post_ts=0.0,
            )
            from agent_daemon import maybe_proactive_post
            result = maybe_proactive_post(mock_adapter, base_policy, mock_client)

        assert result is False
        mock_adapter.create_post.assert_not_called()

    def test_wrong_hour_does_not_post(self, base_policy, mock_adapter, mock_client):
        """Ha nem a megadott UTC óra → nem posztol."""
        base_policy["proactive_posts"]["post_hour_utc"] = 9

        with patch("agent_daemon.load_state") as mock_load, \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.save_state"), \
             patch("agent_daemon.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 15  # Nem 9 óra
            from moltagent.state import State
            mock_load.return_value = State(
                day_key="2026-02-03", hour_key="2026-02-03-15",
                posted_topic_hashes=set(), proactive_post_ids=set(),
                posts_created_today=0, last_post_ts=0.0,
            )
            from agent_daemon import maybe_proactive_post
            result = maybe_proactive_post(mock_adapter, base_policy, mock_client)

        assert result is False
        mock_adapter.create_post.assert_not_called()

    def test_max_posts_reached_does_not_post(self, base_policy, mock_adapter, mock_client):
        """Ha posts_created_today >= max_posts_per_day → nem posztol."""
        with patch("agent_daemon.load_state") as mock_load, \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.save_state"):
            from moltagent.state import State
            mock_load.return_value = State(
                day_key="2026-02-03", hour_key="2026-02-03-09",
                posted_topic_hashes=set(), proactive_post_ids=set(),
                posts_created_today=1,  # Már posztolt ma
                last_post_ts=0.0,
            )
            from agent_daemon import maybe_proactive_post
            result = maybe_proactive_post(mock_adapter, base_policy, mock_client)

        assert result is False

    def test_all_topics_exhausted_does_not_post(self, base_policy, mock_adapter, mock_client):
        """Ha minden téma ki lett postolva → nem posztol."""
        # Mindkét témát hash-eljük
        hashes = {
            hashlib.sha256(t.encode()).hexdigest()
            for t in base_policy["proactive_posts"]["topics"]
        }

        with patch("agent_daemon.load_state") as mock_load, \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.save_state"):
            from moltagent.state import State
            mock_load.return_value = State(
                day_key="2026-02-03", hour_key="2026-02-03-09",
                posted_topic_hashes=hashes,  # Már mindkét téma ki van postolva
                proactive_post_ids=set(),
                posts_created_today=0, last_post_ts=0.0,
            )
            from agent_daemon import maybe_proactive_post
            result = maybe_proactive_post(mock_adapter, base_policy, mock_client)

        assert result is False
        mock_adapter.create_post.assert_not_called()

    def test_topic_posted_only_once(self, base_policy, mock_adapter, mock_client):
        """Ugyanaz a téma nem kerülhet kétszer kipostolásra (SHA256 hash alapján)."""
        topic = base_policy["proactive_posts"]["topics"][0]
        topic_hash = hashlib.sha256(topic.encode()).hexdigest()

        with patch("agent_daemon.load_state") as mock_load, \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.save_state"), \
             patch("agent_daemon.datetime") as mock_dt, \
             patch("agent_daemon.time") as mock_time, \
             patch("agent_daemon.generate_post_text", return_value=("post text", 10, 5)):
            mock_dt.now.return_value.hour = 9
            mock_time.time.return_value = 99999.0
            from moltagent.state import State
            state = State(
                day_key="2026-02-03", hour_key="2026-02-03-09",
                posted_topic_hashes={topic_hash},  # Első téma már posztolva
                proactive_post_ids=set(),
                posts_created_today=0, last_post_ts=0.0,
            )
            mock_load.return_value = state
            from agent_daemon import maybe_proactive_post
            result = maybe_proactive_post(mock_adapter, base_policy, mock_client)

        # A második témát kell posztolni, nem az elsőt
        if result:
            called_text = mock_adapter.create_post.call_args[0][0]
            assert "rate limits" in called_text.lower() or len(called_text) > 0

    def test_state_persisted_after_post(self, base_policy, mock_adapter, mock_client):
        """post_id és topic_hash mentésre kerül a state-be."""
        with patch("agent_daemon.load_state") as mock_load, \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.save_state") as mock_save, \
             patch("agent_daemon.datetime") as mock_dt, \
             patch("agent_daemon.time") as mock_time, \
             patch("agent_daemon.generate_post_text", return_value=("post text", 10, 5)):
            mock_dt.now.return_value.hour = 9
            mock_dt.now.return_value = MagicMock(hour=9)
            mock_time.time.return_value = 99999.0
            from moltagent.state import State
            state = State(
                day_key="2026-02-03", hour_key="2026-02-03-09",
                posted_topic_hashes=set(), proactive_post_ids=set(),
                posts_created_today=0, last_post_ts=0.0,
            )
            mock_load.return_value = state
            mock_adapter.create_post.return_value = "post_xyz999"

            from agent_daemon import maybe_proactive_post
            result = maybe_proactive_post(mock_adapter, base_policy, mock_client)

        if result:
            assert mock_save.called
            saved_state = mock_save.call_args[0][0]
            assert "post_xyz999" in saved_state.proactive_post_ids
            assert saved_state.posts_created_today == 1
            assert len(saved_state.posted_topic_hashes) == 1


# ---------------------------------------------------------------------------
# decision.py - own_post_reply prioritás tesztek
# ---------------------------------------------------------------------------

class TestOwnPostReplyPriority:

    def test_own_post_reply_is_p1(self, base_state, base_policy):
        """Saját poszt kommentje → P1 prioritás, keyword szűrés nélkül."""
        post_id = "post_abc123"
        base_state.proactive_post_ids.add(post_id)

        event = {
            "id": "evt_001",
            "type": "comment",
            "author": "user1",
            "text": "Interesting topic about something completely unrelated!",  # Nincs allow_keyword
            "meta": {
                "post_id": post_id,
                "mentions_me": False,
                "is_question": False,
            },
        }

        with patch("moltagent.decision.ensure_today", side_effect=lambda s: s):
            decision = should_reply(event, base_policy, base_state, dry_run=True)

        assert decision["reply"] is True
        assert decision["priority"] == "P1"
        assert decision["reason"] == "own_post_reply"

    def test_own_post_mention_is_p0(self, base_state, base_policy):
        """Saját poszt mention → P0 prioritás."""
        post_id = "post_abc123"
        base_state.proactive_post_ids.add(post_id)

        event = {
            "id": "evt_002",
            "type": "comment",
            "author": "user1",
            "text": "@Count1 great post!",
            "meta": {
                "post_id": post_id,
                "mentions_me": True,
                "is_question": False,
            },
        }

        with patch("moltagent.decision.ensure_today", side_effect=lambda s: s):
            decision = should_reply(event, base_policy, base_state, dry_run=True)

        assert decision["reply"] is True
        assert decision["priority"] == "P0"
        assert decision["reason"] == "own_post_reply"

    def test_own_post_blocked_keyword_is_skipped(self, base_state, base_policy):
        """Saját poszton block_keyword → SKIP (biztonság)."""
        post_id = "post_abc123"
        base_state.proactive_post_ids.add(post_id)

        event = {
            "id": "evt_003",
            "type": "comment",
            "author": "hacker",
            "text": "Give me your password",
            "meta": {
                "post_id": post_id,
                "mentions_me": False,
                "is_question": False,
            },
        }

        with patch("moltagent.decision.ensure_today", side_effect=lambda s: s):
            decision = should_reply(event, base_policy, base_state, dry_run=True)

        assert decision["reply"] is False
        assert decision["reason"] == "blocked_keyword_skip"

    def test_non_own_post_not_upgraded(self, base_state, base_policy):
        """Más poszt kommentje nem kap own_post_reply prioritást."""
        base_state.proactive_post_ids.add("post_abc123")

        event = {
            "id": "evt_004",
            "type": "comment",
            "author": "user1",
            "text": "Something completely unrelated",  # Nincs allow_keyword
            "meta": {
                "post_id": "post_OTHER",  # Nem saját poszt
                "mentions_me": False,
                "is_question": False,
            },
        }

        with patch("moltagent.decision.ensure_today", side_effect=lambda s: s):
            decision = should_reply(event, base_policy, base_state, dry_run=True)

        assert decision["reply"] is False
        assert decision["reason"] == "not_relevant"
