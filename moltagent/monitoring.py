"""
Monitoring module for moltbook-agent.

Provides:
- Daily summary logging
- Budget warnings at configurable thresholds
- Error rate tracking
- Status reporting
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .config import LOG_DIR
from .utils import append_jsonl

logger = logging.getLogger(__name__)

# Log file for monitoring data
MONITORING_LOG = os.path.join(LOG_DIR, "monitoring.jsonl")
DAILY_SUMMARY_LOG = os.path.join(LOG_DIR, "daily_summary.jsonl")


@dataclass
class DaemonStats:
    """Statistics for the daemon session."""

    session_start: str = ""
    cycles: int = 0
    total_fetched: int = 0
    total_replied: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    budget_warnings: int = 0
    last_cycle_ts: str = ""

    # Per-day tracking
    day_key: str = ""
    day_replied: int = 0
    day_skipped: int = 0
    day_errors: int = 0
    day_spent_usd: float = 0.0

    # Error tracking (last N errors)
    recent_errors: List[Dict[str, Any]] = field(default_factory=list)
    max_recent_errors: int = 10

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "session_start": self.session_start,
            "cycles": self.cycles,
            "total_fetched": self.total_fetched,
            "total_replied": self.total_replied,
            "total_skipped": self.total_skipped,
            "total_errors": self.total_errors,
            "budget_warnings": self.budget_warnings,
            "last_cycle_ts": self.last_cycle_ts,
            "day_key": self.day_key,
            "day_replied": self.day_replied,
            "day_skipped": self.day_skipped,
            "day_errors": self.day_errors,
            "day_spent_usd": self.day_spent_usd,
            "error_rate": self.error_rate,
        }

    @property
    def error_rate(self) -> float:
        """Calculate error rate as percentage."""
        total = self.total_replied + self.total_skipped + self.total_errors
        if total == 0:
            return 0.0
        return (self.total_errors / total) * 100

    def add_error(self, error_info: Dict[str, Any]) -> None:
        """Add an error to recent errors list."""
        self.recent_errors.append({
            **error_info,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        # Keep only last N errors
        if len(self.recent_errors) > self.max_recent_errors:
            self.recent_errors = self.recent_errors[-self.max_recent_errors:]

    def reset_day(self, new_day_key: str) -> None:
        """Reset daily counters for a new day."""
        self.day_key = new_day_key
        self.day_replied = 0
        self.day_skipped = 0
        self.day_errors = 0
        self.day_spent_usd = 0.0


def check_budget_warning(
    spent_usd: float,
    daily_budget_usd: float,
    warning_threshold: float = 0.80,
) -> Optional[Dict[str, Any]]:
    """
    Check if budget usage exceeds warning threshold.

    Args:
        spent_usd: Amount spent today
        daily_budget_usd: Daily budget limit
        warning_threshold: Threshold for warning (default 80%)

    Returns:
        Warning dict if threshold exceeded, None otherwise
    """
    if daily_budget_usd <= 0:
        return None

    usage_pct = spent_usd / daily_budget_usd

    if usage_pct >= warning_threshold:
        warning = {
            "type": "budget_warning",
            "spent_usd": spent_usd,
            "daily_budget_usd": daily_budget_usd,
            "usage_pct": usage_pct * 100,
            "threshold_pct": warning_threshold * 100,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # Log levels based on usage
        if usage_pct >= 1.0:
            logger.error(
                f"🚨 BUDGET EXHAUSTED: ${spent_usd:.4f} / ${daily_budget_usd:.2f} "
                f"({usage_pct*100:.1f}%)"
            )
            warning["severity"] = "critical"
        elif usage_pct >= 0.95:
            logger.warning(
                f"⚠️  BUDGET CRITICAL: ${spent_usd:.4f} / ${daily_budget_usd:.2f} "
                f"({usage_pct*100:.1f}%)"
            )
            warning["severity"] = "high"
        elif usage_pct >= 0.90:
            logger.warning(
                f"⚠️  Budget warning: ${spent_usd:.4f} / ${daily_budget_usd:.2f} "
                f"({usage_pct*100:.1f}%)"
            )
            warning["severity"] = "medium"
        else:
            logger.info(
                f"📊 Budget at {usage_pct*100:.1f}%: ${spent_usd:.4f} / ${daily_budget_usd:.2f}"
            )
            warning["severity"] = "low"

        return warning

    return None


def log_daily_summary(
    stats: DaemonStats,
    state_spent_usd: float,
    state_calls_today: int,
    daily_budget_usd: float,
) -> Dict[str, Any]:
    """
    Create and log a daily summary.

    Args:
        stats: Daemon statistics
        state_spent_usd: Spent amount from state
        state_calls_today: Call count from state
        daily_budget_usd: Daily budget limit

    Returns:
        Summary dict
    """
    usage_pct = (state_spent_usd / daily_budget_usd * 100) if daily_budget_usd > 0 else 0

    summary = {
        "type": "daily_summary",
        "day_key": stats.day_key,
        "ts": datetime.now(timezone.utc).isoformat(),
        "budget": {
            "spent_usd": state_spent_usd,
            "daily_budget_usd": daily_budget_usd,
            "usage_pct": usage_pct,
            "remaining_usd": max(0, daily_budget_usd - state_spent_usd),
        },
        "activity": {
            "calls_today": state_calls_today,
            "replied": stats.day_replied,
            "skipped": stats.day_skipped,
            "errors": stats.day_errors,
        },
        "session": {
            "cycles": stats.cycles,
            "total_replied": stats.total_replied,
            "total_errors": stats.total_errors,
            "error_rate_pct": stats.error_rate,
        },
    }

    # Log to file
    append_jsonl(DAILY_SUMMARY_LOG, summary)

    # Console output
    logger.info("=" * 50)
    logger.info(f"📊 DAILY SUMMARY - {stats.day_key}")
    logger.info("=" * 50)
    logger.info(f"   Budget: ${state_spent_usd:.4f} / ${daily_budget_usd:.2f} ({usage_pct:.1f}%)")
    logger.info(f"   Calls: {state_calls_today}")
    logger.info(f"   Replied: {stats.day_replied} | Skipped: {stats.day_skipped} | Errors: {stats.day_errors}")
    logger.info(f"   Error rate: {stats.error_rate:.1f}%")
    logger.info("=" * 50)

    return summary


def log_cycle_stats(
    cycle_num: int,
    cycle_stats: Dict[str, int],
    state_spent_usd: float,
    state_calls_today: int,
) -> None:
    """Log statistics for a single polling cycle."""
    entry = {
        "type": "cycle_stats",
        "cycle": cycle_num,
        "ts": datetime.now(timezone.utc).isoformat(),
        "fetched": cycle_stats.get("fetched", 0),
        "replied": cycle_stats.get("replied", 0),
        "skipped": cycle_stats.get("skipped", 0),
        "errors": cycle_stats.get("errors", 0),
        "state_spent_usd": state_spent_usd,
        "state_calls_today": state_calls_today,
    }
    append_jsonl(MONITORING_LOG, entry)


def get_status_report(
    stats: DaemonStats,
    state_spent_usd: float,
    state_calls_today: int,
    daily_budget_usd: float,
    adapter_name: str,
    is_dry_run: bool,
) -> str:
    """
    Generate a human-readable status report.

    Returns:
        Formatted status string
    """
    usage_pct = (state_spent_usd / daily_budget_usd * 100) if daily_budget_usd > 0 else 0

    lines = [
        "=" * 50,
        "🦞 MOLTBOOK AGENT STATUS",
        "=" * 50,
        f"Adapter: {adapter_name} {'(DRY-RUN)' if is_dry_run else '(LIVE)'}",
        f"Session started: {stats.session_start}",
        f"Uptime cycles: {stats.cycles}",
        "",
        "📊 TODAY'S ACTIVITY",
        f"   Day: {stats.day_key}",
        f"   Budget: ${state_spent_usd:.4f} / ${daily_budget_usd:.2f} ({usage_pct:.1f}%)",
        f"   Calls: {state_calls_today}",
        f"   Replied: {stats.day_replied}",
        f"   Skipped: {stats.day_skipped}",
        f"   Errors: {stats.day_errors}",
        "",
        "📈 SESSION TOTALS",
        f"   Total fetched: {stats.total_fetched}",
        f"   Total replied: {stats.total_replied}",
        f"   Total skipped: {stats.total_skipped}",
        f"   Total errors: {stats.total_errors}",
        f"   Error rate: {stats.error_rate:.1f}%",
        f"   Budget warnings: {stats.budget_warnings}",
        "",
    ]

    if stats.recent_errors:
        lines.append("⚠️  RECENT ERRORS")
        for err in stats.recent_errors[-3:]:
            lines.append(f"   - {err.get('ts', '?')}: {err.get('message', 'Unknown')}")
        lines.append("")

    lines.append("=" * 50)

    return "\n".join(lines)


def check_error_rate_alert(
    stats: DaemonStats,
    threshold_pct: float = 10.0,
) -> Optional[Dict[str, Any]]:
    """
    Check if error rate exceeds threshold.

    Args:
        stats: Daemon statistics
        threshold_pct: Error rate threshold percentage

    Returns:
        Alert dict if threshold exceeded, None otherwise
    """
    if stats.error_rate >= threshold_pct:
        alert = {
            "type": "error_rate_alert",
            "error_rate_pct": stats.error_rate,
            "threshold_pct": threshold_pct,
            "total_errors": stats.total_errors,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        logger.warning(
            f"⚠️  High error rate: {stats.error_rate:.1f}% "
            f"(threshold: {threshold_pct:.1f}%)"
        )

        append_jsonl(MONITORING_LOG, alert)
        return alert

    return None
