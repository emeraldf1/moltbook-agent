"""
Kimenő válasz generálás (EN only) - OpenAI API hívás.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from openai import OpenAI

from .config import MAX_OUTPUT_TOKENS, MODEL, REASONING_EFFORT, TIMEOUT_SECONDS
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


def make_outbound_reply(
    event: Dict[str, Any],
    policy: Dict[str, Any],
    mode: str,
    client: OpenAI,
) -> Tuple[str, int, int]:
    """
    Generál egy angol választ az OpenAI API-val.

    Returns:
        (reply_text, input_tokens, output_tokens)
    """
    prompt = build_prompt(event, policy, mode)

    r = client.responses.create(
        model=MODEL,
        input=prompt,
        reasoning={"effort": REASONING_EFFORT},
        max_output_tokens=MAX_OUTPUT_TOKENS,
        timeout=TIMEOUT_SECONDS,
    )

    text = extract_text(r) or "[no_text]"
    usage = getattr(r, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

    return text, in_tok, out_tok
