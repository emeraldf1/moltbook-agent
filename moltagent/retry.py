"""
Retry logika OpenAI API hívásokhoz.

SPEC - Error handling:
- Exponential backoff retry
- Rate limit (429) kezelés
- Timeout kezelés
- Error logging
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    RateLimitError,
)

from .config import LOG_DIR


# --- Config ---

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_JITTER = 0.1  # 10% jitter

# Retryable exceptions
RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
)

# Error log file
ERROR_LOG = os.path.join(LOG_DIR, "errors.jsonl")


# --- Custom exceptions ---

@dataclass
class ReplyError(Exception):
    """
    Wrapper exception az API hibákhoz.

    Használat:
        try:
            reply = make_outbound_reply(...)
        except ReplyError as e:
            print(f"Reply failed: {e.error_type}: {e.message}")
    """
    error_type: str
    message: str
    event_id: Optional[str] = None
    retry_count: int = 0
    original_exception: Optional[Exception] = None

    def __str__(self) -> str:
        return f"{self.error_type}: {self.message}"


# --- Error logging ---

def log_error(
    event_id: Optional[str],
    error_type: str,
    message: str,
    retry_count: int = 0,
    resolved: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Logol egy hibát az errors.jsonl fájlba.

    Args:
        event_id: Az esemény ID-ja (ha van)
        error_type: A hiba típusa (pl. "RateLimitError")
        message: Hibaüzenet
        retry_count: Hányszor próbálkoztunk
        resolved: Sikerült-e végül
        extra: Extra adatok
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "error_type": error_type,
        "message": message,
        "retry_count": retry_count,
        "resolved": resolved,
    }
    if extra:
        entry["extra"] = extra

    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # Ha a logolás nem sikerül, ne álljon le az agent
        pass


# --- Retry helpers ---

def calculate_delay(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    jitter: float = DEFAULT_JITTER,
) -> float:
    """
    Kiszámítja a várakozási időt exponential backoff-fal.

    Args:
        attempt: Hányadik próbálkozás (0-indexed)
        base_delay: Alap várakozási idő
        max_delay: Maximális várakozási idő
        jitter: Véletlenszerű eltérés (0.1 = 10%)

    Returns:
        Várakozási idő másodpercben
    """
    import random

    delay = base_delay * (2 ** attempt)
    delay = min(delay, max_delay)

    # Jitter hozzáadása
    jitter_amount = delay * jitter
    delay += random.uniform(-jitter_amount, jitter_amount)

    return max(0, delay)


def get_retry_after(exception: Exception) -> Optional[float]:
    """
    Kinyeri a retry-after értéket a RateLimitError-ból (ha van).

    Args:
        exception: A kivétel

    Returns:
        Várakozási idő másodpercben, vagy None
    """
    if isinstance(exception, RateLimitError):
        # OpenAI RateLimitError-nak lehet retry_after attribútuma
        retry_after = getattr(exception, "retry_after", None)
        if retry_after is not None:
            try:
                return float(retry_after)
            except (ValueError, TypeError):
                pass

        # Próbáljuk a headers-ből kinyerni
        response = getattr(exception, "response", None)
        if response:
            headers = getattr(response, "headers", {})
            retry_header = headers.get("retry-after") or headers.get("Retry-After")
            if retry_header:
                try:
                    return float(retry_header)
                except ValueError:
                    pass

    return None


# --- Main retry function ---

def call_with_retry(
    func: Callable[..., Any],
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    event_id: Optional[str] = None,
    **kwargs,
) -> Any:
    """
    Meghív egy függvényt retry logikával.

    Args:
        func: A meghívandó függvény
        *args: Pozícionális argumentumok
        max_retries: Maximum retry szám
        base_delay: Alap várakozási idő
        max_delay: Maximális várakozási idő
        event_id: Event ID a logoláshoz
        **kwargs: Keyword argumentumok

    Returns:
        A függvény visszatérési értéke

    Raises:
        ReplyError: Ha minden retry sikertelen
    """
    last_exception: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)

        except RETRYABLE_EXCEPTIONS as e:
            last_exception = e
            error_type = type(e).__name__

            # Logoljuk a hibát
            log_error(
                event_id=event_id,
                error_type=error_type,
                message=str(e),
                retry_count=attempt,
                resolved=False,
            )

            # Ha ez volt az utolsó próbálkozás, ne várjunk
            if attempt >= max_retries:
                break

            # Várakozási idő meghatározása
            retry_after = get_retry_after(e)
            if retry_after is not None:
                delay = min(retry_after, max_delay)
            else:
                delay = calculate_delay(attempt, base_delay, max_delay)

            # Logoljuk a retry-t
            print(f"[retry] {error_type} - attempt {attempt + 1}/{max_retries + 1}, waiting {delay:.1f}s")

            time.sleep(delay)

        except APIError as e:
            # Nem retryable API hiba (pl. 400 Bad Request, 401 Unauthorized)
            error_type = type(e).__name__
            log_error(
                event_id=event_id,
                error_type=error_type,
                message=str(e),
                retry_count=attempt,
                resolved=False,
                extra={"status_code": getattr(e, "status_code", None)},
            )
            raise ReplyError(
                error_type=error_type,
                message=str(e),
                event_id=event_id,
                retry_count=attempt,
                original_exception=e,
            )

        except Exception as e:
            # Váratlan hiba
            error_type = type(e).__name__
            log_error(
                event_id=event_id,
                error_type=error_type,
                message=str(e),
                retry_count=attempt,
                resolved=False,
            )
            raise ReplyError(
                error_type=error_type,
                message=str(e),
                event_id=event_id,
                retry_count=attempt,
                original_exception=e,
            )

    # Minden retry sikertelen
    if last_exception:
        error_type = type(last_exception).__name__
        raise ReplyError(
            error_type=error_type,
            message=f"All {max_retries + 1} attempts failed: {last_exception}",
            event_id=event_id,
            retry_count=max_retries,
            original_exception=last_exception,
        )

    # Ez nem szabadna megtörténjen
    raise ReplyError(
        error_type="UnknownError",
        message="Retry logic failed unexpectedly",
        event_id=event_id,
        retry_count=max_retries,
    )


# --- Decorator verzió ---

def retry_on_error(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> Callable:
    """
    Decorator retry logikával.

    Használat:
        @retry_on_error(max_retries=3)
        def my_api_call():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # event_id kinyerése ha van
            event_id = kwargs.pop("_event_id", None)
            return call_with_retry(
                func,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                event_id=event_id,
                **kwargs,
            )
        return wrapper
    return decorator
