"""
Konstansok és model konfiguráció.
"""
from __future__ import annotations

import os

# -------------------------
# MODEL CONFIG
# -------------------------
MODEL = "gpt-5-mini"
REASONING_EFFORT = "minimal"
MAX_OUTPUT_TOKENS = 350
TIMEOUT_SECONDS = 30

# -------------------------
# FILES
# -------------------------
STATE_FILE = "agent_state.json"
POLICY_FILE = "policy.json"
EVENTS_FILE = "events.jsonl"
LOG_DIR = "logs"

EVENT_LOG = os.path.join(LOG_DIR, "events.jsonl")
DECISION_LOG = os.path.join(LOG_DIR, "decisions.jsonl")
OUTBOUND_LOG = os.path.join(LOG_DIR, "replies_outbound_en.jsonl")
OPERATOR_LOG = os.path.join(LOG_DIR, "operator_view_hu.jsonl")

# -------------------------
# COST ESTIMATE (rough, for dry-run)
# -------------------------
CHARS_PER_TOKEN_EST = 4.0
USD_PER_1M_INPUT_TOKENS = 1.50
USD_PER_1M_OUTPUT_TOKENS = 6.00

# -------------------------
# SCHEDULER DEFAULTS
# -------------------------
DEFAULT_MAX_CALLS_PER_DAY = 200
DEFAULT_BURST_P0 = 8
DEFAULT_BURST_P1 = 4
DAY_SECONDS = 24 * 60 * 60  # 86400
