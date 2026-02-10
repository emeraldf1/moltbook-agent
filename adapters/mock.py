"""
Mock adapter for moltbook-agent.

Reads events from events.jsonl and logs replies to mock_replies.jsonl.
Useful for testing and development without hitting real APIs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import BaseAdapter


class MockAdapter(BaseAdapter):
    """
    Mock adapter that reads from JSONL files.

    Events are read from events_file (default: events.jsonl).
    Replies are logged to logs/mock_replies.jsonl.
    """

    def __init__(
        self,
        events_file: str = "events.jsonl",
        log_dir: str = "logs",
        agent_name: str = "MockAgent",
        dry_run: bool = True,
    ):
        """
        Initialize mock adapter.

        Args:
            events_file: Path to JSONL file with events
            log_dir: Directory for log files
            agent_name: Name of the agent (for mention detection)
            dry_run: If True, replies are only logged (default behavior)
        """
        self._events_file = events_file
        self._log_dir = log_dir
        self._agent_name = agent_name
        self._dry_run = dry_run

        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)

    def fetch_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch events from events.jsonl file.

        Args:
            limit: Maximum number of events to return

        Returns:
            List of event dicts
        """
        events = []

        if not os.path.exists(self._events_file):
            return events

        with open(self._events_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    # Ensure required fields and normalize format
                    normalized = self._normalize_event(event)
                    events.append(normalized)
                except json.JSONDecodeError:
                    continue

                if len(events) >= limit:
                    break

        return events

    def _normalize_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize event to standard format.

        Ensures all required fields exist with proper defaults.
        """
        text = event.get("text", "")

        # Build meta with defaults
        meta = event.get("meta", {})
        if "is_question" not in meta:
            meta["is_question"] = text.strip().endswith("?")
        if "mentions_me" not in meta:
            meta["mentions_me"] = f"@{self._agent_name}".lower() in text.lower()

        return {
            "id": event.get("id", f"mock_{id(event)}"),
            "type": event.get("type", "comment"),
            "author": event.get("author", "unknown"),
            "text": text,
            "ts": event.get("ts", datetime.now(timezone.utc).isoformat()),
            "meta": meta,
        }

    def send_reply(
        self,
        event_id: str,
        text: str,
        post_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> bool:
        """
        Log a reply to mock_replies.jsonl.

        In mock mode, replies are always just logged, never actually sent.

        Args:
            event_id: The event ID being replied to
            text: Reply text
            post_id: Post ID (ignored in mock)
            parent_id: Parent comment ID (ignored in mock)

        Returns:
            Always True (logging always succeeds)
        """
        reply_log = {
            "event_id": event_id,
            "text": text,
            "post_id": post_id,
            "parent_id": parent_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "dry_run": self._dry_run,
        }

        log_file = os.path.join(self._log_dir, "mock_replies.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(reply_log, ensure_ascii=False) + "\n")

        return True

    def get_agent_info(self) -> Dict[str, Any]:
        """
        Return mock agent info.

        Returns:
            Dict with mock agent data
        """
        return {
            "name": self._agent_name,
            "id": "mock_agent_id",
            "is_claimed": True,
            "karma": 0,
            "adapter": "mock",
        }

    @property
    def agent_name(self) -> str:
        """Return the agent's name."""
        return self._agent_name

    @property
    def is_dry_run(self) -> bool:
        """Mock adapter is always effectively dry-run (no real platform)."""
        return True
