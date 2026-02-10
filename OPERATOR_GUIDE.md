# Operátori Kézikönyv 🦞

Ez a dokumentum a Moltbook Agent napi üzemeltetéséhez nyújt útmutatót.

## Tartalom

1. [Gyors Indítás](#gyors-indítás)
2. [Shell Parancsok](#shell-parancsok)
3. [Daemon Üzemeltetés](#daemon-üzemeltetés)
4. [Monitoring](#monitoring)
5. [Hibaelhárítás](#hibaelhárítás)
6. [Gyakori Kérdések](#gyakori-kérdések)

---

## Gyors Indítás

### Lokális futtatás (tesztelés)

```bash
# Virtual environment aktiválása
source .venv/bin/activate

# Egyetlen futás mock adatokkal
python agent_dryrun.py

# Egyetlen futás Moltbook API-val (dry-run)
python agent_dryrun.py --adapter moltbook
```

### Daemon indítása (folyamatos futás)

```bash
# Dry-run mód (nem posztol)
python agent_daemon.py

# ÉLES mód (FIGYELEM: posztol!)
python agent_daemon.py --live

# Egyetlen ciklus (teszteléshez)
python agent_daemon.py --once
```

---

## Shell Parancsok

```bash
python agent_shell.py
```

### Információs parancsok

| Parancs | Leírás |
|---------|--------|
| `status` | Budget, scheduler, state összefoglaló |
| `show <id>` | Esemény megjelenítése ID alapján |
| `why <id>` | Döntés okának megjelenítése |
| `reply <id>` | Generált angol válasz |
| `hu <id>` | Magyar operátori összefoglaló |

### Log parancsok

| Parancs | Leírás |
|---------|--------|
| `tail events [n]` | Utolsó n bejövő esemény |
| `tail decisions [n]` | Utolsó n döntés |
| `tail outbound [n]` | Utolsó n kimenő válasz |
| `tail operator [n]` | Utolsó n operátori összefoglaló |

### Beállítás parancsok

| Parancs | Leírás |
|---------|--------|
| `set scheduler on/off` | Daily Pacer be/ki |
| `set burst_p0 <n>` | P0 burst limit |
| `set burst_p1 <n>` | P1 burst limit |
| `set maxcalls <n>` | Napi hívás limit |

### Állapot törlés

| Parancs | Leírás | Megerősítés |
|---------|--------|-------------|
| `clear counters` | Napi számlálók nullázása | Nincs |
| `clear dedup` | Feldolgozott ID-k törlése | "yes" |
| `clear all` | Teljes állapot törlése | "CONFIRM" |
| `clear logs` | Log fájlok törlése | Nincs |

### Futtatás

| Parancs | Leírás |
|---------|--------|
| `run` | Egyetlen feldolgozási ciklus |
| `exit` / `quit` | Kilépés |

---

## Daemon Üzemeltetés

### VPS-en (systemd)

```bash
# Státusz
sudo systemctl status moltbook-agent

# Indítás
sudo systemctl start moltbook-agent

# Leállítás
sudo systemctl stop moltbook-agent

# Újraindítás
sudo systemctl restart moltbook-agent

# Logok (élő)
sudo journalctl -u moltbook-agent -f

# Utolsó 100 sor
sudo journalctl -u moltbook-agent -n 100
```

### Lokálisan

```bash
# Háttérben
nohup python agent_daemon.py > daemon.log 2>&1 &

# Leállítás (graceful)
kill -SIGTERM <PID>

# Vagy Ctrl+C ha előtérben fut
```

---

## Monitoring

### Budget ellenőrzés

A shell `status` parancs mutatja:

```
Budget: ████████░░ 78% ($0.78 / $1.00)
         ▲ vizuális indikátor

⚠️ 80%+ : Soft cap - P2 blokkolva
🛑 100% : Hard cap - minden blokkolva
```

### Log fájlok

| Fájl | Tartalom | Mikor nézd |
|------|----------|------------|
| `logs/daily_summary.jsonl` | Napi összefoglaló | Nap végén |
| `logs/monitoring.jsonl` | Ciklus statisztikák | Debugging |
| `logs/errors.jsonl` | Hibák | Ha probléma van |
| `logs/decisions.jsonl` | Minden döntés | Audit |
| `logs/moltbook_replies.jsonl` | API válaszok | Éles mód ellenőrzés |

### Budget warning küszöbök

| Szint | Trigger | Hatás |
|-------|---------|-------|
| 80% | Warning log | P2 események SKIP |
| 90% | Warning log | P2 események SKIP |
| 95% | Warning log | P2 események SKIP |
| 100% | Hard cap | MINDEN esemény SKIP |

### Napi összefoglaló

A daemon minden napváltáskor és leálláskor logol:

```
📊 DAILY SUMMARY - 2025-02-10
Budget: $0.85 / $1.00 (85.0%)
Calls: 156
Replied: 142 | Skipped: 14 | Errors: 0
Error rate: 0.0%
```

---

## Hibaelhárítás

### "Nem indul az agent"

**1. Ellenőrizd a .env fájlt:**
```bash
cat .env
# Szükséges:
# OPENAI_API_KEY=sk-...
# MOLTBOOK_API_KEY=moltbook_sk_...
# MOLTBOOK_AGENT_NAME=YourAgentName
```

**2. Ellenőrizd a policy.json-t:**
```bash
python -c "from moltagent.policy import load_policy; load_policy(validate=True)"
```

**3. Teszteld manuálisan:**
```bash
python agent_daemon.py --once
```

### "API hibák a logban"

**1. Nézd meg a hibát:**
```bash
tail -20 logs/errors.jsonl | python -m json.tool
```

**2. Gyakori okok:**
- `401 Unauthorized` → Rossz API kulcs
- `429 Rate Limited` → Túl sok kérés (automatikusan retry-ol)
- `500 Server Error` → Moltbook oldali hiba

### "Nem válaszol semmire"

**1. Ellenőrizd a budget-et:**
```bash
python agent_shell.py
> status
```

Ha 100% → új nap kell, vagy növeld a `daily_budget_usd`-t

**2. Ellenőrizd a scheduler-t:**
```bash
> status
# Ha "scheduler_paced_wait" → várni kell
# Vagy: set scheduler off
```

**3. Ellenőrizd a dedup listát:**
```bash
cat agent_state.json | python -m json.tool | grep replied_event_ids
```

Ha sok ID van → `clear dedup` (ha biztosan új feldolgozás kell)

### "Dry-run → Éles átállás"

**1. Ellenőrizd a dry-run logokat:**
```bash
tail logs/moltbook_replies.jsonl
# "dry_run": true kell legyen
```

**2. Ellenőrizd a generált válaszokat:**
```bash
tail logs/replies_outbound_en.jsonl | python -m json.tool
```

**3. Ha minden OK, kapcsold élőre:**
```bash
# .env-ben:
MOLTBOOK_DRY_RUN=false

# VAGY daemon flag:
python agent_daemon.py --live
```

### "VPS memory hiba"

```bash
# Ellenőrizd a memóriát
free -h

# Ha OOM → növeld a limitet
sudo nano /etc/systemd/system/moltbook-agent.service
# MemoryMax=768M

sudo systemctl daemon-reload
sudo systemctl restart moltbook-agent
```

---

## Gyakori Kérdések

### Hány válasz megy ki naponta?

`max_calls_per_day` a policy.json-ben (alapértelmezett: 200)

### Mennyibe kerül naponta?

`daily_budget_usd` a policy.json-ben (alapértelmezett: $1.00)

A tényleges költés a `status` parancsban látható.

### Hogyan változtatom meg az agent nevét?

1. Moltbook.com-on regisztrálj új agent-et
2. Frissítsd a .env-ben:
   ```
   MOLTBOOK_AGENT_NAME=UjNev
   MOLTBOOK_API_KEY=uj_api_key
   ```
3. Indítsd újra a daemon-t

### Mi történik ha a VPS újraindul?

A systemd automatikusan újraindítja az agent-et (`Restart=on-failure`).

Az állapot (`agent_state.json`) megmarad, nem küld dupla válaszokat.

### Hogyan állíthatok be egyedi poll intervallumot?

```bash
# CLI flag
python agent_daemon.py --interval 120  # 120 másodperc

# VAGY policy.json:
{
  "moltbook": {
    "poll_interval_sec": 120
  }
}
```

### Hogyan látom valós időben a tevékenységet?

```bash
# Daemon log
sudo journalctl -u moltbook-agent -f

# VAGY app log
tail -f logs/decisions.jsonl
```

---

## Kapcsolat

- **SPEC dokumentáció:** `SPEC.md`
- **Fejlesztési roadmap:** `ROADMAP.md`
- **VPS telepítés:** `deploy/README_DEPLOY.md`
- **GitHub:** https://github.com/emeraldf1/moltbook-agent
