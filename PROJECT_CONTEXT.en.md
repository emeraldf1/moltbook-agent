# Moltbook Agent (Local Prototype) — Project Context (EN)

## Goal
Build a local, safe, budget-controlled prototype of an “agent” that can later be connected to Moltbook.
Right now we simulate Moltbook events offline and generate:
- English outbound replies (what would be sent to Moltbook)
- Hungarian operator summaries (for the human operator) at near-zero cost

## Key Files
- `agent_dryrun.py` — offline event simulator + decision engine + logging
- `agent_shell.py` — interactive CLI wrapper to run dry-run and inspect logs
- `events.jsonl` — input stream of mock Moltbook events (one JSON object per line)
- `policy.json` — behavior policy + budgeting/rate limits + style rules
- `agent_state.json` — persisted counters (calls, estimated spend, hourly caps)
- `logs/*.jsonl` — output logs produced by the dry-run

## How `agent_dryrun.py` Works
1. Loads events from `events.jsonl`
2. Loads rules from `policy.json`
3. Loads persisted counters from `agent_state.json`
4. For each event, decides: REPLY or SKIP with a reason
5. If REPLY:
   - generates an **English outbound** reply (EN-only)
   - estimates cost/tokens and updates counters
6. Writes logs:
   - `logs/events.jsonl`
   - `logs/decisions.jsonl`
   - `logs/replies_outbound_en.jsonl`
   - `logs/operator_view_hu.jsonl` (Hungarian operator view, LLM-free)

## Operator View (HU) Logic
- `hu_event_gist(text)` creates a 1-sentence Hungarian gist of the incoming event.
- `summarize_en_to_hu_cheap(reply_en, event_text)` creates an event-specific Hungarian gist of the outbound English reply.
Both are rule-based (no extra API calls).

## How `agent_shell.py` Helps
Provides commands:
- `run`, `status`, `tail operator 5`, `show e1`, `why e1`, `reply e1`, `hu e1`, `clear logs`, `clear state`, `edit policy`, `edit events`

## Notes
- Logs are JSONL and typically append; use `clear logs` for clean runs.
- Outbound must remain English (for Moltbook). Operator summaries remain Hungarian.