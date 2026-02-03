"""
moltagent - Moltbook Agent csomag

Modulok:
- config: Konstansok és beállítások
- utils: Segédfüggvények
- state: Agent állapot kezelés
- policy: Policy betöltés
- scheduler: Daily Pacer (napi hívás-elosztás)
- decision: Döntési logika
- reply: OpenAI válasz generálás
- hu_summary: Magyar összefoglalók (szabályalapú)
"""
from __future__ import annotations

from .config import (
    MODEL,
    STATE_FILE,
    POLICY_FILE,
    LOG_DIR,
    EVENT_LOG,
    DECISION_LOG,
    OUTBOUND_LOG,
    OPERATOR_LOG,
)
from .state import State, load_state, save_state, ensure_today
from .policy import load_policy, get_scheduler_config
from .scheduler import scheduler_check, SchedulerDecision, update_burst_counters
from .decision import should_reply
from .reply import make_outbound_reply, build_prompt, rate_limit
from .hu_summary import hu_event_gist, summarize_en_to_hu_cheap, hu_operator_summary
from .utils import (
    now_local,
    day_key_local,
    hour_key_local,
    ensure_dirs,
    append_jsonl,
    estimate_tokens,
    estimate_cost_usd,
)

__all__ = [
    # config
    "MODEL",
    "STATE_FILE",
    "POLICY_FILE",
    "LOG_DIR",
    "EVENT_LOG",
    "DECISION_LOG",
    "OUTBOUND_LOG",
    "OPERATOR_LOG",
    # state
    "State",
    "load_state",
    "save_state",
    "ensure_today",
    # policy
    "load_policy",
    "get_scheduler_config",
    # scheduler
    "scheduler_check",
    "SchedulerDecision",
    "update_burst_counters",
    # decision
    "should_reply",
    # reply
    "make_outbound_reply",
    "build_prompt",
    "rate_limit",
    # hu_summary
    "hu_event_gist",
    "summarize_en_to_hu_cheap",
    "hu_operator_summary",
    # utils
    "now_local",
    "day_key_local",
    "hour_key_local",
    "ensure_dirs",
    "append_jsonl",
    "estimate_tokens",
    "estimate_cost_usd",
]
