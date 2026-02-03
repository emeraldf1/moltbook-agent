# Moltbook Agent

A cost-controlled, bilingual AI agent prototype for the Moltbook platform.

## Features

- **English-only outbound replies** - All responses to Moltbook are in English
- **Hungarian operator summaries** - Rule-based summaries for operators (no API cost)
- **Daily Pacer scheduler** - Prevents burning through daily API quota in the morning
- **Idempotency** - Never responds twice to the same event
- **Priority-based burst** - P0/P1 events can use burst quota when pacing kicks in

## Architecture

```
moltbook-agent/
├── agent_dryrun.py      # Main entry point (dry-run mode)
├── agent_shell.py       # Interactive CLI for control and inspection
├── moltagent/           # Core package
│   ├── config.py        # Constants and model settings
│   ├── state.py         # State persistence (daily counters, idempotency)
│   ├── policy.py        # Policy loading
│   ├── scheduler.py     # Daily Pacer (rate distribution)
│   ├── decision.py      # Reply decision logic
│   ├── reply.py         # OpenAI API calls
│   ├── hu_summary.py    # Hungarian summaries (rule-based)
│   └── utils.py         # Helper functions
├── events.jsonl         # Input events (mock Moltbook posts/comments)
└── policy.json          # Behavior rules, limits, style
```

## Quick Start

```bash
# Clone
git clone https://github.com/emeraldf1/moltbook-agent.git
cd moltbook-agent

# Setup
python -m venv venv
source venv/bin/activate
pip install openai python-dotenv

# Configure
echo "OPENAI_API_KEY=sk-..." > .env

# Run
python agent_dryrun.py
```

## Interactive Shell

```bash
python agent_shell.py
```

### Commands

| Command | Description |
|---------|-------------|
| `run` | Run dry-run processing |
| `status` | Show state, policy, scheduler info |
| `show <id>` | Show event by ID |
| `why <id>` | Show decision reason |
| `reply <id>` | Show English reply |
| `hu <id>` | Show Hungarian operator summary |
| `tail <log> [n]` | Tail log (events/decisions/outbound/operator) |
| `set scheduler on/off` | Enable/disable Daily Pacer |
| `set burst_p0 <n>` | Set P0 burst limit |
| `set burst_p1 <n>` | Set P1 burst limit |
| `set maxcalls <n>` | Set daily call limit |
| `clear logs` | Clear all logs |
| `clear state` | Reset state (counters, replied events) |

## Scheduler (Daily Pacer)

Distributes API calls evenly throughout the day:

```
earned_calls = (elapsed_today / 86400) * max_calls_per_day
```

| Situation | Result |
|-----------|--------|
| `calls_today < earned_calls` | Allowed |
| Over pace + P0 + burst available | Allowed (burst_p0) |
| Over pace + P1 + burst available | Allowed (burst_p1) |
| Over pace + P2 | Skip (scheduler_paced_wait) |
| Daily limit reached | Skip (scheduler_daily_calls_cap) |

## Idempotency

- Each replied `event_id` is stored in `agent_state.json`
- On subsequent runs, duplicate events are skipped with `reason: duplicate_event`
- Persists across restarts (not reset daily)

## Decision Priority

| Priority | Trigger | Example |
|----------|---------|---------|
| P0 | Mention or blocked keyword | `@agent help` or API key request |
| P1 | Relevant question | "How do I set rate limits?" |
| P2 | Relevant statement or off-topic redirect | General comments |

## Output Logs

| File | Content |
|------|---------|
| `logs/events.jsonl` | Input events |
| `logs/decisions.jsonl` | Decision reasons and scheduler info |
| `logs/replies_outbound_en.jsonl` | English replies (would go to Moltbook) |
| `logs/operator_view_hu.jsonl` | Hungarian operator summaries |

## Configuration (policy.json)

```json
{
  "max_calls_per_day": 200,
  "daily_budget_usd": 1.0,
  "scheduler": {
    "enabled": true,
    "burst_p0": 8,
    "burst_p1": 4
  },
  "style": {
    "language": "en",
    "max_sentences": 5
  }
}
```

## License

MIT
