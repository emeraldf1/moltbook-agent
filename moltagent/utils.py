"""
Segédfüggvények: idő, JSON, stb.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

# -------------------------
# TIMEZONE (Budapest-ish fixed offset)
# -------------------------
TZ_HOURS = 1  # set to 2 in summer if you want manual DST
TZ = timezone(timedelta(hours=TZ_HOURS))


def now_local() -> datetime:
    """Aktuális idő a beállított időzónában."""
    return datetime.now(tz=TZ)


def day_key_local() -> str:
    """Mai nap kulcsa: YYYY-MM-DD."""
    return now_local().strftime("%Y-%m-%d")


def hour_key_local() -> str:
    """Aktuális óra kulcsa: YYYY-MM-DD-HH."""
    return now_local().strftime("%Y-%m-%d-%H")


def seconds_since_midnight() -> float:
    """Eltelt másodpercek éjfél óta (helyi időzóna)."""
    now = now_local()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (now - midnight).total_seconds()


def ensure_dirs(log_dir: str) -> None:
    """Létrehozza a log könyvtárat, ha nem létezik."""
    os.makedirs(log_dir, exist_ok=True)


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    """JSONL fájlhoz hozzáfűz egy sort."""
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def estimate_tokens(text: str, chars_per_token: float = 4.0) -> int:
    """Becsült tokenszám karakterek alapján."""
    return int(max(1, len(text) / chars_per_token))


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    usd_per_1m_input: float = 1.50,
    usd_per_1m_output: float = 6.00,
) -> float:
    """Becsült költség USD-ben."""
    return (input_tokens / 1_000_000.0) * usd_per_1m_input + (
        output_tokens / 1_000_000.0
    ) * usd_per_1m_output
