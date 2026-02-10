"""
Moltbook adapter for moltbook-agent.

Connects to the real Moltbook API for fetching events and sending replies.
Includes dry-run mode for safe development.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from .base import BaseAdapter

logger = logging.getLogger(__name__)


class MoltbookAdapter(BaseAdapter):
    """
    Moltbook API adapter.

    Fetches events from Moltbook feed and posts comments as replies.
    Supports dry-run mode where reads work but writes are only logged.
    """

    BASE_URL = "https://www.moltbook.com/api/v1"

    # Moltbook rate limits
    MIN_SECONDS_BETWEEN_COMMENTS = 20  # 1 comment per 20 seconds
    MAX_COMMENTS_PER_DAY = 50

    def __init__(
        self,
        api_key: Optional[str] = None,
        agent_name: Optional[str] = None,
        dry_run: Optional[bool] = None,
        log_dir: str = "logs",
    ):
        """
        Initialize Moltbook adapter.

        Args:
            api_key: Moltbook API key (default: from MOLTBOOK_API_KEY env)
            agent_name: Agent name (default: from MOLTBOOK_AGENT_NAME env)
            dry_run: If True, don't actually post (default: from MOLTBOOK_DRY_RUN env, True if not set)
            log_dir: Directory for log files
        """
        self._api_key = api_key or os.environ.get("MOLTBOOK_API_KEY")
        self._agent_name_config = agent_name or os.environ.get("MOLTBOOK_AGENT_NAME", "")
        self._log_dir = log_dir

        # Dry-run: default to True for safety
        if dry_run is not None:
            self._dry_run = dry_run
        else:
            env_dry_run = os.environ.get("MOLTBOOK_DRY_RUN", "true").lower()
            self._dry_run = env_dry_run in ("true", "1", "yes")

        # Validate API key
        if not self._api_key:
            raise ValueError(
                "MOLTBOOK_API_KEY not set. "
                "Set it in .env or pass api_key parameter."
            )

        # Track last comment time for rate limiting
        self._last_comment_ts: float = 0
        self._comments_today: int = 0
        self._comments_day_key: str = ""

        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)

        # Cache agent info
        self._agent_info: Optional[Dict[str, Any]] = None

    def _get_headers(self) -> Dict[str, str]:
        """Return headers for API requests."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make an API request with error handling.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/feed")
            data: JSON body for POST requests
            params: Query parameters
            timeout: Request timeout in seconds

        Returns:
            Response data dict

        Raises:
            requests.RequestException: On network/API errors
        """
        url = f"{self.BASE_URL}{endpoint}"

        response = requests.request(
            method=method,
            url=url,
            headers=self._get_headers(),
            json=data,
            params=params,
            timeout=timeout,
        )

        # Parse response
        try:
            result = response.json()
        except json.JSONDecodeError:
            result = {"success": False, "error": response.text}

        # Check for errors
        if not response.ok or not result.get("success", True):
            error_msg = result.get("error", f"HTTP {response.status_code}")
            hint = result.get("hint", "")
            logger.error(f"Moltbook API error: {error_msg}. {hint}")
            raise requests.RequestException(f"{error_msg}. {hint}")

        return result

    def fetch_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch events from Moltbook feed.

        Gets posts from subscribed submolts and followed agents.

        Args:
            limit: Maximum number of events to fetch

        Returns:
            List of normalized event dicts
        """
        try:
            result = self._make_request(
                "GET",
                "/feed",
                params={"limit": limit, "sort": "new"},
            )
        except Exception as e:
            logger.error(f"Failed to fetch feed: {e}")
            return []

        # API returns posts at top level, not in data
        posts = result.get("posts", []) or result.get("data", {}).get("posts", [])
        events = []

        for post in posts:
            event = self._post_to_event(post)
            if event:
                events.append(event)

        # Log fetched events
        self._log_fetched_events(events)

        return events

    def _post_to_event(self, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a Moltbook post to our event format.

        Args:
            post: Moltbook API post object

        Returns:
            Normalized event dict or None if invalid
        """
        try:
            post_id = post.get("id", "")
            author_info = post.get("author", {})
            author_name = author_info.get("name", "unknown")

            # Combine title and content
            title = post.get("title", "")
            content = post.get("content", "")
            text = f"{title}\n\n{content}".strip() if title else content

            # Detect question and mention
            is_question = text.strip().endswith("?")
            mentions_me = self._check_mention(text)

            return {
                "id": f"post_{post_id}",
                "type": "post",
                "author": author_name,
                "text": text,
                "ts": post.get("created_at", datetime.now(timezone.utc).isoformat()),
                "meta": {
                    "is_question": is_question,
                    "mentions_me": mentions_me,
                    "post_id": post_id,
                    "submolt": post.get("submolt", {}).get("name", ""),
                    "score": post.get("score", 0),
                },
            }
        except Exception as e:
            logger.warning(f"Failed to parse post: {e}")
            return None

    def _check_mention(self, text: str) -> bool:
        """Check if agent is mentioned in text."""
        if not self._agent_name_config:
            # Try to get from API
            try:
                info = self.get_agent_info()
                agent_name = info.get("name", "")
            except Exception:
                return False
        else:
            agent_name = self._agent_name_config

        if not agent_name:
            return False

        return f"@{agent_name}".lower() in text.lower()

    def send_reply(
        self,
        event_id: str,
        text: str,
        post_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> bool:
        """
        Send a reply as a comment on a post.

        In dry-run mode, the reply is logged but not actually sent.

        Args:
            event_id: The event ID being replied to (for logging)
            text: Reply text
            post_id: Post ID to comment on (required)
            parent_id: Parent comment ID for nested replies

        Returns:
            True if reply was sent (or logged in dry-run), False on error
        """
        # Check rate limits
        if not self._check_rate_limits():
            logger.warning("Rate limit reached, cannot send reply")
            return False

        # Log the intended reply
        reply_log = {
            "event_id": event_id,
            "text": text,
            "post_id": post_id,
            "parent_id": parent_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "dry_run": self._dry_run,
        }

        log_file = os.path.join(self._log_dir, "moltbook_replies.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(reply_log, ensure_ascii=False) + "\n")

        # In dry-run mode, stop here
        if self._dry_run:
            logger.info(f"[DRY-RUN] Would send reply to {event_id}: {text[:50]}...")
            return True

        # Actually send the reply
        if not post_id:
            logger.error("Cannot send reply: post_id is required")
            return False

        try:
            data = {"content": text}
            if parent_id:
                data["parent_id"] = parent_id

            result = self._make_request(
                "POST",
                f"/posts/{post_id}/comments",
                data=data,
            )

            # Update rate limit tracking
            self._last_comment_ts = time.time()
            self._update_daily_counter()

            logger.info(f"Reply sent to post {post_id}: {text[:50]}...")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send reply: {e}")
            return False

    def _check_rate_limits(self) -> bool:
        """
        Check if we're within Moltbook rate limits.

        Returns:
            True if we can post, False if rate limited
        """
        # Check daily limit
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._comments_day_key != today:
            self._comments_day_key = today
            self._comments_today = 0

        if self._comments_today >= self.MAX_COMMENTS_PER_DAY:
            logger.warning(f"Daily comment limit reached ({self.MAX_COMMENTS_PER_DAY})")
            return False

        # Check time between comments
        if self._last_comment_ts > 0:
            elapsed = time.time() - self._last_comment_ts
            if elapsed < self.MIN_SECONDS_BETWEEN_COMMENTS:
                wait_time = self.MIN_SECONDS_BETWEEN_COMMENTS - elapsed
                logger.warning(f"Must wait {wait_time:.1f}s between comments")
                return False

        return True

    def _update_daily_counter(self) -> None:
        """Update the daily comment counter."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._comments_day_key != today:
            self._comments_day_key = today
            self._comments_today = 0
        self._comments_today += 1

    def get_agent_info(self) -> Dict[str, Any]:
        """
        Get information about the current agent from Moltbook API.

        Returns:
            Dict with agent info

        Raises:
            requests.RequestException: On API error
        """
        # Return cached info if available
        if self._agent_info:
            return self._agent_info

        result = self._make_request("GET", "/agents/me")
        agent_data = result.get("agent", {})

        self._agent_info = {
            "name": agent_data.get("name", ""),
            "id": agent_data.get("id", ""),
            "is_claimed": agent_data.get("is_claimed", False),
            "karma": agent_data.get("karma", 0),
            "description": agent_data.get("description", ""),
            "adapter": "moltbook",
        }

        # Update agent name if not configured
        if not self._agent_name_config and self._agent_info["name"]:
            self._agent_name_config = self._agent_info["name"]

        return self._agent_info

    def _log_fetched_events(self, events: List[Dict[str, Any]]) -> None:
        """Log fetched events for debugging."""
        log_file = os.path.join(self._log_dir, "moltbook_fetched.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            for event in events:
                log_entry = {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "event": event,
                }
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    @property
    def agent_name(self) -> str:
        """Return the agent's name."""
        if self._agent_name_config:
            return self._agent_name_config
        # Try to get from API
        try:
            info = self.get_agent_info()
            return info.get("name", "")
        except Exception:
            return ""

    @property
    def is_dry_run(self) -> bool:
        """Return True if adapter is in dry-run mode."""
        return self._dry_run
