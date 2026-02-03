from __future__ import annotations

import json
import os
import sys
import subprocess
from datetime import datetime
from typing import Any, Dict, Optional, List

LOG_DIR = "logs"
EVENTS_FILE = "events.jsonl"
POLICY_FILE = "policy.json"
STATE_FILE = "agent_state.json"

# logs created by agent_dryrun.py
EVENT_LOG = os.path.join(LOG_DIR, "events.jsonl")
DECISION_LOG = os.path.join(LOG_DIR, "decisions.jsonl")
OUTBOUND_LOG = os.path.join(LOG_DIR, "replies_outbound_en.jsonl")
OPERATOR_LOG = os.path.join(LOG_DIR, "operator_view_hu.jsonl")


def _exists(path: str) -> bool:
    return os.path.exists(path)


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not _exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    # keep going if a line is broken
                    continue
    return rows


def _tail_jsonl(path: str, n: int = 10) -> List[Dict[str, Any]]:
    rows = _read_jsonl(path)
    return rows[-n:]


def _find_in_jsonl(path: str, key: str, value: str) -> Optional[Dict[str, Any]]:
    rows = _read_jsonl(path)
    for r in rows:
        if str(r.get(key, "")) == value:
            return r
    return None


def _print_card(title: str, body: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("-" * 80)
    print(body.rstrip())
    print("=" * 80 + "\n")


def _print_help() -> None:
    help_text = """
Parancsok:

  help
    - súgó

  status
    - megmutatja: state + policy gyors infó + scheduler állapot + log fájlok

  run
    - lefuttatja a dry-run feldolgozást (python agent_dryrun.py)
    - scheduler be/ki: set scheduler on|off

  show <event_id>
    - megmutatja az esemény (events.jsonl) sorát

  why <event_id>
    - megmutatja, mi volt a döntés oka (decisions.jsonl)

  reply <event_id>
    - megmutatja, mit válaszolt volna/írt (replies_outbound_en.jsonl)

  hu <event_id>
    - megmutatja a magyar operator összefoglalót (operator_view_hu.jsonl)

  tail <log> [n]
    - log utolsó n sora (alap: 5)
    - log lehet: events | decisions | outbound | operator

  clear logs
    - törli a logs/ alatti jsonl logokat

  clear state
    - törli az agent_state.json-t (napi counters reset)

  show policy
    - kiírja a policy.json teljes tartalmát

  edit policy
    - megnyitja a policy.json-t a default editorral (VS Code: code policy.json ha van)

  set budget <usd>
    - beállítja a daily_budget_usd értéket (pl. set budget 1.0)

  set maxcalls <n>
    - beállítja a max_calls_per_day értéket (pl. set maxcalls 200)

  set p2hour <n>
    - beállítja a reply.max_replies_per_hour_p2 értéket (pl. set p2hour 2)

  set minsec <seconds>
    - beállítja a min_seconds_between_calls értéket (pl. set minsec 8)

  set lang <en|hu>
    - beállítja a style.language mezőt (nálunk maradjon: en)

  set maxsent <n>
    - beállítja a style.max_sentences értéket

  set format <bullets|plain>
    - beállítja a style.format értéket

  set scheduler <on|off>
    - bekapcsolja/kikapcsolja a Daily Pacer-t

  set burst_p0 <n>
    - P0 prioritáshoz napi burst limit (pl. set burst_p0 8)

  set burst_p1 <n>
    - P1 prioritáshoz napi burst limit (pl. set burst_p1 4)

  edit events
    - megnyitja az events.jsonl-t

  exit / quit
    - kilépés
"""
    _print_card("agent_shell.py - help", help_text)


def _load_state() -> Dict[str, Any]:
    if not _exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_policy() -> Dict[str, Any]:
    if not _exists(POLICY_FILE):
        return {}
    try:
        with open(POLICY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_policy(pol: Dict[str, Any]) -> None:
    with open(POLICY_FILE, "w", encoding="utf-8") as f:
        json.dump(pol, f, ensure_ascii=False, indent=2)


def _ensure_policy() -> Dict[str, Any]:
    pol = _load_policy()
    if not pol:
        pol = {}

    # Ensure basic structure exists
    pol.setdefault("daily_budget_usd", 1.0)
    pol.setdefault("max_calls_per_day", 200)
    pol.setdefault("min_seconds_between_calls", 8)

    pol.setdefault("reply", {})
    pol["reply"].setdefault("max_replies_per_hour_p2", 2)
    pol["reply"].setdefault("offtopic_question_mode", "redirect")

    pol.setdefault("style", {})
    pol["style"].setdefault("language", "en")
    pol["style"].setdefault("max_sentences", 4)
    pol["style"].setdefault("format", "bullets")

    pol.setdefault("domain", {})
    pol["domain"].setdefault("context", "")

    # Scheduler (Daily Pacer) defaults
    pol.setdefault("scheduler", {})
    pol["scheduler"].setdefault("enabled", True)
    pol["scheduler"].setdefault("burst_p0", 8)
    pol["scheduler"].setdefault("burst_p1", 4)

    return pol


def _show_policy() -> None:
    pol = _ensure_policy()
    _print_card("POLICY (policy.json)", json.dumps(pol, ensure_ascii=False, indent=2))


def _set_policy_field(field: str, value: str) -> None:
    pol = _ensure_policy()

    def as_int(v: str) -> int:
        return int(float(v))

    def as_float(v: str) -> float:
        return float(v)

    field = field.lower().strip()

    # Map shell fields to policy.json structure
    if field in ("budget", "daily_budget", "daily_budget_usd"):
        pol["daily_budget_usd"] = as_float(value)

    elif field in ("maxcalls", "max_calls", "max_calls_per_day"):
        pol["max_calls_per_day"] = as_int(value)

    elif field in ("p2hour", "max_replies_per_hour_p2"):
        pol.setdefault("reply", {})
        pol["reply"]["max_replies_per_hour_p2"] = as_int(value)

    elif field in ("minsec", "min_seconds_between_calls"):
        pol["min_seconds_between_calls"] = as_int(value)

    elif field in ("lang", "language"):
        pol.setdefault("style", {})
        pol["style"]["language"] = value.strip().lower()

    elif field in ("maxsent", "max_sentences"):
        pol.setdefault("style", {})
        pol["style"]["max_sentences"] = as_int(value)

    elif field in ("format",):
        pol.setdefault("style", {})
        pol["style"]["format"] = value.strip().lower()

    # Scheduler fields
    elif field in ("scheduler",):
        pol.setdefault("scheduler", {})
        val_lower = value.strip().lower()
        if val_lower in ("on", "true", "1", "yes"):
            pol["scheduler"]["enabled"] = True
        elif val_lower in ("off", "false", "0", "no"):
            pol["scheduler"]["enabled"] = False
        else:
            _print_card("ERROR", "Usage: set scheduler <on|off>")
            return

    elif field in ("burst_p0", "burst0"):
        pol.setdefault("scheduler", {})
        pol["scheduler"]["burst_p0"] = as_int(value)

    elif field in ("burst_p1", "burst1"):
        pol.setdefault("scheduler", {})
        pol["scheduler"]["burst_p1"] = as_int(value)

    else:
        _print_card("ERROR", f"Unknown policy field: {field}\nTry: budget | maxcalls | p2hour | minsec | lang | maxsent | format | scheduler | burst_p0 | burst_p1")
        return

    _save_policy(pol)
    _print_card("OK", f"Updated policy: {field} = {value}\nSaved to {POLICY_FILE}")

def _status() -> None:
    st = _load_state()
    pol = _load_policy()

    lines = []
    lines.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"State file: {'OK' if _exists(STATE_FILE) else 'missing'}")
    if st:
        lines.append(f"  day_key={st.get('day_key')} calls_today={st.get('calls_today')} spent_usd={st.get('spent_usd')}")
        lines.append(f"  hour_key={st.get('hour_key')} p2_replies_this_hour={st.get('p2_replies_this_hour')}")
        # Scheduler burst counters
        burst_p0_used = st.get('burst_used_p0', 0)
        burst_p1_used = st.get('burst_used_p1', 0)
        lines.append(f"  burst_used: p0={burst_p0_used} p1={burst_p1_used}")
        # Idempotencia: megválaszolt események száma
        replied_count = len(st.get('replied_event_ids', []))
        lines.append(f"  replied_events: {replied_count}")
    else:
        lines.append("  (no state loaded)")

    lines.append("")
    lines.append(f"Policy file: {'OK' if _exists(POLICY_FILE) else 'missing'}")
    if pol:
        lines.append(f"  daily_budget_usd={pol.get('daily_budget_usd')} max_calls_per_day={pol.get('max_calls_per_day')} min_seconds_between_calls={pol.get('min_seconds_between_calls')}")
        style = pol.get("style", {})
        lines.append(f"  outbound language={style.get('language')} max_sentences={style.get('max_sentences')} format={style.get('format')}")
        dom = (pol.get("domain", {}) or {}).get("context", "")
        lines.append(f"  domain_context={'set' if dom else 'missing'}")
        rep = pol.get("reply", {})
        lines.append(f"  offtopic_question_mode={rep.get('offtopic_question_mode')} max_replies_per_hour_p2={rep.get('max_replies_per_hour_p2')}")
        # Scheduler config
        sched = pol.get("scheduler", {})
        sched_enabled = sched.get("enabled", True)
        burst_p0_max = sched.get("burst_p0", 8)
        burst_p1_max = sched.get("burst_p1", 4)
        lines.append(f"  scheduler: enabled={sched_enabled} burst_p0={burst_p0_max} burst_p1={burst_p1_max}")
    else:
        lines.append("  (no policy loaded)")

    lines.append("")
    lines.append("Files:")
    for p in [EVENTS_FILE, POLICY_FILE, STATE_FILE, EVENT_LOG, DECISION_LOG, OUTBOUND_LOG, OPERATOR_LOG]:
        lines.append(f"  {p}: {'OK' if _exists(p) else 'missing'}")
    _print_card("STATUS", "\n".join(lines))


def _run_dryrun() -> None:
    script = "agent_dryrun.py"

    if not _exists(script):
        _print_card("ERROR", f"{script} not found in current folder.")
        return

    _print_card("RUN", f"Running: python {script}\n(Use 'tail operator 5' to see the HU operator output log afterwards.)")
    try:
        subprocess.run([sys.executable, script], check=False)
    except Exception as e:
        _print_card("ERROR", f"Failed to run {script}: {e}")


def _show_event(event_id: str) -> None:
    row = _find_in_jsonl(EVENTS_FILE, "id", event_id)
    if not row:
        _print_card("NOT FOUND", f"No event with id={event_id} in {EVENTS_FILE}")
        return
    _print_card(f"EVENT {event_id}", json.dumps(row, ensure_ascii=False, indent=2))


def _why(event_id: str) -> None:
    row = _find_in_jsonl(DECISION_LOG, "event_id", event_id)
    if not row:
        _print_card("NOT FOUND", f"No decision for event_id={event_id} in {DECISION_LOG}")
        return
    dec = row.get("decision", {})
    body = json.dumps(dec, ensure_ascii=False, indent=2)
    _print_card(f"WHY {event_id}", body)


def _reply(event_id: str) -> None:
    row = _find_in_jsonl(OUTBOUND_LOG, "event_id", event_id)
    if not row:
        _print_card("NOT FOUND", f"No outbound reply for event_id={event_id} in {OUTBOUND_LOG}")
        return
    reply_en = row.get("reply_en", "")
    usage = row.get("usage", {})
    est = row.get("est_usd")
    body = f"{reply_en}\n\nusage={usage} est_usd={est}"
    _print_card(f"REPLY (EN) {event_id}", body)


def _hu(event_id: str) -> None:
    row = _find_in_jsonl(OPERATOR_LOG, "event_id", event_id)
    if not row:
        _print_card("NOT FOUND", f"No operator view for event_id={event_id} in {OPERATOR_LOG}")
        return
    body = row.get("operator_summary_hu", "")
    _print_card(f"OPERATOR (HU) {event_id}", body)


def _tail(which: str, n: int) -> None:
    mapping = {
        "events": EVENT_LOG,
        "decisions": DECISION_LOG,
        "outbound": OUTBOUND_LOG,
        "operator": OPERATOR_LOG,
    }
    path = mapping.get(which)
    if not path:
        _print_card("ERROR", "Unknown log. Use: events | decisions | outbound | operator")
        return
    rows = _tail_jsonl(path, n)
    if not rows:
        _print_card("EMPTY", f"No rows in {path} (or missing).")
        return
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    _print_card(f"TAIL {which} {n}", body)


def _clear_logs() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    deleted = []
    for p in [EVENT_LOG, DECISION_LOG, OUTBOUND_LOG, OPERATOR_LOG]:
        if _exists(p):
            os.remove(p)
            deleted.append(p)
    _print_card("CLEAR LOGS", "Deleted:\n" + ("\n".join(deleted) if deleted else "(nothing to delete)"))


def _clear_state() -> None:
    if _exists(STATE_FILE):
        os.remove(STATE_FILE)
        _print_card("CLEAR STATE", f"Deleted {STATE_FILE}")
    else:
        _print_card("CLEAR STATE", f"{STATE_FILE} not found")


def _edit_file(path: str) -> None:
    # Prefer VS Code if available
    if shutil_which("code"):
        subprocess.run(["code", path], check=False)
        return
    # fallback to nano
    subprocess.run(["nano", path], check=False)


def shutil_which(cmd: str) -> Optional[str]:
    # minimal which replacement (avoid importing shutil)
    for p in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(p, cmd)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def repl() -> None:
    _print_card("agent_shell", "Készen áll.\nÍrd be: help")

    while True:
        try:
            raw = input("agent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()

        if cmd in ("exit", "quit"):
            print("bye")
            break

        if cmd == "help":
            _print_help()
            continue

        if cmd == "status":
            _status()
            continue

        if cmd == "run":
            _run_dryrun()
            continue

        if cmd == "why" and len(parts) >= 2:
            _why(parts[1])
            continue

        if cmd == "reply" and len(parts) >= 2:
            _reply(parts[1])
            continue

        if cmd == "hu" and len(parts) >= 2:
            _hu(parts[1])
            continue

        if cmd == "tail":
            if len(parts) < 2:
                _print_card("ERROR", "Usage: tail <events|decisions|outbound|operator> [n]")
                continue
            which = parts[1].lower()
            n = 5
            if len(parts) >= 3:
                try:
                    n = int(parts[2])
                except ValueError:
                    n = 5
            _tail(which, n)
            continue

        if cmd == "show":
            if len(parts) < 2:
                _print_card("ERROR", "Usage: show <event_id> | show policy")
                continue
            if parts[1].lower() == "policy":
                _show_policy()
                continue
            _show_event(parts[1])
            continue
                
        if cmd == "set":
            if len(parts) < 3:
                _print_card("ERROR", "Usage: set <field> <value>\nExamples: set budget 1.0 | set maxcalls 200 | set p2hour 2")
                continue
            field = parts[1]
            value = parts[2]
            _set_policy_field(field, value)
            continue

        if cmd == "clear" and len(parts) >= 2:
            what = parts[1].lower()
            if what == "logs":
                _clear_logs()
                continue
            if what == "state":
                _clear_state()
                continue

        if cmd == "edit" and len(parts) >= 2:
            what = parts[1].lower()
            if what == "policy":
                if not _exists(POLICY_FILE):
                    _print_card("ERROR", f"{POLICY_FILE} not found")
                else:
                    _edit_file(POLICY_FILE)
                continue
            if what == "events":
                if not _exists(EVENTS_FILE):
                    _print_card("ERROR", f"{EVENTS_FILE} not found")
                else:
                    _edit_file(EVENTS_FILE)
                continue

        _print_card("UNKNOWN COMMAND", f"'{raw}'\nÍrd be: help")


if __name__ == "__main__":
    repl()