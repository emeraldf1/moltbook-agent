# SPEC_EXT – Bővített Specifikáció

Ez a dokumentum a SPEC.md kiegészítése, amely részletes technikai specifikációt tartalmaz minden fejlesztési feladathoz.

---

## Fejlesztés #1: Budget Hard Cap

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ (2025-02-04)
**SPEC hivatkozás:** SPEC.md §7 Költségkontroll
**ROADMAP hivatkozás:** Fázis 1.1

---

### 1. Áttekintés

#### 1.1 Probléma
A jelenlegi implementációban a `daily_budget_usd` és `max_calls_per_day` limitek nincsenek ellenőrizve a döntési logikában. Ez azt jelenti, hogy az agent túllépheti a költségkeretet, ami biztonsági és üzleti kockázatot jelent.

#### 1.2 Megoldás
Budget ellenőrzés bevezetése a `decision.py` modulban, a scheduler ellenőrzés ELŐTT.

#### 1.3 Hatókör
- **Érintett fájlok:** `moltagent/decision.py`
- **Érintett függvények:** `should_reply()`
- **Új reason kódok:** `budget_exhausted`, `daily_calls_cap`

---

### 2. Részletes specifikáció

#### 2.1 Budget ellenőrzés helye a pipeline-ban

**SPEC §4 szerinti sorrend:**
1. Esemény beolvasása
2. **Prioritás meghatározása** ← jelenlegi 1. fázis
3. Duplikáció ellenőrzés ← jelenlegi 0. fázis
4. **Költségellenőrzés** ← ÚJ! (SPEC §7)
5. Scheduler ellenőrzés ← jelenlegi 2. fázis
6. Relevancia ellenőrzés
7. P2 hourly cap ← jelenlegi 3. fázis

**Döntés:** A SPEC sorrendjét követjük. A budget ellenőrzés a prioritás meghatározása ÉS duplikáció ellenőrzés UTÁN, de a scheduler ELŐTT történik.

#### 2.2 Budget ellenőrzés szabályai

```python
# Псевдокód
def budget_check(state: State, policy: Dict) -> Optional[SkipDecision]:
    daily_budget = policy.get("daily_budget_usd", 1.0)
    max_calls = policy.get("max_calls_per_day", 200)

    # 1. USD limit ellenőrzés
    if state.spent_usd >= daily_budget:
        return SKIP(reason="budget_exhausted")

    # 2. Hívásszám limit ellenőrzés
    if state.calls_today >= max_calls:
        return SKIP(reason="daily_calls_cap")

    return None  # OK, folytatható
```

#### 2.3 Visszatérési érték budget limit esetén

```json
{
    "reply": false,
    "priority": "<eredeti priority>",
    "reason": "budget_exhausted" | "daily_calls_cap",
    "budget": {
        "spent_usd": 0.85,
        "daily_budget_usd": 1.0,
        "calls_today": 195,
        "max_calls_per_day": 200
    }
}
```

#### 2.4 Prioritás megtartása

Fontos: A budget ellenőrzés a prioritás meghatározása UTÁN fut, tehát a visszatérési értékben meg kell őrizni az eredeti prioritást (P0/P1/P2). Ez fontos az operátor számára, hogy lássa: milyen prioritású esemény lett elutasítva budget limit miatt.

#### 2.5 Megjegyzés a scheduler `daily_calls_cap`-ről

A scheduler jelenleg már ellenőrzi a `max_calls_per_day` limitet (`scheduler_daily_calls_cap` reason). Azonban:
- A budget ellenőrzést a scheduler ELŐTT kell végrehajtani
- A `daily_calls_cap` reason a decision.py-ból jön (nem a scheduler-ből)
- A scheduler `scheduler_daily_calls_cap` reason-ja redundánssá válik, de megtartjuk backward compatibility miatt

---

### 3. Implementációs terv

#### 3.1 Módosítandó kód: `moltagent/decision.py`

```python
def should_reply(...) -> Dict[str, Any]:
    state = ensure_today(state)

    # --- 0. fázis: Idempotencia ellenőrzés ---
    # (változatlan)

    # --- 1. fázis: Prioritás meghatározása ---
    # (változatlan, de a base_decision-t előbb kell meghatározni)

    # --- 1.5 fázis: Budget ellenőrzés (ÚJ!) ---
    budget_skip = _check_budget(state, policy, priority)
    if budget_skip:
        return budget_skip

    # --- 2. fázis: Scheduler ellenőrzés ---
    # (változatlan)

    # --- 3. fázis: P2 hourly cap ---
    # (változatlan)
```

#### 3.2 Új függvény: `_check_budget()`

```python
def _check_budget(
    state: State,
    policy: Dict[str, Any],
    priority: str,
) -> Optional[Dict[str, Any]]:
    """
    Ellenőrzi a napi költségkeretet és hívásszám limitet.

    Returns:
        None ha OK, egyébként SKIP döntés dict.
    """
    daily_budget = float(policy.get("daily_budget_usd", 1.0))
    max_calls = int(policy.get("max_calls_per_day", 200))

    budget_info = {
        "spent_usd": state.spent_usd,
        "daily_budget_usd": daily_budget,
        "calls_today": state.calls_today,
        "max_calls_per_day": max_calls,
    }

    # USD limit
    if state.spent_usd >= daily_budget:
        return {
            "reply": False,
            "priority": priority,
            "reason": "budget_exhausted",
            "budget": budget_info,
        }

    # Hívásszám limit
    if state.calls_today >= max_calls:
        return {
            "reply": False,
            "priority": priority,
            "reason": "daily_calls_cap",
            "budget": budget_info,
        }

    return None
```

---

### 4. Acceptance Criteria

#### AC-1: Budget exhausted SKIP
- **Given:** `spent_usd >= daily_budget_usd` a policy-ben
- **When:** Egy esemény feldolgozásra kerül
- **Then:**
  - `reply: false`
  - `reason: "budget_exhausted"`
  - A döntés logolva van a `decisions.jsonl`-ben
  - Az eseményre NEM történik API hívás

#### AC-2: Daily calls cap SKIP
- **Given:** `calls_today >= max_calls_per_day` a policy-ben
- **When:** Egy esemény feldolgozásra kerül
- **Then:**
  - `reply: false`
  - `reason: "daily_calls_cap"`
  - A döntés logolva van

