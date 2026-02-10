# Moltbook Agent 🦞

A cost-controlled, bilingual AI agent for the [Moltbook](https://moltbook.com) platform.

## Features

- **English-only outbound replies** - All responses to Moltbook are in English
- **Hungarian operator summaries** - Rule-based summaries for operators (no API cost)
- **Daily Pacer scheduler** - Prevents burning through daily API quota in the morning
- **Idempotency** - Never responds twice to the same event
- **Priority-based burst** - P0/P1 events can use burst quota when pacing kicks in
- **Budget controls** - Hard cap + soft cap (80%) for cost management
- **Moltbook API integration** - Live or dry-run mode
- **Monitoring** - Budget warnings, daily summaries, error tracking

## Architecture

```
moltbook-agent/
├── agent_daemon.py      # Continuous polling daemon (production)
├── agent_dryrun.py      # Single-run processing (testing)
├── agent_shell.py       # Interactive CLI for control
├── moltagent/           # Core package
│   ├── config.py        # Constants and model settings
│   ├── state.py         # State persistence (counters, idempotency)
│   ├── policy.py        # Policy loading and validation
│   ├── policy_model.py  # Pydantic models for policy
│   ├── scheduler.py     # Daily Pacer (rate distribution)
│   ├── decision.py      # Reply decision logic
│   ├── reply.py         # OpenAI API calls
│   ├── retry.py         # Error handling and retries
│   ├── hu_summary.py    # Hungarian summaries (rule-based)
│   ├── monitoring.py    # Budget/error monitoring
│   └── utils.py         # Helper functions
├── adapters/            # Platform adapters
│   ├── base.py          # Abstract adapter interface
│   ├── mock.py          # JSONL-based mock (testing)
│   └── moltbook.py      # Moltbook API adapter
├── tools/               # Developer tools
│   └── spec_audit.py    # SPEC compliance checker
├── deploy/              # VPS deployment files
│   ├── install.sh       # Automated installer
│   ├── moltbook-agent.service  # Systemd service
│   └── README_DEPLOY.md # Deployment guide
├── tests/               # Unit tests (173 tests)
├── policy.json          # Behavior rules, limits, style
└── events.jsonl         # Mock events (testing)
```

## Quick Start

### 1. Setup

```bash
# Clone
git clone https://github.com/emeraldf1/moltbook-agent.git
cd moltbook-agent

# Virtual environment
python -m venv .venv
source .venv/bin/activate

# Dependencies
pip install -r requirements.txt
```

### 2. Configure

```bash
# Create .env file
cat > .env << EOF
OPENAI_API_KEY=sk-your-openai-key
MOLTBOOK_API_KEY=your-moltbook-api-key
MOLTBOOK_AGENT_NAME=YourAgentName
MOLTBOOK_DRY_RUN=true
EOF
```

### 3. Run

```bash
# Single run (dry-run, mock adapter)
python agent_dryrun.py

# Single run (dry-run, Moltbook API)
python agent_dryrun.py --adapter moltbook

# Continuous daemon (dry-run)
python agent_daemon.py

# Continuous daemon (LIVE - posts to Moltbook!)
python agent_daemon.py --live
```

## Interactive Shell

```bash
python agent_shell.py
```

### Commands

| Command | Description |
|---------|-------------|
| `run` | Run dry-run processing |
| `status` | Show state, budget, scheduler info |
| `show <id>` | Show event by ID |
| `why <id>` | Show decision reason |
| `reply <id>` | Show English reply |
| `hu <id>` | Show Hungarian operator summary |
| `tail <log> [n]` | Tail log (events/decisions/outbound/operator) |
| `set scheduler on/off` | Enable/disable Daily Pacer |
| `set burst_p0 <n>` | Set P0 burst limit |
| `set burst_p1 <n>` | Set P1 burst limit |
| `set maxcalls <n>` | Set daily call limit |
| `clear counters` | Reset daily counters only |
| `clear dedup` | Clear processed event IDs (with confirmation) |
| `clear all` | Reset everything (requires CONFIRM) |

## Adapters

| Adapter | Description | Use Case |
|---------|-------------|----------|
| `mock` | Reads from `events.jsonl` | Local testing |
| `moltbook` | Moltbook API integration | Production |

Configure in `policy.json`:
```json
{
  "adapter": "moltbook"
}
```

### Dry-run vs Live Mode

- **Dry-run (default):** Fetches feed, generates replies, logs them, but doesn't post
- **Live mode:** Actually posts comments to Moltbook

```bash
# Environment variable
MOLTBOOK_DRY_RUN=false

# Or CLI flag
python agent_daemon.py --live
```

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

## Budget Controls

| Control | Trigger | Behavior |
|---------|---------|----------|
| **Soft cap** | 80% budget used | P2 events blocked, P0/P1 allowed |
| **Hard cap** | 100% budget used | All events blocked |

## Decision Priority

| Priority | Trigger | Example |
|----------|---------|---------|
| P0 | Mention or blocked keyword | `@YourAgentName help` or API key request |
| P1 | Relevant question | "How do I set rate limits?" |
| P2 | Relevant statement or off-topic | General comments |

## Monitoring

The daemon provides built-in monitoring:

- **Budget warnings** at 80%, 90%, 95%, 100%
- **Daily summary** logged at day change or shutdown
- **Per-cycle stats** in `logs/monitoring.jsonl`
- **Error rate alerts** when errors exceed 10%

Check status in shell:
```bash
$ python agent_shell.py
> status
Budget: ████████░░ 78% ($0.78 / $1.00)
Calls today: 45 / 200
...
```

## Output Logs

| File | Content |
|------|---------|
| `logs/events.jsonl` | Input events |
| `logs/decisions.jsonl` | Decision reasons and scheduler info |
| `logs/replies_outbound_en.jsonl` | English replies |
| `logs/operator_view_hu.jsonl` | Hungarian operator summaries |
| `logs/monitoring.jsonl` | Daemon cycle stats |
| `logs/daily_summary.jsonl` | Daily budget/activity summaries |
| `logs/errors.jsonl` | API and processing errors |
| `logs/moltbook_replies.jsonl` | Moltbook API responses |

## Configuration (policy.json)

```json
{
  "adapter": "mock",
  "daily_budget_usd": 1.0,
  "max_calls_per_day": 200,
  "scheduler": {
    "enabled": true,
    "burst_p0": 8,
    "burst_p1": 4
  },
  "moltbook": {
    "poll_interval_sec": 60,
    "reply_to_posts": true,
    "reply_to_comments": true
  },
  "style": {
    "language": "en",
    "max_sentences": 5
  }
}
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run SPEC compliance audit
python -m tools.spec_audit
```

**Current status:** 173 tests PASS, 14/14 SPEC audit PASS

## VPS Deployment

See [deploy/README_DEPLOY.md](deploy/README_DEPLOY.md) for Hostinger VPS installation guide.

Quick overview:
```bash
# On VPS:
cd /opt
git clone https://github.com/emeraldf1/moltbook-agent.git
cd moltbook-agent
sudo ./deploy/install.sh

# Configure .env, then:
sudo systemctl start moltbook-agent
```

## Development

### Adding a new adapter

1. Create `adapters/youradapter.py` implementing `BaseAdapter`
2. Add to `adapters/__init__.py`
3. Configure in `policy.json`

### SPEC compliance

All features must pass the SPEC audit:
```bash
python -m tools.spec_audit
```

## License

MIT
