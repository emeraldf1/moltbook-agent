# Moltbook Agent – Development Roadmap

## Cél

A jelenlegi SPEC.md alapján egy javasolt fejlesztési roadmap, mérföldkövekkel és „Definition of Done"-nal.

---

## Fázis 0 – Biztonsági alapok ✅ KÉSZ

**Miért:** public repo → kulcs-szivárgás kockázat.

**Feladatok:**
- [x] `.gitignore` beállítása (`.env`, `logs/`, `agent_state.json`, `*.db`)
- [x] Nincs secret a working tree-ben
- [x] Nincs secret a git history-ban

**DoD:** `git grep -n "sk-" -- .` és `git log -p -S "sk-" --all` üres.

---

## Fázis 1 – SPEC 1–13 teljes megfelelés (Core hardening)

**Státusz:** ✅ KÉSZ

### 1.1 Budget hard cap implementálása ✅ KÉSZ

**SPEC 7 követelmény:** `daily_budget_usd` és `max_calls_per_day` ellenőrzés

**Feladatok:**
- [x] `decision.py`: Budget ellenőrzés hozzáadása a scheduler elé (`_check_budget()` függvény)
- [x] Új reason kódok: `budget_exhausted`, `daily_calls_cap`
- [x] Teszt: 12 új unit teszt a `TestBudgetHardCap` osztályban
- [x] HU összefoglaló: budget info megjelenítése
- [x] OpenAI gpt-4o validálta a specifikációt
- [x] OpenAI gpt-4o tesztelte az implementációt

**Befejezve:** 2025-02-04

**DoD:** ✅ `logs/decisions.jsonl`-ben megjelenik `budget_exhausted` reason.

### 1.2 Pipeline sorrend javítása ✅ KÉSZ

**SPEC 4 követelmény:** priority → dedup → budget → scheduler → relevance

**Feladatok:**
- [x] `decision.py`: Sorrend átrendezése
  1. Duplikáció ellenőrzés ✅
  2. Priority meghatározása ✅
  3. **Budget ellenőrzés** ✅ (fázis 1.5)
  4. Scheduler ellenőrzés ✅
  5. P2 hourly cap ✅

**Befejezve:** 2025-02-04 (a budget hard cap részeként)

**DoD:** ✅ Kód review + teszt a helyes sorrenddel.

### 1.3 Policy validáció ✅ KÉSZ

**SPEC 13 követelmény:** Érvénytelen policy esetén az agent nem indul vagy safe defaults

**Feladatok:**
- [x] Pydantic model definiálása (`moltagent/policy_model.py`)
- [x] `policy.py`: Validáció induláskor (`load_policy(validate=True)`)
- [x] Hibás policy → explicit error, agent nem indul
- [x] Tényleges policy értékek logolása console-ra
- [x] Fix szabályok kikényszerítése (EN out, HU op)
- [x] 26 unit teszt PASS
- [x] OpenAI o3 validálta az implementációt (9/9 AC PASS)

**Befejezve:** 2025-02-05

**DoD:** ✅ Hibás `policy.json` esetén az agent nem indul el.

### 1.4 Soft cap (80%) ✅ KÉSZ

**SPEC 7b követelmény:** 80% budget felett csak P0/P1 engedélyezett

**Feladatok:**
- [x] `decision.py`: `_check_soft_cap()` függvény
- [x] Pipeline integráció: hard cap után, scheduler előtt
- [x] Új reason kód: `soft_cap_p2_blocked`
- [x] 11 új teszt PASS (145 összesen)
- [x] OpenAI validálta (7/7 AC PASS)

**Befejezve:** 2025-02-10

**DoD:** ✅ P2 események SKIP-elődnek 80% felett.

---

## Fázis 2 – SPEC 14 implementáció (State lifecycle)

**Státusz:** ✅ KÉSZ (2.1 + 2.2)

### 2.1 Clear parancsok a shellben ✅ KÉSZ