#### AC-3: Budget info a döntésben
- **Given:** Budget limit miatt SKIP
- **When:** A döntés visszatér
- **Then:** A `budget` mező tartalmazza:
  - `spent_usd`
  - `daily_budget_usd`
  - `calls_today`
  - `max_calls_per_day`

#### AC-4: Prioritás megőrzése
- **Given:** Egy P0 esemény (pl. mention)
- **When:** Budget limit miatt SKIP
- **Then:** `priority: "P0"` a döntésben (nem P2!)

#### AC-5: Pipeline sorrend
- **Given:** Egy duplicate event + budget exhausted
- **When:** Az esemény feldolgozásra kerül
- **Then:** `reason: "duplicate_event"` (mert az idempotencia előbb fut)

#### AC-6: Budget ellenőrzés a scheduler előtt
- **Given:** Budget OK, de scheduler paced_wait
- **When:** Az esemény feldolgozásra kerül
- **Then:** `reason: "scheduler_paced_wait"` (nem budget-related)

#### AC-7: Magyar operátor összefoglaló
- **Given:** Budget limit miatt SKIP
- **When:** Operátor összefoglaló generálódik
- **Then:** A HU összefoglaló tartalmazza: "Budget limit elérve" vagy hasonló

---

### 5. Teszt terv

#### 5.1 Unit tesztek (`tests/test_decision.py`)

```python
def test_budget_exhausted_skip():
    """Budget elérve → SKIP budget_exhausted"""

def test_daily_calls_cap_skip():
    """Max hívásszám elérve → SKIP daily_calls_cap"""

def test_budget_priority_preserved():
    """P0 esemény budget SKIP-nél is P0 marad"""

def test_dedup_before_budget():
    """Duplicate event előbb fut mint budget check"""

def test_budget_before_scheduler():
    """Budget check előbb fut mint scheduler"""
```

#### 5.2 Integrációs teszt

1. Állíts `daily_budget_usd: 0.001` és `max_calls_per_day: 1`
2. Futtass `python agent_dryrun.py`
3. Ellenőrizd: első esemény REPLY, többi SKIP (`budget_exhausted` vagy `daily_calls_cap`)

---

### 6. Rollback terv

Ha a változtatás problémát okoz:
1. `git revert <commit>` a budget check commit-ra
2. Vagy: kommenteld ki a `_check_budget()` hívást a `should_reply()`-ban

---

### 7. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-04 | 1.0 | Kezdeti specifikáció |
| 2025-02-04 | 1.1 | Implementáció kész, OpenAI validálta |

---

## Fejlesztés #2: Clear parancsok (State lifecycle)

**Verzió:** 1.1
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** SPEC.md §14 Állapotkezelés (State lifecycle)
**ROADMAP hivatkozás:** Fázis 2.1

---

### 1. Áttekintés

#### 1.1 Probléma
A jelenlegi `agent_shell.py`-ban csak `clear state` parancs van, ami MINDENT töröl (számlálók + dedup lista). A SPEC §14.5 szerint külön parancsok kellenek:
- `clear counters` - csak számlálók
- `clear dedup` - csak dedup lista (megerősítéssel)
- `clear all` - minden (dupla megerősítéssel)

#### 1.2 Megoldás
Három új parancs implementálása az `agent_shell.py`-ban, megfelelő megerősítési logikával.

#### 1.3 Hatókör
- **Érintett fájlok:** `agent_shell.py`
- **Új parancsok:** `clear counters`, `clear dedup`, `clear all`
- **Meglévő parancs:** `clear state` → deprecated vagy eltávolítva

---

### 2. Részletes specifikáció

#### 2.1 Clear parancsok definíciója

##### `clear counters`
Törli a napi és órás számlálókat, DE megtartja a dedup listát.

**Törlendő/resetelt mezők:**
- `calls_today` → 0
- `spent_usd` → 0.0
- `burst_used_p0` → 0
- `burst_used_p1` → 0
- `p2_replies_this_hour` → 0
- `last_call_ts` → 0.0
- `day_key` → aktuális nap (frissül)
- `hour_key` → aktuális óra (frissül)

**NEM törlendő:**
- `replied_event_ids` (dedup lista)

**Megerősítés:** Nem szükséges (alacsony kockázat)

##### `clear dedup`
Törli a feldolgozott event_id-k listáját.

**Törlendő mezők:**
- `replied_event_ids` → üres set

**NEM törlendő:**
- Számlálók (calls_today, spent_usd, stb.)

**Megerősítés:** SZÜKSÉGES
```
FIGYELEM: Ez törli a dedup listát! Az agent újra válaszolhat korábban megválaszolt eseményekre.
Biztosan folytatod? (yes/no):
```

##### `clear all`
Törli az összes állapotot (számlálók + dedup).

**Törlendő mezők:**
- Minden számláló
- `replied_event_ids`

**Megerősítés:** DUPLA MEGERŐSÍTÉS
```
FIGYELEM: Ez törli az ÖSSZES állapotot (számlálók + dedup lista)!
Ez nem visszavonható művelet.
Első megerősítés - Írd be: yes
> yes
Második megerősítés - Írd be: CONFIRM
> CONFIRM
```

#### 2.2 Visszajelzés formátuma

```
================================================================================
CLEAR COUNTERS
--------------------------------------------------------------------------------
Törölve:
  - calls_today: 15 → 0
  - spent_usd: 0.0523 → 0.0
  - burst_used_p0: 2 → 0
  - burst_used_p1: 1 → 0
  - p2_replies_this_hour: 1 → 0

Megtartva:
  - replied_event_ids: 23 elem

State mentve: agent_state.json
================================================================================
```

#### 2.3 Meglévő `clear state` parancs

**Döntés:** Eltávolítjuk és helyettesítjük `clear all`-lal.

Alternatíva: Megtartjuk deprecated állapotban, de figyelmeztetéssel:
```
FIGYELEM: 'clear state' deprecated. Használd helyette:
  - clear counters (csak számlálók)
  - clear dedup (csak dedup lista)
  - clear all (minden)
```

---

### 3. Implementációs terv

#### 3.1 Új függvények `agent_shell.py`-ban

```python
def _clear_counters() -> None:
    """Törli a számlálókat, megtartja a dedup listát."""

def _clear_dedup() -> None:
    """Törli a dedup listát, megerősítéssel."""

def _clear_all() -> None:
    """Törli az összes állapotot, dupla megerősítéssel."""

def _confirm(prompt: str) -> bool:
    """Megerősítés kérése a felhasználótól."""
```

#### 3.2 State kezelés

