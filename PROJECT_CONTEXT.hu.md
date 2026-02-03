# Moltbook Agent (helyi prototípus) — Projekt Kontextus (HU)

## Cél
Egy helyben futó, biztonságos és költség-korlátos “agent” prototípus építése, amit később Moltbookhoz lehet kötni.
Most még offline szimulálunk, és kétféle kimenetet készítünk:
- **EN outbound** válasz (ez menne Moltbook felé élesben)
- **HU operator összefoglaló** (neked, mint operátornak), extra API költség nélkül

## Fő fájlok
- `agent_dryrun.py` — offline esemény-szimulátor + döntéshozó + logolás
- `agent_shell.py` — interaktív CLI “kezelőpult” a futtatáshoz és ellenőrzéshez
- `events.jsonl` — bemeneti (mock) Moltbook események, soronként 1 JSON
- `policy.json` — viselkedési szabályok + budget/rate limit + stílus
- `agent_state.json` — perzisztált számlálók (hívásszám, becsült költés, órás cap)
- `logs/*.jsonl` — a dry-run kimeneti logok

## Mit csinál az `agent_dryrun.py`?
1. Beolvassa az eseményeket az `events.jsonl`-ből
2. Beolvassa a szabályokat a `policy.json`-ból
3. Betölti a számlálókat az `agent_state.json`-ból
4. Minden eseményre dönt: **VÁLASZ** vagy **SKIP**, okkal
5. Ha válaszol:
   - generál egy **angol kimenő** választ (EN-only)
   - költséget/tokeneket becsül, és frissíti a számlálókat
6. Logol több JSONL fájlba:
   - `logs/events.jsonl`
   - `logs/decisions.jsonl`
   - `logs/replies_outbound_en.jsonl`
   - `logs/operator_view_hu.jsonl` (magyar operator nézet, LLM nélkül)

## Magyar operator nézet logika
- `hu_event_gist(text)` → magyar “esemény lényege” 1 mondatban
- `summarize_en_to_hu_cheap(reply_en, event_text)` → event-specifikus magyar “válasz lényege”
Mindkettő szabály-alapú (nem hív modellt).

## Mit csinál az `agent_shell.py`?
Parancsokat ad a futtatáshoz és a logok gyors nézéséhez:
- `run`, `status`, `tail operator 5`, `show e1`, `why e1`, `reply e1`, `hu e1`, `clear logs`, `clear state`, `edit policy`, `edit events`

## Megjegyzések
- A logok JSONL-ek és általában hozzáfűznek; tiszta futáshoz `clear logs`.
- A Moltbook felé kimenet mindig angol (EN), az operator összefoglaló magyar (HU).