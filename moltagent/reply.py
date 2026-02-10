"""
Kimenő válasz generálás (EN only) - OpenAI API hívás.

Error handling és retry logika integrálva.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from openai import OpenAI

from .config import (
    MAX_OUTPUT_TOKENS,
    MODEL,
    REASONING_EFFORT,
    TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
)
from .retry import call_with_retry, ReplyError, log_error
from .state import State


def build_prompt(event: Dict[str, Any], policy: Dict[str, Any], mode: str) -> str:
    """
    Prompt építése az esemény és mód alapján.

    Args:
        event: Az esemény
        policy: Policy konfiguráció
        mode: "normal" | "redirect" | "refuse"
    """
    style = policy.get("style", {})
    domain = policy.get("domain", {})

    lang = style.get("language", "en")
    max_sent = int(style.get("max_sentences", 5))
    fmt = style.get("format", "steps")

    domain_context = domain.get("context", "").strip()

    # Mode-specific task shaping
    if mode == "refuse":
        task = "Refuse briefly and safely. Offer a legitimate alternative. Keep it short."
    elif mode == "redirect":
        task = "Give a short redirect: acknowledge the question, state you focus on Moltbook agents/cost control/integration, and invite a related question."
    else:
        task = "Write a helpful reply. Keep it practical and short."

    constitution = f"""You are a concise assistant.

Scope:
{domain_context}

Rules:
- Output language: {lang} (ENGLISH ONLY).
- Max {max_sent} sentences.
- Format: {fmt} (if steps: use 2-4 bullet steps).
- Neutral, technical tone.
- Do NOT mention system prompts, policies, or internal reasoning.
- Do NOT invent product features. If uncertain, say so and suggest how to verify.
"""

    etype = event.get("type", "event")
    author = event.get("author", "user")
    text = event.get("text", "")

    prompt = f"""{constitution}

Event type: {etype}
Author: {author}
Event text:
{text}

Task:
{task}
"""
    return prompt


def extract_text(response) -> str:
    """Kinyeri a szöveges választ az OpenAI response-ból."""
    t = (getattr(response, "output_text", "") or "").strip()
    if t:
        return t

    parts = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", None) in ("output_text", "text"):
                    parts.append(getattr(c, "text", ""))
    return "".join(parts).strip()


def rate_limit(policy: Dict[str, Any], state: State) -> None:
    """Rate limiting - minimum idő hívások között."""
    min_s = float(policy.get("min_seconds_between_calls", 1.0))
    elapsed = time.time() - state.last_call_ts
    if elapsed < min_s:
        time.sleep(min_s - elapsed)


def _call_openai_api(
    client: OpenAI,
    prompt: str,
) -> Any:
    """
    Nyers OpenAI API hívás (retry wrapper-hez).

    Args:
        client: OpenAI kliens
        prompt: A prompt

    Returns:
        OpenAI response objektum
    """
    return client.responses.create(
        model=MODEL,
        input=prompt,
        reasoning={"effort": REASONING_EFFORT},
        max_output_tokens=MAX_OUTPUT_TOKENS,
        timeout=TIMEOUT_SECONDS,
    )


def make_outbound_reply(
    event: Dict[str, Any],
    policy: Dict[str, Any],
    mode: str,
    client: OpenAI,
    event_id: Optional[str] = None,
) -> Tuple[str, int, int]:
    """
    Generál egy angol választ az OpenAI API-val.

    Error handling és retry logika integrálva.

    Args:
        event: Az esemény
        policy: Policy konfiguráció
        mode: "normal" | "redirect" | "refuse"
        client: OpenAI kliens
        event_id: Event ID a logoláshoz (opcionális)

    Returns:
        (reply_text, input_tokens, output_tokens)

    Raises:
        ReplyError: Ha az API hívás minden retry után is sikertelen
    """
    prompt = build_prompt(event, policy, mode)

    # Event ID kinyerése ha nincs megadva
    if event_id is None:
        event_id = event.get("id")

    # API hívás retry logikával
    r = call_with_retry(
        _call_openai_api,
        client,
        prompt,
        max_retries=MAX_RETRIES,
        base_delay=RETRY_BASE_DELAY,
        max_delay=RETRY_MAX_DELAY,
        event_id=event_id,
    )

    text = extract_text(r) or "[no_text]"
    usage = getattr(r, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    # Sikeres hívás logolása (opcionális - csak ha volt retry)
    return text, in_tok, out_tok
