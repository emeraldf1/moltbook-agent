"""
Agent állapot: State dataclass + perzisztencia.

Crash recovery támogatással:
- Atomi írás (temp file + rename)
- fsync() a lemezre íráshoz
- Korrupt state kezelés
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from .config import STATE_FILE, LOG_DIR
from .utils import day_key_local, hour_key_local


@dataclass
class State:
    """Agent állapot, napi és órás számlálókkal + scheduler burst + idempotencia."""

    day_key: str
    spent_usd: float = 0.0
    calls_today: int = 0
    last_call_ts: float = 0.0
    p2_replies_this_hour: int = 0
    hour_key: str = ""

    # Scheduler burst counters (napi reset)
    burst_used_p0: int = 0
    burst_used_p1: int = 0

    # Idempotencia: megválaszolt event_id-k (NEM resetelődik naponta)
    replied_event_ids: Set[str] = field(default_factory=set)

    def __post_init__(self):
        if not self.hour_key:
            self.hour_key = hour_key_local()

    def has_replied(self, event_id: str) -> bool:
        """Ellenőrzi, hogy az event_id már meg lett-e válaszolva."""
        return event_id in self.replied_event_ids

    def mark_replied(self, event_id: str) -> None:
        """Megjelöli az event_id-t megválaszoltként."""
        self.replied_event_ids.add(event_id)


def _log_state_error(error_type: str, message: str, backup_path: Optional[str] = None) -> None:
    """Logol egy state hibát az errors.jsonl-be."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        error_log = os.path.join(LOG_DIR, "errors.jsonl")
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "error_type": error_type,
            "message": message,
            "backup_path": backup_path,
        }
        with open(error_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # Ha a logolás nem sikerül, ne álljon le


def load_state(state_file: str = STATE_FILE) -> State:
    """
    Betölti az állapotot fájlból, vagy újat hoz létre.

    Crash recovery:
    - Korrupt JSON → backup + fresh state + log
    - Hiányzó fájl → fresh state
    """
    today = day_key_local()
    hour = hour_key_local()

    if not os.path.exists(state_file):
        return State(day_key=today, hour_key=hour)

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
    except json.JSONDecodeError as e:
        # Korrupt JSON - backup + fresh state
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = f"{state_file}.corrupt.{timestamp}"
        try:
            os.rename(state_file, backup_path)
            _log_state_error(
                "state_corrupt",
                f"Korrupt state fájl: {e}. Backup: {backup_path}",
                backup_path,
            )
        except Exception:
            pass
        return State(day_key=today, hour_key=hour)
    except Exception:
        return State(day_key=today, hour_key=hour)

    # replied_event_ids NEM resetelődik naponta
    replied_ids = set(data.get("replied_event_ids", []))

    # Ha új nap van, reseteljük a napi számlálókat (de replied_event_ids marad!)
    if data.get("day_key") != today:
        return State(
            day_key=today,
            spent_usd=0.0,
            calls_today=0,
            last_call_ts=float(data.get("last_call_ts", 0.0)),
            p2_replies_this_hour=0,
            hour_key=hour,
            burst_used_p0=0,
            burst_used_p1=0,
            replied_event_ids=replied_ids,
        )

    st = State(
        day_key=today,
        spent_usd=float(data.get("spent_usd", 0.0)),
        calls_today=int(data.get("calls_today", 0) or 0),
        last_call_ts=float(data.get("last_call_ts", 0.0)),
        p2_replies_this_hour=int(data.get("p2_replies_this_hour", 0) or 0),
        hour_key=str(data.get("hour_key", hour)),
        burst_used_p0=int(data.get("burst_used_p0", 0) or 0),
        burst_used_p1=int(data.get("burst_used_p1", 0) or 0),
        replied_event_ids=replied_ids,
    )

    # Reset hourly cap if hour changed
    if st.hour_key != hour:
        st.hour_key = hour
        st.p2_replies_this_hour = 0

    return st


def save_state(st: State, state_file: str = STATE_FILE) -> None:
    """
    Elmenti az állapotot fájlba atomikusan.

    Crash recovery:
    - Temp fájlba ír, majd atomi rename
    - fsync() biztosítja a lemezre írást
    - Ha a rename sikertelen, a régi state megmarad
    """
    data = {
        "day_key": st.day_key,
        "spent_usd": st.spent_usd,
        "calls_today": st.calls_today,
        "last_call_ts": st.last_call_ts,
        "p2_replies_this_hour": st.p2_replies_this_hour,
        "hour_key": st.hour_key,
        "burst_used_p0": st.burst_used_p0,
        "burst_used_p1": st.burst_used_p1,
        "replied_event_ids": sorted(st.replied_event_ids),
    }

    # Atomi írás: temp file + rename
    temp_file = state_file + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk

        # Atomi rename (POSIX-on garantáltan atomi)
        os.replace(temp_file, state_file)

    except Exception:
        # Ha bármi hiba, próbáljuk törölni a temp fájlt
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except Exception:
            pass
        raise


def ensure_today(st: State) -> State:
    """Ellenőrzi, hogy a state a mai napra vonatkozik-e, és resetel ha kell."""
    today = day_key_local()
    hour = hour_key_local()

    if st.day_key != today:
        st.day_key = today
        st.spent_usd = 0.0
        st.calls_today = 0
        st.burst_used_p0 = 0
        st.burst_used_p1 = 0

    if st.hour_key != hour:
        st.hour_key = hour
        st.p2_replies_this_hour = 0

    save_state(st)
    return st
