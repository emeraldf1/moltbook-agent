"""
Tests for adapter modules.
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from adapters import get_adapter, BaseAdapter
from adapters.mock import MockAdapter
from adapters.moltbook import MoltbookAdapter


# =============================================================================
# Test: Adapter Factory
# =============================================================================


class TestAdapterFactory:
    """Tests for get_adapter factory function."""

    def test_get_mock_adapter(self):
        """get_adapter("mock") returns MockAdapter."""
        adapter = get_adapter("mock")
        assert isinstance(adapter, MockAdapter)

    def test_get_moltbook_adapter_with_api_key(self):
        """get_adapter("moltbook") returns MoltbookAdapter when API key is set."""
        with patch.dict(os.environ, {"MOLTBOOK_API_KEY": "test_key"}):
            adapter = get_adapter("moltbook")
            assert isinstance(adapter, MoltbookAdapter)

    def test_get_unknown_adapter_raises(self):
        """get_adapter with unknown type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown adapter type"):
            get_adapter("unknown")


# =============================================================================
# Test: Mock Adapter
# =============================================================================


class TestMockAdapter:
    """Tests for MockAdapter."""

    def test_fetch_events_empty_file(self):
        """fetch_events returns empty list when file doesn't exist."""
        adapter = MockAdapter(events_file="nonexistent.jsonl")
        events = adapter.fetch_events()
        assert events == []

    def test_fetch_events_reads_jsonl(self):
        """fetch_events reads events from JSONL file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"id": "e1", "text": "Hello?", "author": "user1"}\n')
            f.write('{"id": "e2", "text": "World", "author": "user2"}\n')
            f.flush()

            try:
                adapter = MockAdapter(events_file=f.name)
                events = adapter.fetch_events()

                assert len(events) == 2
                assert events[0]["id"] == "e1"
                assert events[1]["id"] == "e2"
            finally:
                os.unlink(f.name)

    def test_fetch_events_normalizes_format(self):
        """fetch_events adds default fields."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"id": "e1", "text": "What is this?"}\n')
            f.flush()

            try:
                adapter = MockAdapter(events_file=f.name)
                events = adapter.fetch_events()

                assert len(events) == 1
                event = events[0]
                assert "type" in event
                assert "author" in event
                assert "ts" in event
                assert "meta" in event
                assert event["meta"]["is_question"] is True  # ends with ?
            finally:
                os.unlink(f.name)

    def test_fetch_events_detects_mention(self):
        """fetch_events detects @mention in text."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            f.write('{"id": "e1", "text": "Hey @TestAgent, help!"}\n')
            f.flush()

            try:
                adapter = MockAdapter(events_file=f.name, agent_name="TestAgent")
                events = adapter.fetch_events()

                assert events[0]["meta"]["mentions_me"] is True
            finally:
                os.unlink(f.name)

    def test_fetch_events_respects_limit(self):
        """fetch_events respects limit parameter."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for i in range(10):
                f.write(f'{{"id": "e{i}", "text": "Event {i}"}}\n')
            f.flush()

            try:
                adapter = MockAdapter(events_file=f.name)
                events = adapter.fetch_events(limit=3)

                assert len(events) == 3
            finally:
                os.unlink(f.name)

    def test_send_reply_logs_to_file(self):
        """send_reply writes to mock_replies.jsonl."""
        with tempfile.TemporaryDirectory() as log_dir:
            adapter = MockAdapter(log_dir=log_dir)
            result = adapter.send_reply("e1", "Hello!", post_id="p1")

            assert result is True

            log_file = os.path.join(log_dir, "mock_replies.jsonl")
            assert os.path.exists(log_file)

            with open(log_file) as f:
                line = f.readline()
                log = json.loads(line)

            assert log["event_id"] == "e1"
            assert log["text"] == "Hello!"
            assert log["post_id"] == "p1"
            assert log["dry_run"] is True

    def test_agent_name_property(self):
        """agent_name property returns configured name."""
        adapter = MockAdapter(agent_name="MyAgent")
        assert adapter.agent_name == "MyAgent"

    def test_is_dry_run_always_true(self):
        """Mock adapter is always dry-run."""
        adapter = MockAdapter()
        assert adapter.is_dry_run is True

    def test_get_agent_info(self):
        """get_agent_info returns mock info."""
        adapter = MockAdapter(agent_name="TestAgent")
        info = adapter.get_agent_info()

        assert info["name"] == "TestAgent"
        assert info["adapter"] == "mock"
        assert info["is_claimed"] is True