A `moltagent/state.py`-ban már van `State` dataclass és `save_state()`. A clear műveletek:

1. Betöltjük a state-et: `load_state()`
2. Módosítjuk a megfelelő mezőket
3. Mentjük: `save_state()`

#### 3.3 REPL módosítás

```python
if cmd == "clear" and len(parts) >= 2:
    what = parts[1].lower()
    if what == "logs":
        _clear_logs()
    elif what == "counters":
        _clear_counters()
    elif what == "dedup":
        _clear_dedup()
    elif what == "all":
        _clear_all()
    elif what == "state":
        # Deprecated
        _print_card("DEPRECATED", "Használd: clear counters | clear dedup | clear all")
```

---

### 4. Acceptance Criteria

#### AC-1: clear counters működik
- **Given:** Van agent_state.json számlálókkal és dedup listával
- **When:** `clear counters` parancs
- **Then:**
  - Számlálók nullázódnak
  - Dedup lista MARAD
  - State mentve

#### AC-2: clear dedup megerősítést kér
- **Given:** Van agent_state.json dedup listával
- **When:** `clear dedup` parancs
- **Then:**
  - Megerősítés kérése
  - "no" → művelet megszakítva
  - "yes" → dedup lista törölve, számlálók MARADNAK

#### AC-3: clear all dupla megerősítést kér
- **Given:** Van agent_state.json
- **When:** `clear all` parancs
- **Then:**
  - Első megerősítés: "yes"
  - Második megerősítés: "CONFIRM"
  - Mindkettő OK → minden törölve
  - Bármelyik FAIL → művelet megszakítva

#### AC-4: clear all részleges megerősítésnél megszakít
- **Given:** `clear all` parancs
- **When:** Első "yes", de második nem "CONFIRM"
- **Then:** Művelet megszakítva, state VÁLTOZATLAN

#### AC-5: clear state deprecated
- **Given:** `clear state` parancs
- **When:** Felhasználó beírja
- **Then:** Deprecated üzenet, NEM töröl semmit

#### AC-6: Visszajelzés részletes
- **Given:** Bármely clear parancs sikeres
- **When:** Parancs végrehajtva
- **Then:** Visszajelzés mutatja:
  - Mit törölt (régi → új érték)
  - Mit tartott meg
  - State fájl mentve

#### AC-7: Help frissítve
- **Given:** `help` parancs
- **When:** Felhasználó beírja
- **Then:** Új clear parancsok dokumentálva

#### AC-8: Status mutatja a törölt értékeket
- **Given:** `clear counters` sikeres végrehajtás után
- **When:** `status` parancs
- **Then:** Számlálók 0-t mutatnak, dedup lista változatlan

#### AC-9: Agent futás figyelmeztetés
- **Given:** Agent process fut (opcionális implementáció)
- **When:** Bármely clear parancs
- **Then:** Figyelmeztetés: "FIGYELEM: Az agent futhat! Állítsd le a clear művelet előtt."

---

### 5. Teszt terv

#### 5.1 Unit tesztek (`tests/test_shell.py` - új fájl)

```python
def test_clear_counters_resets_counters():
    """clear counters nullázza a számlálókat"""

def test_clear_counters_keeps_dedup():
    """clear counters megtartja a dedup listát"""

def test_clear_dedup_requires_confirmation():
    """clear dedup megerősítést kér"""

def test_clear_dedup_aborts_on_no():
    """clear dedup 'no'-ra megszakít"""

def test_clear_all_requires_double_confirmation():
    """clear all dupla megerősítést kér"""

def test_clear_all_aborts_on_wrong_confirm():
    """clear all hibás CONFIRM-nál megszakít"""

def test_clear_state_is_deprecated():
    """clear state deprecated üzenetet ad"""
```

#### 5.2 Integrációs teszt (manuális)

1. Futtass `python agent_dryrun.py` → események feldolgozva
2. `status` → lásd a számlálókat és dedup listát
3. `clear counters` → számlálók 0, dedup marad
4. `clear dedup` → "no" → semmi nem változik
5. `clear dedup` → "yes" → dedup törölve
6. `clear all` → "yes" + "CONFIRM" → minden törölve

---

### 6. Rollback terv

Ha a változtatás problémát okoz:
1. Állítsd vissza a régi `_clear_state()` függvényt
2. Vagy: `git revert <commit>`

---

### 7. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-04 | 1.0 | Kezdeti specifikáció |
| 2025-02-05 | 1.1 | Implementáció kész, OpenAI o3 validálta (9/9 AC PASS) |

---

## Fejlesztés #3: Policy validáció

**Verzió:** 1.1
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** SPEC.md §13 Policy modell (13.4 Policy érvényesítés)
**ROADMAP hivatkozás:** Fázis 1.3

---

### 1. Áttekintés

#### 1.1 Probléma
A jelenlegi `load_policy()` egyszerűen beolvassa a JSON-t, de:
- Nincs schema validáció
- Hibás JSON → Python exception, nem felhasználóbarát
- Hiányzó mezők → runtime error később
- Nincs típusellenőrzés (pl. budget string helyett number)

#### 1.2 Megoldás
Pydantic model a policy struktúrához:
- Típusellenőrzés
- Default értékek hiányzó mezőkre
- Explicit hibaüzenetek
- Induláskor validálás

#### 1.3 Hatókör
- **Új fájl:** `moltagent/policy_model.py`
- **Módosítandó:** `moltagent/policy.py` - validáció hozzáadása
- **Módosítandó:** `agent_shell.py` - startup validálás
- **Módosítandó:** `agent_dryrun.py` - startup validálás

---

### 2. Részletes specifikáció

#### 2.1 Policy schema (Pydantic model)

