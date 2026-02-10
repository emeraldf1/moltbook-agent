#!/usr/bin/env python3
"""
agent_daemon.py - Folyamatosan futó Moltbook Agent daemon.

Periodikusan lekéri a Moltbook feed-et és feldolgozza az eseményeket.
Systemd service-ként vagy standalone daemon-ként futtatható.

Használat:
    python agent_daemon.py              # Dry-run (alapértelmezett)
    python agent_daemon.py --live       # Éles mód (tényleg posztol)
    python agent_daemon.py --once       # Egyszer fut, majd kilép
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

from moltagent import (
    LOG_DIR,
    EVENT_LOG,
    DECISION_LOG,
    OUTBOUND_LOG,
    OPERATOR_LOG,
    load_state,
    save_state,
    ensure_today,
    load_policy,
    should_reply,
    make_outbound_reply,
    build_prompt,
    rate_limit,
    hu_operator_summary,
    ensure_dirs,
    append_jsonl,
    estimate_tokens,
    estimate_cost_usd,
)
from moltagent.retry import ReplyError
from moltagent.config import CHARS_PER_TOKEN_EST, USD_PER_1M_INPUT_TOKENS, USD_PER_1M_OUTPUT_TOKENS
from moltagent.monitoring import (
    DaemonStats,
    check_budget_warning,
    log_daily_summary,
    log_cycle_stats,
    check_error_rate_alert,
)
from adapters import get_adapter, BaseAdapter

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    shutdown_requested = True


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Moltbook Agent daemon - continuous polling"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually send replies (disables dry-run)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (useful for testing)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Override poll interval in seconds"
    )
    return parser.parse_args()


def process_event(
    event: Dict[str, Any],
    policy: Dict[str, Any],
    adapter: BaseAdapter,
    client: OpenAI,
) -> Optional[Dict[str, Any]]:
    """
    Process a single event through the decision pipeline.

    Returns the decision dict or None on error.
    """
    st = load_state()
    st = ensure_today(st)

    event_id = event.get("id", "unknown")

    # Decision
    decision = should_reply(event, policy, st, dry_run=adapter.is_dry_run)

    # Apply P2 hourly cap counter
    if decision.get("reply") and decision.get("priority") == "P2" and decision.get("mode") == "normal":
        st.p2_replies_this_hour += 1
        save_state(st)

    # Log decision
    decision_log_entry = {
        "event_id": event_id,
        "ts": event.get("ts"),
        "type": event.get("type"),
        "author": event.get("author"),
        "decision": decision,
        "day_key": st.day_key,
        "hour_key": st.hour_key,
        "daemon_ts": datetime.now(timezone.utc).isoformat(),
    }
    append_jsonl(DECISION_LOG, decision_log_entry)

    reason = decision.get("reason", "?")
    prio = decision.get("priority", "?")

    if not decision["reply"]:
        logger.info(f"SKIP {event_id} ({reason}, {prio})")

        # Operator view for skipped items
        op = hu_operator_summary(event, decision, reply_en=None)
        append_jsonl(OPERATOR_LOG, {
            "event_id": event_id,
            "operator_summary_hu": op,
        })
        return decision

    # Rate limit
    rate_limit(policy, st)

    mode = decision.get("mode", "normal")

    # Generate reply via OpenAI
    try:
        reply_en, in_tok, out_tok = make_outbound_reply(
            event, policy, mode, client, event_id=event_id
        )
    except ReplyError as err:
        logger.error(f"API error for {event_id}: {err.error_type} - {err.message}")
        return None

    # Update state
    st = load_state()  # Reload in case of concurrent changes
    st = ensure_today(st)
    st.calls_today += 1
    st.last_call_ts = time.time()

    if event_id:
        st.mark_replied(event_id)

    # Estimate cost
    if in_tok == 0 and out_tok == 0:
        in_tok = estimate_tokens(build_prompt(event, policy, mode), CHARS_PER_TOKEN_EST)
        out_tok = estimate_tokens(reply_en, CHARS_PER_TOKEN_EST)

    est = estimate_cost_usd(in_tok, out_tok, USD_PER_1M_INPUT_TOKENS, USD_PER_1M_OUTPUT_TOKENS)
    st.spent_usd += est
    save_state(st)

    # Send reply through adapter
    post_id = event.get("meta", {}).get("post_id")
    parent_id = event.get("meta", {}).get("parent_id")

    reply_sent = adapter.send_reply(
        event_id=event_id,
        text=reply_en,
        post_id=post_id,
        parent_id=parent_id,
    )

    reply_status = "SENT" if reply_sent and not adapter.is_dry_run else "LOGGED (dry-run)"

    logger.info(f"REPLY {event_id} ({reason}, {prio}) - {reply_status}")
    logger.debug(f"  Reply: {reply_en[:80]}...")

    # Log outbound
    append_jsonl(OUTBOUND_LOG, {
        "event_id": event_id,
        "ts": event.get("ts"),
        "type": event.get("type"),
        "author": event.get("author"),
        "reply_en": reply_en,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
        "est_usd": est,
        "reply_status": reply_status,
        "daemon_ts": datetime.now(timezone.utc).isoformat(),
    })

    # Operator view
    op = hu_operator_summary(event, decision, reply_en=reply_en)
    append_jsonl(OPERATOR_LOG, {
        "event_id": event_id,
        "operator_summary_hu": op,
        "day_total_est_usd": st.spent_usd,
        "calls_today": st.calls_today,
    })

    return decision


def run_poll_cycle(
    adapter: BaseAdapter,
    policy: Dict[str, Any],
    client: OpenAI,
    limit: int = 20,
) -> Dict[str, int]:
    """
    Run one polling cycle: fetch events and process them.

    Returns stats dict with counts.
    """
    stats = {"fetched": 0, "processed": 0, "replied": 0, "skipped": 0, "errors": 0}

    # Fetch events
    events = adapter.fetch_events(limit=limit)
    stats["fetched"] = len(events)

    if not events:
        logger.debug("No events in feed")
        return stats

    logger.info(f"Fetched {len(events)} events from feed")

    # Log input events
    for event in events:
        append_jsonl(EVENT_LOG, {
            **event,
            "daemon_fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    # Process each event
    for event in events:
        if shutdown_requested:
            logger.info("Shutdown requested, stopping processing")
            break

        try:
            decision = process_event(event, policy, adapter, client)
            stats["processed"] += 1

            if decision is None:
                stats["errors"] += 1
            elif decision.get("reply"):
                stats["replied"] += 1
            else:
                stats["skipped"] += 1

        except Exception as e:
            logger.exception(f"Error processing event {event.get('id')}: {e}")
            stats["errors"] += 1

    return stats


def main() -> int:
    """Main daemon entry point."""
    global shutdown_requested

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Load environment
    load_dotenv()

    args = parse_args()
    ensure_dirs(LOG_DIR)

    # Load and validate policy
    try:
        policy = load_policy(validate=True)
        logger.info("✅ Policy loaded and validated")
    except ValueError as e:
        logger.error(f"❌ Policy error: {e}")
        return 1

    # Get poll interval from policy or args
    moltbook_config = policy.get("moltbook", {})
    poll_interval = args.interval or moltbook_config.get("poll_interval_sec", 60)

    # Initialize adapter
    dry_run = not args.live

    try:
        adapter = get_adapter(
            "moltbook",
            dry_run=dry_run,
            log_dir=LOG_DIR,
        )
    except ValueError as e:
        logger.error(f"❌ Adapter error: {e}")
        return 1

    logger.info(f"✅ Adapter: moltbook")
    logger.info(f"   Agent: {adapter.agent_name}")
    logger.info(f"   Dry-run: {adapter.is_dry_run}")
    logger.info(f"   Poll interval: {poll_interval}s")

    # Initialize OpenAI client
    client = OpenAI()

    # Initialize monitoring stats
    daemon_stats = DaemonStats(
        session_start=datetime.now(timezone.utc).isoformat(),
    )

    # Get initial state for day tracking
    st = load_state()
    st = ensure_today(st)
    daemon_stats.day_key = st.day_key
    daemon_stats.day_spent_usd = st.spent_usd

    # Log startup
    logger.info("=" * 50)
    logger.info("🦞 Moltbook Agent Daemon Started")
    logger.info("=" * 50)

    daily_budget_usd = policy.get("daily_budget_usd", 1.0)
    last_budget_warning_pct = 0  # Track to avoid duplicate warnings

    while not shutdown_requested:
        daemon_stats.cycles += 1
        cycle_start = time.time()

        logger.info(f"--- Poll cycle #{daemon_stats.cycles} ---")

        try:
            # Reload policy each cycle (allows hot-reload)
            policy = load_policy(validate=False)
            daily_budget_usd = policy.get("daily_budget_usd", 1.0)

            # Check for day change
            st = load_state()
            st = ensure_today(st)

            if st.day_key != daemon_stats.day_key:
                # New day! Log daily summary for previous day
                log_daily_summary(
                    daemon_stats,
                    daemon_stats.day_spent_usd,
                    st.calls_today,
                    daily_budget_usd,
                )
                daemon_stats.reset_day(st.day_key)
                last_budget_warning_pct = 0
                logger.info(f"📅 New day: {st.day_key}")

            # Run poll cycle
            stats = run_poll_cycle(adapter, policy, client)

            # Update daemon stats
            daemon_stats.total_fetched += stats["fetched"]
            daemon_stats.total_replied += stats["replied"]
            daemon_stats.total_skipped += stats["skipped"]
            daemon_stats.total_errors += stats["errors"]
            daemon_stats.day_replied += stats["replied"]
            daemon_stats.day_skipped += stats["skipped"]
            daemon_stats.day_errors += stats["errors"]
            daemon_stats.last_cycle_ts = datetime.now(timezone.utc).isoformat()

            # Update spent tracking
            st = load_state()
            daemon_stats.day_spent_usd = st.spent_usd

            # Log cycle stats to monitoring log
            log_cycle_stats(
                daemon_stats.cycles,
                stats,
                st.spent_usd,
                st.calls_today,
            )

            # Check budget warning (only warn once per threshold)
            current_pct = (st.spent_usd / daily_budget_usd * 100) if daily_budget_usd > 0 else 0
            warning_thresholds = [80, 90, 95, 100]
            for threshold in warning_thresholds:
                if current_pct >= threshold and last_budget_warning_pct < threshold:
                    warning = check_budget_warning(
                        st.spent_usd,
                        daily_budget_usd,
                        warning_threshold=threshold / 100,
                    )
                    if warning:
                        daemon_stats.budget_warnings += 1
                        last_budget_warning_pct = threshold

            # Check error rate
            check_error_rate_alert(daemon_stats, threshold_pct=10.0)

            logger.info(
                f"Cycle #{daemon_stats.cycles}: "
                f"fetched={stats['fetched']}, replied={stats['replied']}, "
                f"skipped={stats['skipped']}, errors={stats['errors']} "
                f"| Budget: ${st.spent_usd:.4f}/{daily_budget_usd:.2f}"
            )

        except Exception as e:
            logger.exception(f"Error in poll cycle: {e}")
            daemon_stats.total_errors += 1
            daemon_stats.day_errors += 1
            daemon_stats.add_error({"message": str(e), "type": "cycle_error"})

        # Exit if --once flag
        if args.once:
            logger.info("--once flag set, exiting after first cycle")
            break

        # Sleep until next cycle
        elapsed = time.time() - cycle_start
        sleep_time = max(0, poll_interval - elapsed)

        if sleep_time > 0 and not shutdown_requested:
            logger.debug(f"Sleeping {sleep_time:.1f}s until next cycle")

            # Sleep in small increments to allow graceful shutdown
            sleep_end = time.time() + sleep_time
            while time.time() < sleep_end and not shutdown_requested:
                time.sleep(min(1.0, sleep_end - time.time()))

    # Final daily summary
    st = load_state()
    log_daily_summary(daemon_stats, st.spent_usd, st.calls_today, daily_budget_usd)

    # Shutdown summary
    logger.info("=" * 50)
    logger.info("🦞 Moltbook Agent Daemon Stopped")
    logger.info(f"   Total cycles: {daemon_stats.cycles}")
    logger.info(f"   Total fetched: {daemon_stats.total_fetched}")
    logger.info(f"   Total replied: {daemon_stats.total_replied}")
    logger.info(f"   Total skipped: {daemon_stats.total_skipped}")
    logger.info(f"   Total errors: {daemon_stats.total_errors}")
    logger.info(f"   Error rate: {daemon_stats.error_rate:.1f}%")
    logger.info(f"   Budget warnings: {daemon_stats.budget_warnings}")
    logger.info("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