# =============================================================================
# Test: Moltbook Adapter
# =============================================================================


class TestMoltbookAdapter:
    """Tests for MoltbookAdapter."""

    def test_init_requires_api_key(self):
        """MoltbookAdapter raises if no API key."""
        # Clear env var if set
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="MOLTBOOK_API_KEY not set"):
                MoltbookAdapter()

    def test_init_with_api_key(self):
        """MoltbookAdapter initializes with API key."""
        adapter = MoltbookAdapter(api_key="test_key", agent_name="TestAgent")
        assert adapter.agent_name == "TestAgent"

    def test_dry_run_default_true(self):
        """Dry-run defaults to True for safety."""
        adapter = MoltbookAdapter(api_key="test_key")
        assert adapter.is_dry_run is True

    def test_dry_run_from_env(self):
        """Dry-run can be set from MOLTBOOK_DRY_RUN env."""
        with patch.dict(os.environ, {"MOLTBOOK_DRY_RUN": "false"}):
            adapter = MoltbookAdapter(api_key="test_key")
            assert adapter.is_dry_run is False

        with patch.dict(os.environ, {"MOLTBOOK_DRY_RUN": "true"}):
            adapter = MoltbookAdapter(api_key="test_key")
            assert adapter.is_dry_run is True

    def test_dry_run_explicit_override(self):
        """Explicit dry_run parameter overrides env."""
        with patch.dict(os.environ, {"MOLTBOOK_DRY_RUN": "false"}):
            adapter = MoltbookAdapter(api_key="test_key", dry_run=True)
            assert adapter.is_dry_run is True

    @patch("adapters.moltbook.requests.request")
    def test_fetch_events_calls_api(self, mock_request):
        """fetch_events calls /feed endpoint."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "posts": [
                    {
                        "id": "post1",
                        "title": "Test Post",
                        "content": "Hello world?",
                        "author": {"name": "user1"},
                        "created_at": "2025-02-10T10:00:00Z",
                        "submolt": {"name": "test"},
                        "score": 5,
                    }
                ]
            },
        }
        mock_request.return_value = mock_response

        with tempfile.TemporaryDirectory() as log_dir:
            adapter = MoltbookAdapter(
                api_key="test_key",
                agent_name="TestAgent",
                log_dir=log_dir,
            )
            events = adapter.fetch_events(limit=10)

        assert len(events) == 1
        event = events[0]
        assert event["id"] == "post_post1"
        assert event["type"] == "post"
        assert event["author"] == "user1"
        assert "Hello world?" in event["text"]
        assert event["meta"]["is_question"] is True
        assert event["meta"]["post_id"] == "post1"

    @patch("adapters.moltbook.requests.request")
    def test_fetch_events_handles_error(self, mock_request):
        """fetch_events returns empty list on API error."""
        mock_request.side_effect = Exception("Network error")

        with tempfile.TemporaryDirectory() as log_dir:
            adapter = MoltbookAdapter(
                api_key="test_key",
                agent_name="TestAgent",
                log_dir=log_dir,
            )
            events = adapter.fetch_events()

        assert events == []

    def test_send_reply_dry_run_only_logs(self):
        """send_reply in dry-run mode only logs, doesn't call API."""
        with tempfile.TemporaryDirectory() as log_dir:
            adapter = MoltbookAdapter(
                api_key="test_key",
                agent_name="TestAgent",
                dry_run=True,
                log_dir=log_dir,
            )

            # Should not call API, just log
            result = adapter.send_reply("e1", "Test reply", post_id="p1")

            assert result is True

            # Check log file
            log_file = os.path.join(log_dir, "moltbook_replies.jsonl")
            assert os.path.exists(log_file)

            with open(log_file) as f:
                log = json.loads(f.readline())

            assert log["event_id"] == "e1"
            assert log["text"] == "Test reply"
            assert log["dry_run"] is True

    @patch("adapters.moltbook.requests.request")
    def test_send_reply_live_calls_api(self, mock_request):
        """send_reply in live mode calls API."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"success": True}
        mock_request.return_value = mock_response

        with tempfile.TemporaryDirectory() as log_dir:
            adapter = MoltbookAdapter(
                api_key="test_key",
                agent_name="TestAgent",
                dry_run=False,
                log_dir=log_dir,
            )

            result = adapter.send_reply("e1", "Test reply", post_id="p1")

            assert result is True

            # Verify API was called
            mock_request.assert_called()
            call_args = mock_request.call_args
            assert "/posts/p1/comments" in call_args.kwargs["url"]
            assert call_args.kwargs["json"]["content"] == "Test reply"

    def test_send_reply_requires_post_id_for_live(self):
        """send_reply in live mode returns False without post_id."""
        with tempfile.TemporaryDirectory() as log_dir:
            adapter = MoltbookAdapter(
                api_key="test_key",
                agent_name="TestAgent",
                dry_run=False,
                log_dir=log_dir,
            )

            result = adapter.send_reply("e1", "Test reply", post_id=None)

            assert result is False

    @patch("adapters.moltbook.requests.request")
    def test_get_agent_info_calls_api(self, mock_request):
        """get_agent_info calls /agents/me endpoint."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "success": True,
            "agent": {
                "name": "TestAgent",
                "id": "agent123",
                "is_claimed": True,
                "karma": 42,
                "description": "Test",
            },
        }
        mock_request.return_value = mock_response

        adapter = MoltbookAdapter(api_key="test_key")
        info = adapter.get_agent_info()

        assert info["name"] == "TestAgent"
        assert info["id"] == "agent123"
        assert info["is_claimed"] is True
        assert info["karma"] == 42
        assert info["adapter"] == "moltbook"

    @patch("adapters.moltbook.requests.request")
    def test_get_agent_info_caches_result(self, mock_request):
        """get_agent_info caches the result."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "success": True,
            "agent": {"name": "TestAgent", "id": "agent123"},
        }
        mock_request.return_value = mock_response

        adapter = MoltbookAdapter(api_key="test_key")

        # First call
        info1 = adapter.get_agent_info()
        # Second call
        info2 = adapter.get_agent_info()

        # API should only be called once
        assert mock_request.call_count == 1
        assert info1 == info2

    def test_check_mention(self):
        """_check_mention detects agent name in text."""
        adapter = MoltbookAdapter(api_key="test_key", agent_name="TestAgent")

        assert adapter._check_mention("Hey @TestAgent!") is True
        assert adapter._check_mention("Hello @testagent") is True  # case insensitive
        assert adapter._check_mention("Hello world") is False


# =============================================================================
# Test: Rate Limiting
# =============================================================================


class TestMoltbookRateLimiting:
    """Tests for Moltbook adapter rate limiting."""

    def test_rate_limit_check_passes_initially(self):
        """Rate limit check passes when no comments sent."""
        adapter = MoltbookAdapter(api_key="test_key")
        assert adapter._check_rate_limits() is True

    def test_rate_limit_daily_cap(self):
        """Rate limit check fails at daily cap."""
        adapter = MoltbookAdapter(api_key="test_key")
        adapter._comments_today = 50
        adapter._comments_day_key = "2025-02-10"

        # Temporarily set the day to match
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        adapter._comments_day_key = today

        assert adapter._check_rate_limits() is False

    def test_rate_limit_resets_on_new_day(self):
        """Daily counter resets on new day."""
        adapter = MoltbookAdapter(api_key="test_key")
        adapter._comments_today = 50
        adapter._comments_day_key = "1999-01-01"  # Old day

        # Should reset and pass
        assert adapter._check_rate_limits() is True