**SPEC 14 követelmény:** Külön parancsok az állapot törléséhez

**Feladatok:**
- [x] `clear counters` - csak napi/órás számlálók törlése
  - `calls_today`, `spent_usd`, `burst_used_p0`, `burst_used_p1`, `p2_replies_this_hour`
  - Nem érinti a `replied_event_ids` listát
- [x] `clear dedup` - feldolgozott event_id-k törlése
  - Megerősítés kérése: "Biztosan törlöd a dedup listát? (yes/no)"
- [x] `clear all` - minden állapot törlése
  - Dupla megerősítés: "FIGYELEM: Ez törli az összes állapotot! Írd be: CONFIRM"
- [x] `clear state` deprecated, figyelmeztetéssel
- [x] OpenAI o3 validálta az implementációt (9/9 AC PASS)

**Befejezve:** 2025-02-05

**DoD:** ✅ Shell parancsok működnek, megerősítések aktívak.

### 2.2 Restart viselkedés validálása ✅ KÉSZ

**Feladatok:**
- [x] Teszt: restart után a számlálók nem nullázódnak
- [x] Teszt: restart nem használható rate limit megkerülésére
- [x] Teszt: dedup lista megmarad restart után
- [x] Teszt: többszöri restart is konzisztens
- [x] Dokumentáció: restart viselkedés leírása (SPEC_EXT.md #4)

**Befejezve:** 2025-02-05

**Tesztek:** 6 új unit teszt (`tests/test_state.py::TestRestartBehavior`)

**DoD:** ✅ Tesztek PASS + dokumentált.

---

## Fázis 3 – Error handling & recovery

**Státusz:** ✅ KÉSZ (3.1 + 3.2)

### 3.1 API hiba kezelés ✅ KÉSZ

**Feladatok:**
- [x] OpenAI API hiba → retry (max 3x, exponential backoff)
- [x] Rate limit (429) → várakozás + retry (retry-after header)
- [x] Timeout → graceful fail, SKIP az eseményre
- [x] Hiba logolás: `logs/errors.jsonl`
- [x] Új modul: `moltagent/retry.py`
- [x] 21 új teszt PASS
- [x] OpenAI validálta (6/6 AC PASS)

**Befejezve:** 2025-02-05

**DoD:** ✅ API hibák kezelve, retry logika működik.

### 3.2 Crash recovery ✅ KÉSZ

**Feladatok:**
- [x] State atomicitás: JSON írás atomi (temp file + rename + fsync)
- [x] Korrupt state kezelés: backup + fresh state + error log
- [x] at-most-once garancia: mark_replied csak sikeres API hívás után
- [x] 8 új teszt PASS (összesen 134 teszt)
- [x] OpenAI validálta (6/6 AC PASS)

**Befejezve:** 2025-02-05

**DoD:** ✅ Hiba-szimulációk mellett is determinisztikus döntések és biztonságos leállás.

---

## Fázis 4 – Moltbook adapter ✅ KÉSZ

**Státusz:** ✅ KÉSZ

### 4.1 Adapter interface ✅

**Feladatok:**
- [x] `adapters/base.py`: Abstract adapter interface
  - `fetch_events() -> List[Event]`
  - `send_reply(event_id, reply_text)`
- [x] `adapters/mock.py`: JSONL-alapú működés teszteléshez
- [x] `adapters/moltbook.py`: Valódi Moltbook API integráció

### 4.2 Konfiguráció ✅

**Feladatok:**
- [x] `policy.json`: `adapter` mező (`mock` | `moltbook`)
- [x] Környezeti változók: `MOLTBOOK_API_KEY`, `MOLTBOOK_AGENT_NAME`, `MOLTBOOK_DRY_RUN`
- [x] CLI: `--adapter` és `--live` flags

### 4.3 Biztonság ✅

- [x] Dry-run alapértelmezett (nem küld semmit)
- [x] `--live` flag szükséges az éles küldéshez
- [x] Moltbook rate limit tisztelet (20s/comment, 50/day)
- [x] 28 új teszt PASS

**Befejezve:** 2025-02-10

**DoD:** ✅ `python agent_dryrun.py --adapter moltbook` működik.

---

## Fázis 5 – Hardening & Ops

**Státusz:** ✅ KÉSZ

### 5.1 Audit tooling ✅ KÉSZ

**Feladatok:**
- [x] `tools/spec_audit.py`: Automatikus SPEC compliance ellenőrzés
  - 14 SPEC pont ellenőrzése
  - Dedup proof (két futás szimuláció)
  - Budget cap teszt
  - PASS/FAIL per SPEC pont
- [x] OpenAI validálta (5/5 AC PASS)

**Befejezve:** 2025-02-10

**DoD:** ✅ `python -m tools.spec_audit` → 14/14 PASS

### 5.2 CI integráció ✅ KÉSZ

**Feladatok:**
- [x] GitHub Actions workflow (`.github/workflows/ci.yml`)
- [x] `requirements.txt` létrehozása
- [x] Push/PR triggerre fut: tesztek + SPEC audit

**Befejezve:** 2025-02-10

**DoD:** ✅ `git push` → automatikus CI futás

### 5.3 Monitoring & Alerting ✅ KÉSZ

**Feladatok:**
- [x] `moltagent/monitoring.py` modul
- [x] Napi költés összesítő log (`logs/daily_summary.jsonl`)
- [x] Budget warning 80%, 90%, 95%, 100%-nál
- [x] Hiba rate monitoring (10% threshold)
- [x] Per-cycle stats (`logs/monitoring.jsonl`)
- [x] Shell status parancs budget indikátorral

**Befejezve:** 2025-02-10

**DoD:** ✅ Daemon logol monitoring adatokat, budget warning működik

### 5.4 Dokumentáció ✅ KÉSZ

**Feladatok:**
- [x] `README.md` teljes frissítés (architektúra, adapters, monitoring)
- [x] `ROADMAP.md` aktualizálás
- [x] `deploy/README_DEPLOY.md` telepítési útmutató
- [x] `OPERATOR_GUIDE.md` operátori kézikönyv

**Befejezve:** 2025-02-10

**DoD:** ✅ Teljes dokumentáció a projekthez

---

## Összefoglaló táblázat

| Fázis | Leírás | Státusz |
|-------|--------|---------|
| 0 | Biztonsági alapok | ✅ KÉSZ |
| 1.1 | Budget hard cap | ✅ KÉSZ (2025-02-04) |
| 1.2 | Pipeline sorrend | ✅ KÉSZ (2025-02-04) |
| 1.3 | Policy validáció | ✅ KÉSZ (2025-02-05) |
| 1.4 | Soft cap (80%) | ✅ KÉSZ (2025-02-10) |
| 2.1 | Clear parancsok | ✅ KÉSZ (2025-02-05) |
| 2.2 | Restart validálás | ✅ KÉSZ (2025-02-05) |
| 3.1 | API error handling | ✅ KÉSZ (2025-02-05) |
| 3.2 | Crash recovery | ✅ KÉSZ (2025-02-05) |
| 4 | Moltbook adapter | ✅ KÉSZ (2025-02-10) |
| 5.1 | SPEC Audit Tool | ✅ KÉSZ (2025-02-10) |
| 5.2 | CI integráció | ✅ KÉSZ (2025-02-10) |
| 5.3 | Monitoring | ✅ KÉSZ (2025-02-10) |
| 5.4 | Dokumentáció | ✅ KÉSZ (2025-02-10) |

---

## 🎉 PROJEKT KÉSZ!

Minden fázis teljesítve:
- ✅ 173 teszt PASS
- ✅ 14/14 SPEC audit PASS
- ✅ Moltbook API integráció
- ✅ VPS deployment csomag
- ✅ Monitoring és alerting
- ✅ Teljes dokumentáció
