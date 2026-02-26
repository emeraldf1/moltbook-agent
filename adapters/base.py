"""
Base adapter interface for moltbook-agent.

All adapters must implement this interface to provide
a unified way of fetching events and sending replies.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAdapter(ABC):
    """
    Abstract base class for platform adapters.

    Adapters handle:
    - Fetching events from the platform
    - Sending replies back to the platform
    - Getting agent/user info
    """

    @abstractmethod
    def fetch_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch new events from the platform.

        Args:
            limit: Maximum number of events to fetch

        Returns:
            List of event dicts with format:
            {
                "id": str,           # Unique event ID
                "type": str,         # "post" or "comment"
                "author": str,       # Author name
                "text": str,         # Event content
                "ts": str,           # ISO timestamp
                "meta": {
                    "is_question": bool,
                    "mentions_me": bool,
                    "post_id": str,      # For comments: parent post ID
                    "parent_id": str,    # For nested comments
                }
            }
        """
        pass

    @abstractmethod
    def send_reply(
        self,
        event_id: str,
        text: str,
        post_id: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> bool:
        """
        Send a reply to an event.

        Args:
            event_id: The event ID being replied to (for logging)
            text: Reply text content
            post_id: Post ID to comment on (required for Moltbook)
            parent_id: Parent comment ID (for nested replies)

        Returns:
            True if reply was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_agent_info(self) -> Dict[str, Any]:
        """
        Get information about the current agent.

        Returns:
            Dict with agent info:
            {
                "name": str,
                "id": str,
                "is_claimed": bool,
                "karma": int,
                ...
            }
        """
        pass

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Return the agent's name for mention detection."""
        pass

    @property
    @abstractmethod
    def is_dry_run(self) -> bool:
        """Return True if adapter is in dry-run mode (no writes)."""
        pass

    def respond_to_challenge(self, post_id: str) -> bool:
        """
        Respond to a platform moderation challenge post.

        The Moltbook auto-mod sends challenge events to verify the agent
        is alive and operational. Failing to respond results in suspension.

        Args:
            post_id: The challenge post ID to reply to

        Returns:
            True if challenge was answered, False otherwise.
            Default implementation is a no-op (not supported).
        """
        return False

    def create_post(self, title: str, submolt: str, submolt_name: str) -> Optional[str]:
        """
        Create a new standalone post on the platform.

        Args:
            title: Post title / content (max 300 chars for Moltbook)
            submolt: Submolt slug/identifier (e.g. "general")
            submolt_name: Submolt display name (e.g. "General")

        Returns:
            post_id if created successfully, None otherwise.
            Default implementation returns None (not supported).
        """
        return None