```python
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional

class SchedulerConfig(BaseModel):
    enabled: bool = True
    burst_p0: int = Field(default=8, ge=0, le=50)
    burst_p1: int = Field(default=4, ge=0, le=50)

class ReplyConfig(BaseModel):
    max_replies_per_hour_p2: int = Field(default=2, ge=0, le=20)
    reply_to_mentions_always: bool = True
    reply_to_questions_always: bool = True
    offtopic_question_mode: str = Field(default="redirect", pattern="^(redirect|skip)$")

class DomainConfig(BaseModel):
    context: str = ""

class TopicsConfig(BaseModel):
    allow_keywords: List[str] = []
    block_keywords: List[str] = []

class StyleConfig(BaseModel):
    language: str = Field(default="en", pattern="^en$")  # Fix: csak EN!
    max_sentences: int = Field(default=5, ge=1, le=20)
    format: str = Field(default="steps", pattern="^(steps|bullet|paragraph)$")

class OperatorConfig(BaseModel):
    language: str = Field(default="hu", pattern="^hu$")  # Fix: csak HU!
    verbosity: str = Field(default="short", pattern="^(short|normal|verbose)$")

class PolicyModel(BaseModel):
    daily_budget_usd: float = Field(default=1.0, ge=0.01, le=100.0)
    max_calls_per_day: int = Field(default=200, ge=1, le=1000)
    min_seconds_between_calls: float = Field(default=1.0, ge=0.0, le=60.0)
    scheduler: SchedulerConfig = SchedulerConfig()
    reply: ReplyConfig = ReplyConfig()
    domain: DomainConfig = DomainConfig()
    topics: TopicsConfig = TopicsConfig()
    style: StyleConfig = StyleConfig()
    operator: OperatorConfig = OperatorConfig()

    @field_validator('daily_budget_usd')
    @classmethod
    def budget_precision(cls, v):
        return round(v, 4)
```

#### 2.2 Validáció kimenetei

**Sikeres validáció:**
```
✅ Policy OK: policy.json
   - Budget: $1.00/nap, max 200 hívás
   - Scheduler: enabled, burst P0=8, P1=4
```

**Hibás policy - típushiba:**
```
❌ Policy HIBA: policy.json
   - daily_budget_usd: nem szám ("abc")

Az agent nem indul el.
```

**Hibás policy - érték túl nagy:**
```
❌ Policy HIBA: policy.json
   - daily_budget_usd: maximum 100.0, kapott: 999.0

Az agent nem indul el.
```

**Hiányzó mező - default használata:**
```
⚠️ Policy figyelmeztetés: policy.json
   - scheduler.burst_p0: nincs megadva, default: 8

Policy OK, folytatás.
```

#### 2.3 Fix szabályok ellenőrzése

A Pydantic model kikényszeríti:
- `style.language` = "en" (regex pattern)
- `operator.language` = "hu" (regex pattern)

Ha valaki más értéket ad meg → validációs hiba.

#### 2.4 Safe defaults vs. fail-fast

**Döntés:** Fail-fast kritikus hibáknál, defaults opcionális mezőknél.

| Mező | Hiányzik | Hibás típus | Hibás érték |
|------|----------|-------------|-------------|
| daily_budget_usd | Default 1.0 | ❌ FAIL | ❌ FAIL (ha <0.01 vagy >100) |
| max_calls_per_day | Default 200 | ❌ FAIL | ❌ FAIL |
| scheduler | Default {} | - | - |
| scheduler.enabled | Default true | ❌ FAIL | - |
| style.language | Default "en" | ❌ FAIL | ❌ FAIL (ha nem "en") |

---

### 3. Implementációs terv

#### 3.1 Új fájl: `moltagent/policy_model.py`

```python
"""Policy Pydantic model és validáció."""
from pydantic import BaseModel, Field, field_validator, ValidationError
from typing import List, Optional, Tuple
import json

# ... model definíciók ...

def validate_policy(path: str) -> Tuple[bool, PolicyModel | None, List[str]]:
    """
    Validálja a policy fájlt.

    Returns:
        (success, policy_model, errors)
    """
    errors = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return (False, None, [f"Policy fájl nem található: {path}"])
    except json.JSONDecodeError as e:
        return (False, None, [f"Hibás JSON: {e}"])

    try:
        model = PolicyModel(**data)
        return (True, model, [])
    except ValidationError as e:
        for err in e.errors():
            field = ".".join(str(x) for x in err["loc"])
            msg = err["msg"]
            errors.append(f"{field}: {msg}")
        return (False, None, errors)
```

#### 3.2 Módosítás: `moltagent/policy.py`

```python
from .policy_model import validate_policy, PolicyModel

def load_policy(path: str = POLICY_FILE) -> Dict[str, Any]:
    """Betölti és validálja a policy.json fájlt."""
    success, model, errors = validate_policy(path)
    if not success:
        raise ValueError(f"Policy validáció sikertelen:\n" + "\n".join(errors))
    return model.model_dump()
```

#### 3.3 Módosítás: `agent_shell.py` és `agent_dryrun.py`

Induláskor:
```python
try:
    policy = load_policy()
    _print_card("POLICY OK", f"Budget: ${policy['daily_budget_usd']}/nap")
except ValueError as e:
    _print_card("POLICY HIBA", str(e))
    sys.exit(1)
```

---

### 4. Acceptance Criteria

#### AC-1: Érvényes policy betöltődik
- **Given:** Helyes policy.json
- **When:** Agent indul
- **Then:** Policy betöltődik, nincs hiba

#### AC-2: Hibás JSON kezelése
- **Given:** Szintaktikailag hibás JSON (pl. hiányzó vessző)
- **When:** Agent indul
- **Then:** Explicit hibaüzenet a JSON hibáról, agent nem indul

#### AC-3: Típushiba kezelése
- **Given:** `daily_budget_usd: "abc"` (string szám helyett)
- **When:** Agent indul
- **Then:** Hibaüzenet: "daily_budget_usd: nem szám", agent nem indul

#### AC-4: Érték túl nagy/kicsi
- **Given:** `daily_budget_usd: 999` (max 100)
- **When:** Agent indul
- **Then:** Hibaüzenet a limitről, agent nem indul

#### AC-5: Hiányzó opcionális mező → default
- **Given:** Nincs `scheduler` blokk a policy-ban
- **When:** Agent indul
- **Then:** Default scheduler értékek használata, agent indul

#### AC-6: Fix szabály felülírási kísérlet
- **Given:** `style.language: "hu"` (EN helyett)
- **When:** Agent indul
- **Then:** Hibaüzenet, agent nem indul

#### AC-7: Policy fájl nem található
- **Given:** Nincs policy.json
- **When:** Agent indul
- **Then:** Hibaüzenet: "Policy fájl nem található", agent nem indul

#### AC-8: Sikeres validáció logolva
- **Given:** Érvényes policy
- **When:** Agent indul
- **Then:** Console-on megjelenik: "Policy OK" + főbb értékek

#### AC-9: show policy mutatja a validált értékeket
- **Given:** Agent fut
- **When:** `show policy` parancs
- **Then:** Megjelennek a validált értékek (beleértve a default-okat)

---

### 5. Teszt terv

