"""
Döntési logika: should_reply + scheduler integráció.
"""
from __future__ import annotations

from typing import Any, Dict

from .scheduler import scheduler_check, update_burst_counters, SchedulerDecision
from .state import State, ensure_today


def keyword_hit(text_lower: str, keywords: list[str]) -> bool:
    """Ellenőrzi, hogy a szöveg tartalmaz-e bármelyik kulcsszót."""
    return any(k in text_lower for k in keywords)


def should_reply(
    event: Dict[str, Any],
    policy: Dict[str, Any],
    state: State,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Eldönti, hogy válaszoljon-e az agent.

    A döntés lépései:
    0. Idempotencia ellenőrzés (duplicate_event)
    1. Alapvető szabályok (blocked keywords, mentions, questions, relevance)
    2. Scheduler ellenőrzés (Daily Pacer)
    3. P2 hourly cap

    Returns:
        {
            reply: bool,
            priority: "P0"|"P1"|"P2",
            reason: str,
            mode: "normal"|"redirect"|"refuse",
            scheduler: {...}  # ha scheduler döntött
        }
    """
    state = ensure_today(state)

    # --- 0. fázis: Idempotencia ellenőrzés ---
    event_id = event.get("id")
    if event_id and state.has_replied(event_id):
        return {
            "reply": False,
            "priority": "P2",
            "reason": "duplicate_event",
            "original_event_id": event_id,
        }

    text = event.get("text") or ""
    text_lower = text.lower()

    meta = event.get("meta") or {}
    mentions_me = bool(meta.get("mentions_me"))
    is_question = bool(meta.get("is_question")) or text.strip().endswith("?")

    allow_kw = [k.lower() for k in policy.get("topics", {}).get("allow_keywords", [])]
    block_kw = [k.lower() for k in policy.get("topics", {}).get("block_keywords", [])]

    # --- 1. fázis: Alapvető döntés (priority meghatározása) ---

    # Blocked keyword → refuse (de valid P0)
    if keyword_hit(text_lower, block_kw):
        priority = "P0"
        base_decision = {
            "reply": True,
            "priority": priority,
            "reason": "blocked_keyword_refuse",
            "mode": "refuse",
        }
    # Mention → P0
    elif mentions_me and policy.get("reply", {}).get("reply_to_mentions_always", True):
        priority = "P0"
        base_decision = {
            "reply": True,
            "priority": priority,
            "reason": "mention",
            "mode": "normal",
        }
    # Question
    elif is_question and policy.get("reply", {}).get("reply_to_questions_always", True):
        relevant = keyword_hit(text_lower, allow_kw)
        if relevant:
            priority = "P1"
            base_decision = {
                "reply": True,
                "priority": priority,
                "reason": "relevant_question",
                "mode": "normal",
            }
        else:
            mode = policy.get("reply", {}).get("offtopic_question_mode", "redirect")
            if mode == "redirect":
                priority = "P2"
                base_decision = {
                    "reply": True,
                    "priority": priority,
                    "reason": "offtopic_question_redirect",
                    "mode": "redirect",
                }
            else:
                return {
                    "reply": False,
                    "priority": "P2",
                    "reason": "offtopic_question_skip",
                }
    # Non-question, relevant
    elif keyword_hit(text_lower, allow_kw):
        priority = "P2"
        base_decision = {
            "reply": True,
            "priority": priority,
            "reason": "relevant_statement",
            "mode": "normal",
        }
    else:
        return {"reply": False, "priority": "P2", "reason": "not_relevant"}

    # --- 2. fázis: Scheduler ellenőrzés ---
    sched_decision: SchedulerDecision = scheduler_check(
        state=state,
        priority=priority,
        policy=policy,
        dry_run=dry_run,
    )

    if not sched_decision.allowed:
        return {
            "reply": False,
            "priority": priority,
            "reason": sched_decision.reason,
            "scheduler": {
                "wait_seconds": sched_decision.wait_seconds,
                "calls_today": state.calls_today,
                "burst_used_p0": state.burst_used_p0,
                "burst_used_p1": state.burst_used_p1,
            },
        }

    # Burst használat frissítése
    update_burst_counters(state, sched_decision)

    # --- 3. fázis: P2 hourly cap ---
    if priority == "P2" and base_decision.get("mode") == "normal":
        max_p2 = int(policy.get("reply", {}).get("max_replies_per_hour_p2", 2))
        if state.p2_replies_this_hour >= max_p2:
            return {"reply": False, "priority": "P2", "reason": "p2_hour_cap"}

    # Scheduler info hozzáadása a döntéshez
    base_decision["scheduler"] = {
        "reason": sched_decision.reason,
        "used_burst": sched_decision.used_burst,
        "burst_type": sched_decision.burst_type,
    }

    return base_decision
