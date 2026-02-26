"""
Tests for challenge event handling.

Covers:
- _post_to_event() preserves raw 'type' field (challenge vs post)
- run_poll_cycle() auto-responds to challenge events bypassing decision pipeline
- No double-reply to same challenge (dedup via state.has_replied)
- Normal (non-challenge) posts are unaffected
- Dry-run mode: logs but does not call send_reply
"""
from unittest.mock import MagicMock, patch, call
import pytest

from moltagent.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**kwargs):
    defaults = dict(
        day_key="2026-02-27",
        hour_key="2026-02-27-20",
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
    defaults.update(kwargs)
    return State(**defaults)


def _challenge_event(post_id="chal-001"):
    return {
        "id": f"challenge_{post_id}",
        "type": "challenge",
        "author": "automod",
        "text": "Verify your agent is operational.",
        "ts": "2026-02-27T20:00:00Z",
        "meta": {
            "is_question": False,
            "mentions_me": False,
            "post_id": post_id,
            "submolt": "general",
            "score": 0,
        },
    }


def _post_event(post_id="post-001"):
    return {
        "id": f"post_{post_id}",
        "type": "post",
        "author": "someone",
        "text": "How do I set up an agent?",
        "ts": "2026-02-27T20:00:00Z",
        "meta": {
            "is_question": True,
            "mentions_me": False,
            "post_id": post_id,
            "submolt": "general",
            "score": 0,
        },
    }


# ---------------------------------------------------------------------------
# 1. _post_to_event() preserves raw type field
# ---------------------------------------------------------------------------

class TestRawTypePreserved:
    def test_challenge_type_preserved(self):
        """Raw 'challenge' type from API must survive _post_to_event()."""
        from adapters.moltbook import MoltbookAdapter
        adapter = MoltbookAdapter.__new__(MoltbookAdapter)
        adapter._agent_name_config = "TestBot"
        adapter._dry_run = True

        raw_post = {
            "id": "abc-123",
            "type": "challenge",
            "title": "Verify agent",
            "content": "Please confirm you are active.",
            "author": {"name": "automod"},
            "created_at": "2026-02-27T20:00:00Z",
            "submolt": {"name": "general"},
            "score": 0,
        }
        event = adapter._post_to_event(raw_post)

        assert event is not None
        assert event["type"] == "challenge"
        assert event["id"].startswith("challenge_")

    def test_post_type_preserved(self):
        """Regular posts without type field default to 'post'."""
        from adapters.moltbook import MoltbookAdapter
        adapter = MoltbookAdapter.__new__(MoltbookAdapter)
        adapter._agent_name_config = "TestBot"
        adapter._dry_run = True

        raw_post = {
            "id": "xyz-456",
            # no "type" field
            "title": "Normal post",
            "content": "Hello world",
            "author": {"name": "user1"},
            "created_at": "2026-02-27T20:00:00Z",
            "submolt": {"name": "general"},
            "score": 0,
        }
        event = adapter._post_to_event(raw_post)

        assert event is not None
        assert event["type"] == "post"
        assert event["id"].startswith("post_")


# ---------------------------------------------------------------------------
# 2. run_poll_cycle() auto-responds to challenges
# ---------------------------------------------------------------------------

class TestChallengeAutoResponse:
    def test_challenge_auto_responded(self):
        """Challenge event triggers respond_to_challenge() immediately."""
        mock_adapter = MagicMock()
        mock_adapter.fetch_events.return_value = [_challenge_event("chal-001")]
        mock_adapter.respond_to_challenge.return_value = True
        mock_client = MagicMock()

        state = _make_state()

        policy = {"adapter": "moltbook", "daily_budget_usd": 1.0,
                  "max_calls_per_day": 200, "min_seconds_between_calls": 0}

        with patch("agent_daemon.load_state", return_value=state), \
             patch("agent_daemon.save_state"), \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.append_jsonl"), \
             patch("agent_daemon.process_event") as mock_process:

            from agent_daemon import run_poll_cycle
            stats = run_poll_cycle(mock_adapter, policy, mock_client)

        mock_adapter.respond_to_challenge.assert_called_once_with("chal-001")
        mock_process.assert_not_called()  # challenge bypasses decision pipeline
        assert stats["replied"] == 1

    def test_challenge_not_double_replied(self):
        """Already-replied challenge is not answered again."""
        mock_adapter = MagicMock()
        mock_adapter.fetch_events.return_value = [_challenge_event("chal-dup")]
        mock_adapter.respond_to_challenge.return_value = True
        mock_client = MagicMock()

        # State already has this challenge marked as replied
        state = _make_state(replied_event_ids={"challenge_chal-dup"})

        policy = {"adapter": "moltbook", "daily_budget_usd": 1.0,
                  "max_calls_per_day": 200, "min_seconds_between_calls": 0}

        with patch("agent_daemon.load_state", return_value=state), \
             patch("agent_daemon.save_state"), \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.append_jsonl"), \
             patch("agent_daemon.process_event"):

            from agent_daemon import run_poll_cycle
            run_poll_cycle(mock_adapter, policy, mock_client)

        mock_adapter.respond_to_challenge.assert_not_called()

    def test_non_challenge_not_affected(self):
        """Normal post events go through decision pipeline, not challenge handler."""
        mock_adapter = MagicMock()
        mock_adapter.fetch_events.return_value = [_post_event("post-normal")]
        mock_client = MagicMock()

        state = _make_state()
        policy = {"adapter": "moltbook", "daily_budget_usd": 1.0,
                  "max_calls_per_day": 200, "min_seconds_between_calls": 0}

        with patch("agent_daemon.load_state", return_value=state), \
             patch("agent_daemon.save_state"), \
             patch("agent_daemon.ensure_today", side_effect=lambda s: s), \
             patch("agent_daemon.append_jsonl"), \
             patch("agent_daemon.process_event", return_value={"reply": False, "reason": "skip"}) as mock_process:

            from agent_daemon import run_poll_cycle
            run_poll_cycle(mock_adapter, policy, mock_client)

        mock_adapter.respond_to_challenge.assert_not_called()
        mock_process.assert_called_once()


# ---------------------------------------------------------------------------
# 3. MoltbookAdapter.respond_to_challenge() dry-run
# ---------------------------------------------------------------------------

class TestRespondToChallengeDryRun:
    def test_dry_run_does_not_call_send_reply(self):
        """In dry-run mode, respond_to_challenge() logs but does not call send_reply."""
        from adapters.moltbook import MoltbookAdapter
        adapter = MoltbookAdapter.__new__(MoltbookAdapter)
        adapter._dry_run = True
        adapter._log_dir = "/tmp"

        with patch.object(adapter, "send_reply") as mock_send, \
             patch("builtins.open", MagicMock()):
            result = adapter.respond_to_challenge("test-post-id")

        assert result is True
        mock_send.assert_not_called()

    def test_live_mode_calls_send_reply(self):
        """In live mode, respond_to_challenge() calls send_reply."""
        from adapters.moltbook import MoltbookAdapter
        adapter = MoltbookAdapter.__new__(MoltbookAdapter)
        adapter._dry_run = False
        adapter._log_dir = "/tmp"

        with patch.object(adapter, "send_reply", return_value=True) as mock_send, \
             patch("builtins.open", MagicMock()):
            result = adapter.respond_to_challenge("test-post-id")

        assert result is True
        mock_send.assert_called_once_with(
            event_id="challenge_test-post-id",
            text="Challenge acknowledged. Agent is active and operational.",
            post_id="test-post-id",
        )