#### 5.1 Unit tesztek (`tests/test_policy_model.py`)

```python
def test_valid_policy_loads():
    """Érvényes policy betöltődik"""

def test_invalid_json_fails():
    """Hibás JSON hibát dob"""

def test_type_error_fails():
    """Típushiba hibát dob"""

def test_value_out_of_range_fails():
    """Érték túl nagy/kicsi hibát dob"""

def test_missing_optional_uses_default():
    """Hiányzó opcionális mező default értéket kap"""

def test_fixed_language_enforced():
    """style.language != 'en' hibát dob"""

def test_missing_file_fails():
    """Hiányzó fájl hibát dob"""
```

#### 5.2 Integrációs teszt (manuális)

1. Készíts hibás policy.json (pl. `daily_budget_usd: "abc"`)
2. Indítsd: `python agent_shell.py`
3. Ellenőrizd: hibaüzenet + nem indul

---

### 6. Rollback terv

Ha a változtatás problémát okoz:
1. Állítsd vissza a régi `load_policy()` függvényt (validáció nélkül)
2. Vagy: `git revert <commit>`

---

### 7. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-05 | 1.0 | Kezdeti specifikáció |
| 2025-02-05 | 1.1 | Implementáció kész, OpenAI o3 validálta (9/9 AC PASS) |

---

## Fejlesztés #4: Restart validálás

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** SPEC.md §14 State lifecycle
**ROADMAP hivatkozás:** Fázis 2.2

---

### 1. Áttekintés

#### 1.1 Követelmény
A SPEC §14 szerint:
- Restart NEM nullázza a számlálókat
- Restart NEM használható rate limit megkerülésére
- Csak az új nap (UTC váltás) nullázza a napi számlálókat
- Csak a `clear` parancsok törölhetik a state-et manuálisan

#### 1.2 Megvalósítás
A `moltagent/state.py` már helyesen implementálja ezt:
- `agent_state.json` perzisztens tárolás
- `load_state()` visszatölti az összes értéket
- `ensure_today()` csak új napnál nulláz

---

### 2. Restart viselkedés

#### 2.1 Perzisztens mezők

| Mező | Restart | Új nap | clear counters | clear all |
|------|---------|--------|----------------|-----------|
| calls_today | ✅ Megmarad | 🔄 Nullázódik | 🔄 Nullázódik | 🔄 Törlődik |
| spent_usd | ✅ Megmarad | 🔄 Nullázódik | 🔄 Nullázódik | 🔄 Törlődik |
| burst_used_p0 | ✅ Megmarad | 🔄 Nullázódik | 🔄 Nullázódik | 🔄 Törlődik |
| burst_used_p1 | ✅ Megmarad | 🔄 Nullázódik | 🔄 Nullázódik | 🔄 Törlődik |
| p2_replies_this_hour | ✅ Megmarad | 🔄 Nullázódik | 🔄 Nullázódik | 🔄 Törlődik |
| last_call_ts | ✅ Megmarad | 🔄 Nullázódik | 🔄 Nullázódik | 🔄 Törlődik |
| replied_event_ids | ✅ Megmarad | ✅ Megmarad | ✅ Megmarad | 🔄 Törlődik |

#### 2.2 Biztonsági implikációk

**Rate limit megkerülés NINCS:**
```
Felhasználó: "Leállítom és újraindítom az agentet, hogy nullázódjanak a számlálók"
Rendszer: NEM működik - a state perzisztens, restart után is megmaradnak a limitek
```

**Csak az új nap nullázza:**
```
- calls_today: 200 → restart → 200 (marad)
- calls_today: 200 → új nap → 0 (nullázódik)
```

---

### 3. Acceptance Criteria

#### AC-1: Restart megőrzi a számlálókat
- **Given:** State számlálókkal (calls=75, spent=0.54)
- **When:** Agent leáll és újraindul
- **Then:** Számlálók változatlanok (calls=75, spent=0.54)

#### AC-2: Restart nem kerüli meg a rate limitet
- **Given:** calls_today = 200 (limit)
- **When:** Agent restart
- **Then:** calls_today = 200 (továbbra is limit)

#### AC-3: Restart megőrzi a dedup listát
- **Given:** replied_event_ids = {"e1", "e2", "e3"}
- **When:** Agent restart
- **Then:** Agent NEM válaszol újra e1, e2, e3-ra

#### AC-4: Többszöri restart is megőrzi az állapotot
- **Given:** 5x restart
- **Then:** State konzisztens marad

#### AC-5: Új nap nullázza a számlálókat (kontroll)
- **Given:** day_key = tegnap, calls = 150
- **When:** Mai napon betöltődik
- **Then:** calls = 0 (új nap reset)

#### AC-6: Új nap megőrzi a dedup listát
- **Given:** day_key = tegnap, replied_event_ids = {"e1"}
- **When:** Mai napon betöltődik
- **Then:** replied_event_ids = {"e1"} (megmarad!)

---

### 4. Teszt terv

#### 4.1 Unit tesztek (`tests/test_state.py`)

```python
class TestRestartBehavior:
    def test_restart_preserves_counters()
    def test_restart_cannot_bypass_rate_limit()
    def test_restart_preserves_dedup_list()
    def test_multiple_restarts_preserve_state()
    def test_restart_same_day_no_reset()
    def test_new_day_does_reset_counters()
```

**Eredmény:** 6 új teszt, mind PASS

---

### 5. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-05 | 1.0 | Tesztek és dokumentáció kész |

---

## Fejlesztés #5: Error Handling & Recovery

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** Fázis 3 - Error handling & recovery
**ROADMAP hivatkozás:** Fázis 3

---

### 1. Áttekintés

#### 1.1 Probléma
A korábbi kódban NEM volt error handling az OpenAI API hívásoknál.
Ha az API hibát dobott, az exception kezeletlen maradt és az agent leállt.

#### 1.2 Megoldás
- Retry logika exponential backoff-fal
- Különböző hibatípusok kezelése
- Error logging
- Graceful degradation (SKIP és folytatás)

---

### 2. Implementáció

#### 2.1 Új modul: `moltagent/retry.py`

```python
@dataclass
class ReplyError(Exception):
    error_type: str
    message: str
    event_id: Optional[str] = None
    retry_count: int = 0
    original_exception: Optional[Exception] = None

def call_with_retry(
    func, *args,
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    event_id=None,
    **kwargs
) -> Any:
    """Exponential backoff retry logika."""

def log_error(event_id, error_type, message, retry_count, resolved, extra):
    """Hibák logolása errors.jsonl-be."""
```

