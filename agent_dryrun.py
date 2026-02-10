#!/usr/bin/env python3
"""
agent_dryrun.py - Dry-run feldolgozó a moltagent csomaggal.

Scheduler (Daily Pacer) támogatással - policy.json-ban kapcsolható:
  "scheduler": {"enabled": true/false, "burst_p0": 8, "burst_p1": 4}

Adapter támogatás - policy.json-ban:
  "adapter": "mock" | "moltbook"
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, List

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
from moltagent.utils import TZ_HOURS
from moltagent.config import CHARS_PER_TOKEN_EST, USD_PER_1M_INPUT_TOKENS, USD_PER_1M_OUTPUT_TOKENS
from adapters import get_adapter, BaseAdapter

load_dotenv()
client = OpenAI()


def load_events(path: str = "events.jsonl") -> List[Dict[str, Any]]:
    """Betölti az eseményeket a JSONL fájlból. (Legacy - mock adapter használja)"""
    if not os.path.exists(path):
        return []

    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def get_events_from_adapter(adapter: BaseAdapter, limit: int = 50) -> List[Dict[str, Any]]:
    """Események lekérése az adapterből."""
    return adapter.fetch_events(limit=limit)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Moltbook Agent dry-run processor"
    )
    parser.add_argument(
        "--adapter",
        choices=["mock", "moltbook"],
        help="Adapter to use (overrides policy.json)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually send replies (disables dry-run for Moltbook adapter)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of events to fetch (default: 50)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs(LOG_DIR)

    # Policy validáció induláskor (SPEC §13.4)
    try:
        policy = load_policy(validate=True)
        print("✅ Policy OK")
    except ValueError as e:
        print(str(e))
        print("\n❌ Az agent nem indul el hibás policy miatt.")
        return

    # Initialize adapter
    adapter_type = args.adapter or policy.get("adapter", "mock")

    # Dry-run mode: only --live flag disables it for moltbook
    dry_run = not args.live

    try:
        if adapter_type == "mock":
            adapter = get_adapter(
                "mock",
                events_file="events.jsonl",
                log_dir=LOG_DIR,
                agent_name=os.environ.get("MOLTBOOK_AGENT_NAME", "MockAgent"),
            )
        else:
            adapter = get_adapter(
                "moltbook",
                dry_run=dry_run,
                log_dir=LOG_DIR,
            )
    except ValueError as e:
        print(f"❌ Adapter hiba: {e}")
        return

    print(f"✅ Adapter: {adapter_type}")
    print(f"   Agent: {adapter.agent_name}")
    print(f"   Dry-run: {adapter.is_dry_run}")

    st = load_state()
    st = ensure_today(st)

    # Fetch events from adapter
    events = get_events_from_adapter(adapter, limit=args.limit)
    if not events:
        print("\n⚠️  Nincsenek események (üres feed vagy nincs events.jsonl)")
        return

    # Log input events
    for e in events:
        append_jsonl(EVENT_LOG, e)

    print(f"\n[dry-run] loaded {len(events)} events")
    print(f"[dry-run] state day={st.day_key} spent=${st.spent_usd:.4f} calls={st.calls_today}")
    print(f"[dry-run] burst_p0={st.burst_used_p0} burst_p1={st.burst_used_p1} hour={st.hour_key} (UTC{TZ_HOURS:+d})")

    # Scheduler config info
    sched_cfg = policy.get("scheduler", {})
    sched_enabled = sched_cfg.get("enabled", True)
    burst_p0 = sched_cfg.get("burst_p0", 8)
    burst_p1 = sched_cfg.get("burst_p1", 4)
    print(f"[dry-run] scheduler enabled={sched_enabled} burst_p0={burst_p0} burst_p1={burst_p1}\n")

    for e in events:
        st = ensure_today(st)

        # Döntés (scheduler integrálva)
        decision = should_reply(e, policy, st, dry_run=True)

        # Apply P2 hourly cap counter if decision says reply with P2 normal
        if decision.get("reply") and decision.get("priority") == "P2" and decision.get("mode") == "normal":
            st.p2_replies_this_hour += 1
            save_state(st)

        # Write decision log
        decision_log_entry = {
            "event_id": e.get("id"),
            "ts": e.get("ts"),
            "type": e.get("type"),
            "author": e.get("author"),
            "decision": decision,
            "day_key": st.day_key,
            "hour_key": st.hour_key,
        }

        # Ha scheduler várakozást javasol, azt is logoljuk
        sched_info = decision.get("scheduler", {})
        if sched_info.get("wait_seconds"):
            decision_log_entry["scheduler_paced_wait"] = True
            decision_log_entry["wait_seconds"] = sched_info["wait_seconds"]

        append_jsonl(DECISION_LOG, decision_log_entry)

        # Console output
        reason = decision.get("reason", "?")
        prio = decision.get("priority", "?")
        sched_note = ""
        if sched_info:
            if sched_info.get("wait_seconds"):
                sched_note = f" [sched: wait {sched_info['wait_seconds']:.1f}s]"
            elif sched_info.get("used_burst"):
                sched_note = f" [sched: burst_{sched_info.get('burst_type', '?')}]"
            elif sched_info.get("reason"):
                sched_note = f" [sched: {sched_info['reason']}]"

        print(f"- {e.get('id')} {e.get('type')} by {e.get('author')}: {decision['reply']} ({reason}, {prio}){sched_note}")

        if not decision["reply"]:
            # Operator view for skipped items
            op = hu_operator_summary(e, decision, reply_en=None)
            append_jsonl(OPERATOR_LOG, {
                "event_id": e.get("id"),
                "operator_summary_hu": op,
            })
            continue

        # Rate limit
        rate_limit(policy, st)

        mode = decision.get("mode", "normal")
        event_id = e.get("id")

        # API hívás error handling-gel
        try:
            reply_en, in_tok, out_tok = make_outbound_reply(
                e, policy, mode, client, event_id=event_id
            )
        except ReplyError as err:
            # API hiba - logoljuk és SKIP-eljük az eseményt
            print(f"  [ERROR] {err.error_type}: {err.message}")
            print(f"  [SKIP] Event {event_id} - API hiba után skip\n")

            # Operator összefoglaló a hibáról
            error_decision = {
                "reply": False,
                "reason": "api_error",
                "priority": decision.get("priority", "P2"),
                "error": {
                    "type": err.error_type,
                    "message": err.message,
                    "retry_count": err.retry_count,
                },
            }
            op = hu_operator_summary(e, error_decision)
            append_jsonl(OPERATOR_LOG, {
                "event_id": event_id,
                "operator_summary_hu": op,
                "error": err.error_type,
            })
            continue

        # Update state
        st.calls_today += 1
        st.last_call_ts = time.time()

        # Idempotencia: megjelöljük megválaszoltként
        if event_id:
            st.mark_replied(event_id)

        # Estimate cost
        if in_tok == 0 and out_tok == 0:
            in_tok = estimate_tokens(build_prompt(e, policy, mode), CHARS_PER_TOKEN_EST)
            out_tok = estimate_tokens(reply_en, CHARS_PER_TOKEN_EST)

        est = estimate_cost_usd(in_tok, out_tok, USD_PER_1M_INPUT_TOKENS, USD_PER_1M_OUTPUT_TOKENS)
        st.spent_usd += est
        save_state(st)

        # Send reply through adapter
        post_id = e.get("meta", {}).get("post_id")
        parent_id = e.get("meta", {}).get("parent_id")

        reply_sent = adapter.send_reply(
            event_id=event_id,
            text=reply_en,
            post_id=post_id,
            parent_id=parent_id,
        )

        reply_status = "SENT" if reply_sent and not adapter.is_dry_run else "LOGGED (dry-run)"

        # Log outbound (EN only)
        append_jsonl(OUTBOUND_LOG, {
            "event_id": event_id,
            "ts": e.get("ts"),
            "type": e.get("type"),
            "author": e.get("author"),
            "reply_en": reply_en,
            "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
            "est_usd": est,
            "reply_status": reply_status,
        })

        # Operator view (HU)
        op = hu_operator_summary(e, decision, reply_en=reply_en)
        append_jsonl(OPERATOR_LOG, {
            "event_id": event_id,
            "operator_summary_hu": op,
            "day_total_est_usd": st.spent_usd,
            "calls_today": st.calls_today,
        })

        print(f"  [reply EN] {reply_en}")
        print(f"  [status] {reply_status}")
        print(f"  [cost≈] +${est:.4f} → day_total≈${st.spent_usd:.4f}, calls={st.calls_today}\n")

    print("\n[dry-run] done.")
    print(f"[dry-run] final state: spent≈${st.spent_usd:.4f}, calls={st.calls_today}")
    print(f"[dry-run] burst counters: p0={st.burst_used_p0}/{burst_p0}, p1={st.burst_used_p1}/{burst_p1}")
    print(f"[dry-run] logs:\n  - {EVENT_LOG}\n  - {DECISION_LOG}\n  - {OUTBOUND_LOG}\n  - {OPERATOR_LOG}")


if __name__ == "__main__":
    main()
