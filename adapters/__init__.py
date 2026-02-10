"""
Adapters package for moltbook-agent.

Adapters provide a unified interface for fetching events and sending replies
to different platforms (mock, Moltbook, etc.).
"""
from __future__ import annotations

from .base import BaseAdapter
from .mock import MockAdapter
from .moltbook import MoltbookAdapter

__all__ = [
    "BaseAdapter",
    "MockAdapter",
    "MoltbookAdapter",
]


def get_adapter(adapter_type: str, **kwargs) -> BaseAdapter:
    """
    Factory function to get an adapter by type.

    Args:
        adapter_type: "mock" or "moltbook"
        **kwargs: Adapter-specific configuration

    Returns:
        Configured adapter instance

    Raises:
        ValueError: If adapter_type is unknown
    """
    adapters = {
        "mock": MockAdapter,
        "moltbook": MoltbookAdapter,
    }

    if adapter_type not in adapters:
        raise ValueError(f"Unknown adapter type: {adapter_type}. Available: {list(adapters.keys())}")

    return adapters[adapter_type](**kwargs)