#### 2.2 Retry viselkedés

| Exception típus | Retry? | Viselkedés |
|-----------------|--------|------------|
| APIConnectionError | ✅ | Retry exponential backoff-fal |
| APITimeoutError | ✅ | Retry exponential backoff-fal |
| RateLimitError (429) | ✅ | Retry, retry-after header alapján |
| APIError (400, 401) | ❌ | Azonnali fail, ReplyError |

#### 2.3 Backoff számítás

```
delay = base_delay * (2 ^ attempt)
delay = min(delay, max_delay)
delay += random.uniform(-jitter, +jitter)  # ±10%
```

Példa (base=1s, max=30s):
- Attempt 0: ~1s
- Attempt 1: ~2s
- Attempt 2: ~4s
- Attempt 3: fail

---

### 3. Érintett fájlok

| Fájl | Változás |
|------|----------|
| `moltagent/retry.py` | ÚJ - retry modul |
| `moltagent/reply.py` | call_with_retry() integráció |
| `moltagent/config.py` | MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY |
| `agent_dryrun.py` | try/except ReplyError → SKIP |
| `tests/test_retry.py` | ÚJ - 21 teszt |

---

### 4. Acceptance Criteria

#### AC-1: API hiba → max 3 retry
- **Given:** APIConnectionError
- **When:** call_with_retry()
- **Then:** 3 retry exponential backoff-fal

#### AC-2: Rate limit → retry-after
- **Given:** RateLimitError with retry-after header
- **When:** call_with_retry()
- **Then:** Várakozás a header értéke alapján

#### AC-3: Timeout → retry
- **Given:** APITimeoutError
- **When:** call_with_retry()
- **Then:** Retry exponential backoff-fal

#### AC-4: Sikertelen retry → SKIP
- **Given:** Minden retry sikertelen
- **When:** agent_dryrun.py
- **Then:** SKIP event, continue next

#### AC-5: Error logging
- **Given:** Hiba történik
- **When:** log_error()
- **Then:** logs/errors.jsonl bejegyzés

#### AC-6: Meglévő tesztek PASS
- **Given:** 126 teszt
- **When:** pytest tests/
- **Then:** Mind PASS

---

### 5. Teszt terv

#### 5.1 Unit tesztek (`tests/test_retry.py`)

```python
class TestReplyError: ...
class TestCalculateDelay: ...
class TestGetRetryAfter: ...
class TestCallWithRetry: ...
class TestLogError: ...
class TestRetryOnErrorDecorator: ...
class TestRetryIntegration: ...
```

**Eredmény:** 21 teszt PASS

---

### 6. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-05 | 1.0 | Implementáció kész, OpenAI validálta (6/6 AC PASS) |

---

## Fejlesztés #6: Crash Recovery

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** Fázis 3.2 - Crash recovery
**ROADMAP hivatkozás:** Fázis 3.2

---

### 1. Áttekintés

#### 1.1 Probléma
A korábbi implementációban:
- State mentés nem volt atomi (részleges írás lehetséges volt)
- Korrupt state fájl esetén az agent nem tudott elindulni
- Crash esetén az at-most-once garancia sérülhetett

#### 1.2 Megoldás
- Atomi state mentés: temp file + rename + fsync
- Korrupt state kezelés: backup + fresh state + error log
- At-most-once garancia: mark_replied csak sikeres API hívás után

---

### 2. Implementáció

#### 2.1 Atomi state mentés (`save_state()`)

```python
def save_state(st: State, state_file: str = STATE_FILE) -> None:
    temp_file = state_file + ".tmp"
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        os.replace(temp_file, state_file)  # Atomi rename
    except Exception:
        # Cleanup temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise
```

#### 2.2 Korrupt state kezelés (`load_state()`)

```python
def load_state(state_file: str = STATE_FILE) -> State:
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        # Korrupt JSON - backup + fresh state
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = f"{state_file}.corrupt.{timestamp}"
        os.rename(state_file, backup_path)
        _log_state_error("state_corrupt", f"...", backup_path)
        return State(day_key=today, hour_key=hour)
```

#### 2.3 At-most-once garancia

```python
# agent_dryrun.py
try:
    reply_en, in_tok, out_tok = make_outbound_reply(...)
except ReplyError as err:
    print(f"[SKIP] Event {event_id} - API hiba")
    continue  # NEM mark_replied!

# Sikeres reply után
st.mark_replied(event_id)
save_state(st)
```

---

### 3. Acceptance Criteria

#### AC-1: save_state() temp fájlba ír, majd atomi rename
- **Given:** State mentés
- **When:** save_state() hívás
- **Then:** Temp fájl létrejön, majd atomi rename

#### AC-2: save_state() fsync()-et hív a lemezre íráshoz
- **Given:** State mentés
- **When:** save_state() hívás
- **Then:** fsync() biztosítja a lemezre írást

#### AC-3: Korrupt state.json → backup + fresh state
- **Given:** Korrupt state.json (érvénytelen JSON)
- **When:** load_state() hívás
- **Then:** Backup létrejön, fresh state visszaadva

#### AC-4: At-most-once: mark_replied csak sikeres API hívás után
- **Given:** API hiba történik
- **When:** Retry is sikertelen
- **Then:** Event NEM lesz mark_replied

#### AC-5: Temp fájl törlődik hiba esetén
- **Given:** save_state() közben hiba
- **When:** Exception dobódik
- **Then:** Temp fájl törlődik

#### AC-6: Tesztek lefedik az összes esetet
- **Given:** 8 új teszt
- **When:** pytest tests/test_state.py::TestCrashRecovery
- **Then:** Mind PASS

---

### 4. Érintett fájlok

| Fájl | Változás |
|------|----------|
| `moltagent/state.py` | Atomi mentés + korrupt kezelés |
| `agent_dryrun.py` | At-most-once garancia |
| `tests/test_state.py` | 8 új teszt |

---

### 5. Tesztek

```python
class TestCrashRecovery:
    def test_atomic_write_creates_temp_file()
    def test_atomic_write_renames_to_final()
    def test_atomic_write_cleans_temp_on_error()
    def test_corrupt_json_creates_backup()
    def test_corrupt_json_logs_error()
    def test_corrupt_json_returns_fresh_state()
    def test_missing_file_returns_fresh_state()
    def test_at_most_once_guarantee()
```

**Eredmény:** 8 teszt PASS

