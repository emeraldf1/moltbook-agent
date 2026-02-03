"""
Magyar operator összefoglalók - szabályalapú, 0 API költség.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def hu_event_gist(event_text: str) -> str:
    """
    0 extra költség: HU kivonat a bejövő event szövegéről.
    Nem fordít szó szerint, csak témacímkéz + 1 mondat.
    """
    t = (event_text or "").strip()
    tl = t.lower()

    if any(k in tl for k in ["api key", "password", "secret", "token", "private key", "seed phrase"]):
        return "Bizalmas adatot kér (kulcs/jelszó) – ezt el kell utasítani."
    if "cap spending" in tl or "drain credits" in tl or "spending" in tl or "credits" in tl or "billing" in tl:
        return "Kérdés a költési limitről / napi keretről (credit budget)."
    if "rate limit" in tl or "rate limiting" in tl or ("python" in tl and "rate" in tl):
        return "Kérdés a híváskorlátozásról (rate limit), Python példával."
    if "agents" in tl and "moltbook" in tl:
        return "Általános kérdés: Moltbook ügynökök – mire jók, hogyan érdemes kezdeni."
    if "memory" in tl or "leak" in tl or "privacy" in tl or "pii" in tl:
        return "Kérdés az ügynök memóriájáról / adatvédelemről (ne szivárogjon adat)."
    if "favorite movie" in tl or "movie" in tl:
        return "Off-topic kérdés (kedvenc film) – udvarias visszaterelés kell."
    if t.endswith("?"):
        return "Általános kérdés – a bot valószínűleg rövid, praktikus választ ad."
    return "Általános bejegyzés/komment – relevancia alapján döntünk."


def summarize_en_to_hu_cheap(reply_en: str, event_text: str) -> str:
    """
    0 extra költség: magyar operator kivonat az EN válaszból, EVENT-SPECIFIKUSAN.
    Nem fordít szó szerint; 2-3 releváns HU pontot ad.
    """
    txt = (reply_en or "").strip().lower()
    et = (event_text or "").strip().lower()

    points = []

    # --- Candidate points (detectors) ---
    if any(k in txt for k in ["rate limit", "rate limiting", "requests per", "request/sec", "rps", "token-bucket", "fixed-window", "throttle"]):
        points.append("Állíts be híváskorlátot (rate limit), hogy ne tudjon túl gyorsan sok kérést küldeni.")

    if any(k in txt for k in ["daily budget", "spend cap", "cap spending", "daily spend", "budget"]):
        points.append("Adj meg napi költési keretet (daily budget/spend cap), és állítsd meg a futást a keret elérésekor.")

    if any(k in txt for k in ["permissions", "allowed", "disallowed", "policy", "rules", "guardrails"]):
        points.append("Rögzítsd egyértelműen, mit szabad és mit tilos csinálnia (szabályok + jogosultságok).")

    if any(k in txt for k in ["integration", "webhook", "api", "auth", "authentication"]):
        points.append("Az integrációknál kezeld külön a hitelesítést (API/auth), és tesztelj izolált környezetben.")

    if any(k in txt for k in ["audit", "logging", "log", "monitor", "monitoring", "trace", "observability"]):
        points.append("Legyen naplózás/monitorozás, hogy visszakövethető legyen: mi történt és miért.")

    if any(k in txt for k in ["verify", "check", "if unsure", "unknown", "not sure"]):
        points.append("Ha bizonytalan a platform mezőiben/feature-eiben, jelezze és javasoljon ellenőrzést a dokumentációban/UI-ban.")

    if any(k in txt for k in ["reject", "return a clear error", "clear error", "error"]):
        points.append("Keret túllépésnél utasítsa el a kérést és adjon egyértelmű hibát (ne próbálja újra végtelenül).")

    if any(k in txt for k in ["template", "templates", "starter", "minimal setup"]):
        points.append("Kezdésnek érdemes sablonokat készíteni: cél/feladat, hangnem, engedélyezett eszközök, teszt promptok.")

    # --- Event-specific prioritization ---
    # If off-topic movie question: keep only redirect-related points (or a single one)
    if "favorite movie" in et or ("movie" in et and "moltbook" not in et):
        return "Off-topic kérdés: udvarias visszaterelés a Moltbook ügynök témára (setup, szabályok, biztonság, költségkontroll)."

    # If secrets requested: focus on refusal & safe alternative
    if any(k in et for k in ["api key", "password", "secret", "token", "private key", "seed phrase"]):
        p = [
            "Bizalmas adatot/kulcsot nem adunk ki; rövid elutasítás.",
            "Adj biztonságos alternatívát: hogyan hozzon létre saját kulcsot + hogyan tárolja (env/.env, secret manager)."
        ]
        return " | ".join(p)

    # Spending/budget question: prefer budget + reject + monitoring, then rate limit
    if any(k in et for k in ["cap spending", "drain credits", "spending", "credits", "billing", "budget"]):
        ordered = []
        for key in [
            "Adj meg napi költési keretet",
            "Keret túllépésnél utasítsa el",
            "Legyen naplózás/monitorozás",
            "Állíts be híváskorlátot",
        ]:
            for p in points:
                if key in p and p not in ordered:
                    ordered.append(p)
        for p in points:
            if p not in ordered:
                ordered.append(p)
        if not ordered:
            return "Költségkontroll: napi keret + híváskorlát + túlköltésnél leállítás/hiba."
        return " | ".join(ordered[:3])

    # Python rate limit question
    if "python" in et and any(k in et for k in ["rate", "rate limit", "rate limiting"]):
        ordered = []
        for key in [
            "Állíts be híváskorlátot",
            "Kezdésnek érdemes sablonokat",
            "Legyen naplózás/monitorozás",
        ]:
            for p in points:
                if key in p and p not in ordered:
                    ordered.append(p)
        if not ordered:
            return "Python híváskorlát: egyszerű limiter (token bucket / fixed window) + naplózás."
        return " | ".join(ordered[:2])

    # Policy/template question
    if any(k in et for k in ["policy template", "template", "what to reply", "reply policy", "response template"]):
        ordered = []
        for key in [
            "Kezdésnek érdemes sablonokat készíteni",
            "Rögzítsd egyértelműen, mit szabad",
            "Legyen naplózás/monitorozás",
            "Adj meg napi költési keretet",
            "Állíts be híváskorlátot",
        ]:
            for p in points:
                if key in p and p not in ordered:
                    ordered.append(p)
        for p in points:
            if p not in ordered:
                ordered.append(p)
        if not ordered:
            return "Válasz-sablon/policy: engedélyezett témák + tiltott témák + hangnem + eszkaláció + költségkorlátok."
        return " | ".join(ordered[:3])

    # General Moltbook agents question
    if "moltbook" in et and "agents" in et:
        ordered = []
        for key in [
            "Kezdésnek érdemes sablonokat",
            "Rögzítsd egyértelműen, mit szabad",
            "Az integrációknál kezeld külön",
            "Állíts be híváskorlátot",
            "Adj meg napi költési keretet",
        ]:
            for p in points:
                if key in p and p not in ordered:
                    ordered.append(p)
        for p in points:
            if p not in ordered:
                ordered.append(p)
        if not ordered:
            return "Kezdés: sablonok + szabályok/jogosultságok + fokozatos tesztelés + költségkontroll."
        return " | ".join(ordered[:3])

    # Memory/privacy
    if any(k in et for k in ["memory", "privacy", "pii", "leak"]):
        ordered = []
        for key in [
            "Rögzítsd egyértelműen, mit szabad",
            "Legyen naplózás/monitorozás",
            "Ha bizonytalan a platform",
        ]:
            for p in points:
                if key in p and p not in ordered:
                    ordered.append(p)
        if not ordered:
            return "Adatvédelem: minimalizálás + szabályok/jogosultságok + naplózás."
        return " | ".join(ordered[:3])

    # Fallback
    if not points:
        first = (reply_en or "").strip().splitlines()[0] if reply_en else ""
        if len(first) > 160:
            first = first[:157] + "..."
        return f"Lényeg: rövid technikai válasz. (EN alapján: {first})"

    return " | ".join(points[:3])


def hu_operator_summary(
    event: Dict[str, Any],
    decision: Dict[str, Any],
    reply_en: Optional[str],
) -> str:
    """
    Teljes magyar operator összefoglaló generálása.
    """
    etype = event.get("type")
    author = event.get("author")
    text = (event.get("text") or "").strip()

    reason = decision.get("reason")
    prio = decision.get("priority")
    did = decision.get("reply")

    snippet = text if len(text) <= 120 else text[:117] + "..."

    lines = []
    lines.append(f"Esemény: {etype} / {author}")
    lines.append(f"Tartalom (röviden): {snippet}")
    lines.append(f"Esemény lényege (HU): {hu_event_gist(text)}")
    lines.append(f"Döntés: {'VÁLASZ' if did else 'SKIP'} | Prioritás: {prio} | Ok: {reason}")

    # Idempotencia: duplicate event jelzése
    if reason == "duplicate_event":
        orig_id = decision.get("original_event_id", event.get("id"))
        lines.append(f"Idempotencia: már válaszoltunk erre az eseményre ({orig_id})")

    # Scheduler info ha van
    sched = decision.get("scheduler")
    if sched:
        if sched.get("wait_seconds"):
            lines.append(f"Scheduler: várakozás {sched['wait_seconds']:.1f}s (dry-run: nem alszunk)")
        elif sched.get("used_burst"):
            lines.append(f"Scheduler: burst használva ({sched.get('burst_type', '?')})")
        elif sched.get("reason"):
            lines.append(f"Scheduler: {sched['reason']}")

    if reply_en:
        gist_hu = summarize_en_to_hu_cheap(reply_en, text)
        lines.append(f"Válasz lényege (HU): {gist_hu}")

    return "\n".join(lines)