---

### 6. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-05 | 1.0 | Implementáció kész, OpenAI validálta (6/6 AC PASS) |

---

## Fejlesztés #7: Soft Cap (80%)

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** SPEC.md §7b - Soft cap
**ROADMAP hivatkozás:** Fázis 1.4

---

### 1. Áttekintés

#### 1.1 Probléma
A hard cap (100%) csak akkor blokkolja az összes eseményt, amikor a napi budget már teljesen elfogyott. Ilyenkor a fontos P0/P1 események is blokkolva vannak.

#### 1.2 Megoldás
Soft cap: 80% budget felett a P2 események SKIP-elődnek, de P0/P1 még válaszolhat. Ez biztosítja, hogy a fontos események (mentions, relevant questions) még kapjanak választ a nap végéig.

---

### 2. Implementáció

#### 2.1 Új függvény: `_check_soft_cap()`

```python
def _check_soft_cap(
    state: State,
    policy: Dict[str, Any],
    priority: str,
) -> Optional[Dict[str, Any]]:
    """
    Ellenőrzi a 80%-os soft cap-et.

    SPEC §7b: 80% felett csak P0/P1 engedélyezett.
    P2 események SKIP-elődnek.
    """
    # P0/P1 mindig átmegy a soft cap-en
    if priority in ("P0", "P1"):
        return None

    daily_budget = float(policy.get("daily_budget_usd", 1.0))
    soft_cap_threshold = daily_budget * 0.80

    if state.spent_usd >= soft_cap_threshold:
        return {
            "reply": False,
            "priority": priority,
            "reason": "soft_cap_p2_blocked",
            "budget": {
                "spent_usd": state.spent_usd,
                "daily_budget_usd": daily_budget,
                "soft_cap_threshold": soft_cap_threshold,
                "soft_cap_percentage": 0.80,
            },
        }

    return None
```

#### 2.2 Pipeline pozíció

```
0. Idempotencia (duplicate_event)
1. Priority meghatározása
1.5. Hard cap ellenőrzés (budget_exhausted, daily_calls_cap)
1.6. Soft cap ellenőrzés (soft_cap_p2_blocked) ← ÚJ
2. Scheduler ellenőrzés
3. P2 hourly cap
```

---

### 3. Acceptance Criteria

#### AC-1: P2 SKIP 80% felett
- **Given:** spent_usd >= 80% of daily_budget
- **When:** P2 esemény feldolgozásra kerül
- **Then:** `reason: "soft_cap_p2_blocked"`

#### AC-2: P0 átmegy 80% felett
- **Given:** spent_usd >= 80%
- **When:** P0 (mention) esemény
- **Then:** `reply: true` (ha scheduler engedi)

#### AC-3: P1 átmegy 80% felett
- **Given:** spent_usd >= 80%
- **When:** P1 (relevant question) esemény
- **Then:** `reply: true` (ha scheduler engedi)

#### AC-4: P2 átmegy 80% alatt
- **Given:** spent_usd < 80%
- **When:** P2 esemény
- **Then:** `reply: true` (ha egyéb ellenőrzések OK)

#### AC-5: Budget info a döntésben
- **Given:** Soft cap SKIP
- **Then:** `budget` tartalmazza:
  - `soft_cap_threshold`
  - `soft_cap_percentage` (0.80)

#### AC-6: Hard cap előbb fut
- **Given:** spent_usd >= 100%
- **Then:** `reason: "budget_exhausted"` (nem soft_cap)

#### AC-7: Priority megőrződik
- **Given:** Soft cap SKIP
- **Then:** `priority: "P2"` (eredeti priority)

---

### 4. Érintett fájlok

| Fájl | Változás |
|------|----------|
| `moltagent/decision.py` | +`_check_soft_cap()`, pipeline módosítás |
| `tests/test_decision.py` | +11 teszt (`TestBudgetSoftCap`) |

---

### 5. Tesztek

```python
class TestBudgetSoftCap:
    def test_soft_cap_blocks_p2_at_80_percent()
    def test_soft_cap_allows_p0_at_80_percent()
    def test_soft_cap_allows_p1_at_80_percent()
    def test_soft_cap_allows_p2_below_80_percent()
    def test_soft_cap_budget_info_in_decision()
    def test_hard_cap_before_soft_cap()
    def test_soft_cap_priority_preserved()
    def test_check_soft_cap_helper_blocks_p2()
    def test_check_soft_cap_helper_allows_p0()
    def test_check_soft_cap_helper_allows_p1()
    def test_check_soft_cap_helper_ok_below_80()
```

**Eredmény:** 11 teszt PASS (145 összesen)

---

### 6. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-10 | 1.0 | Implementáció kész, OpenAI validálta (7/7 AC PASS) |

---

## Fejlesztés #8: SPEC Audit Tool

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** Fázis 5.1 - Audit tooling
**ROADMAP hivatkozás:** Fázis 5.1

---

### 1. Áttekintés

#### 1.1 Cél
Automatikus SPEC compliance ellenőrzés script, amely minden SPEC pontot tesztel és PASS/FAIL eredményt ad.

#### 1.2 Használat

```bash
python -m tools.spec_audit
```

---

### 2. Implementáció

#### 2.1 Ellenőrzött SPEC pontok

| SPEC | Leírás | Ellenőrzés |
|------|--------|------------|
| SPEC 1 | Bilingual output (EN/HU) | hu_operator_summary() működik |
| SPEC 2 | Decision logging | Döntés struktúra helyes |
| SPEC 3 | Dry-run mode | DRY_RUN flag létezik |
| SPEC 4 | Pipeline order | Fázis kommentek helyesek |
| SPEC 5 | Priority rules | P0/P1/P2 szabályok működnek |
| SPEC 6 | Idempotency | Dedup proof (két futás) |
| SPEC 7 | Budget hard cap | budget_exhausted működik |
| SPEC 7b | Soft cap (80%) | soft_cap_p2_blocked működik |
| SPEC 8 | Scheduler | Daily Pacer működik |
| SPEC 9 | Relevance | Keywords szűrés működik |
| SPEC 10 | Output format | Style config helyes |
| SPEC 11 | Security | .gitignore helyes |
| SPEC 13 | Policy validation | Pydantic validáció működik |
| SPEC 14 | State lifecycle | save/load működik |

#### 2.2 Kimenet formátum

```
============================================================
SPEC Audit Report
============================================================

✅ SPEC 1: Bilingual output (EN/HU)
   HU summary generálható
✅ SPEC 2: Decision logging
   Döntés struktúra OK
...
✅ SPEC 14: State lifecycle
   State lifecycle OK

------------------------------------------------------------
Overall: 14/14 PASS

🎉 All checks PASSED!
```

---

### 3. Acceptance Criteria

#### AC-1: Futtatható
- `python -m tools.spec_audit` működik

#### AC-2: 14 SPEC pont
- Minden SPEC pont ellenőrzésre kerül

#### AC-3: Dedup proof
- Két futás szimulálva, `duplicate_event` reason

#### AC-4: PASS/FAIL output
- Minden pontra egyértelmű eredmény

#### AC-5: Exit code
- 0 ha PASS, 1 ha FAIL

---

### 4. Érintett fájlok

| Fájl | Művelet |
|------|----------|
| `tools/__init__.py` | ÚJ |
| `tools/spec_audit.py` | ÚJ |

---

### 5. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-10 | 1.0 | Implementáció kész, OpenAI validálta (5/5 AC PASS) |

---

## Fejlesztés #9: CI Integráció

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** Fázis 5.2 - CI integráció
**ROADMAP hivatkozás:** Fázis 5.2

---

### 1. Áttekintés

#### 1.1 Cél
GitHub Actions CI pipeline, amely automatikusan futtatja a teszteket és a SPEC audit-ot minden push és PR esetén.

#### 1.2 Használat
Automatikus - minden `git push` és PR triggereli.

---

### 2. Implementáció

#### 2.1 Fájlok

| Fájl | Leírás |
|------|--------|
| `.github/workflows/ci.yml` | GitHub Actions workflow |
| `requirements.txt` | Függőségek a CI-hoz |

#### 2.2 Workflow konfiguráció

```yaml
name: CI

on:
  push:
    branches: [main, master]
  pull_request:
    branches: [main, master]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - Checkout code
      - Set up Python 3.11
      - Install dependencies
      - Run pytest tests/
      - Run python -m tools.spec_audit
```

#### 2.3 Függőségek

```
openai>=2.0.0
pydantic>=2.0.0
pytest>=8.0.0
```

---

### 3. Acceptance Criteria

#### AC-1: Workflow fájl létezik
- `.github/workflows/ci.yml` létezik

#### AC-2: Tesztek futnak
- `pytest tests/` sikeresen lefut

#### AC-3: SPEC audit fut
- `python -m tools.spec_audit` sikeresen lefut

#### AC-4: requirements.txt
- Minden függőség definiálva

---

### 4. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-10 | 1.0 | Implementáció kész |

---

## Fejlesztés #10: Moltbook Adapter

**Verzió:** 1.0
**Státusz:** ✅ KÉSZ
**SPEC hivatkozás:** Fázis 4 - Moltbook adapter
**ROADMAP hivatkozás:** Fázis 4

---

### 1. Áttekintés

#### 1.1 Cél
Valódi Moltbook API integráció, az `events.jsonl` mock helyett élő API polling és reply küldés.

#### 1.2 Fő funkciók
- **Mock adapter** - Teszteléshez, JSONL fájlból olvas
- **Moltbook adapter** - Valódi API, feed polling és comment küldés
- **Dry-run mód** - Alapértelmezetten nem küld semmit (biztonság)
- **--live flag** - Explicit engedélyezés szükséges az éles küldéshez

---

### 2. Architektúra

```
adapters/
├── __init__.py      # Factory: get_adapter()
├── base.py          # BaseAdapter ABC
├── mock.py          # MockAdapter - JSONL alapú
└── moltbook.py      # MoltbookAdapter - API alapú
```

#### 2.1 BaseAdapter interface

```python
class BaseAdapter(ABC):
    def fetch_events(self, limit: int = 50) -> List[Dict]
    def send_reply(self, event_id, text, post_id, parent_id) -> bool
    def get_agent_info(self) -> Dict
    @property agent_name: str
    @property is_dry_run: bool
```

---

### 3. Használat

#### 3.1 Mock adapter (alapértelmezett)

```bash
python agent_dryrun.py --adapter mock
# Vagy: policy.json-ban "adapter": "mock"
```

#### 3.2 Moltbook adapter (dry-run)

```bash
python agent_dryrun.py --adapter moltbook
# Feed-et lekéri, válaszokat CSAK logolja
```

#### 3.3 Moltbook adapter (éles)

```bash
python agent_dryrun.py --adapter moltbook --live
# FIGYELEM: Ténylegesen posztol a Moltbook-ra!
```

---

### 4. Konfiguráció

#### 4.1 Környezeti változók (.env)

```
MOLTBOOK_API_KEY=moltbook_sk_...
MOLTBOOK_AGENT_NAME=YourAgentName
MOLTBOOK_DRY_RUN=true  # Opcionális, default: true
```

#### 4.2 Policy.json

```json
{
  "adapter": "mock",  // vagy "moltbook"
  "moltbook": {
    "poll_interval_sec": 60,
    "reply_to_posts": true,
    "reply_to_comments": true
  }
}
```

---

### 5. Moltbook API endpointok

| Endpoint | Cél |
|----------|-----|
| `GET /feed` | Események lekérése |
| `POST /posts/{id}/comments` | Válasz küldése |
| `GET /agents/me` | Agent info |

#### 5.1 Rate limitek
- 100 requests/minute
- 1 comment per 20 seconds
- 50 comments/day

---

### 6. Tesztek

28 új teszt az `tests/test_adapters.py`-ben:

- `TestAdapterFactory` - Factory tesztek
- `TestMockAdapter` - Mock adapter tesztek
- `TestMoltbookAdapter` - API adapter tesztek
- `TestMoltbookRateLimiting` - Rate limit tesztek

---

### 7. Acceptance Criteria

- [x] AC-1: Mock adapter ugyanúgy működik, mint eddig
- [x] AC-2: Moltbook adapter lekéri a feed-et
- [x] AC-3: Moltbook adapter küld választ (dry-run és live)
- [x] AC-4: Policy `adapter` mező működik
- [x] AC-5: Meglévő tesztek PASS (173 összesen)
- [x] AC-6: Új adapter tesztek PASS (28 új)

---

### 8. Változtatási napló

| Dátum | Verzió | Változás |
|-------|--------|----------|
| 2025-02-10 | 1.0 | Implementáció kész |

---

## Fejlesztés #11: (Következő feature ide kerül)

(Placeholder a következő fejlesztéshez)
