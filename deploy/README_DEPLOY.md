# Moltbook Agent - Hostinger VPS Telepítési Útmutató

## Követelmények

- **Hostinger VPS KVM1** (vagy hasonló)
  - Ubuntu 22.04 LTS
  - 4 GB RAM
  - 1 vCPU
  - ~€5/hó
- **SSH hozzáférés** a szerverhez

---

## 1. VPS Vásárlás és Beállítás

### 1.1 Hostinger VPS rendelés

1. Menj a [Hostinger VPS](https://www.hostinger.com/vps-hosting) oldalra
2. Válaszd a **KVM 1** tervet
3. Válassz **Ubuntu 22.04** operációs rendszert
4. Add meg az SSH kulcsod (ajánlott) vagy jelszót

### 1.2 SSH Belépés

```bash
# Első belépés
ssh root@YOUR_VPS_IP

# SSH kulcs esetén
ssh -i ~/.ssh/id_rsa root@YOUR_VPS_IP
```

---

## 2. Kód Feltöltés

### 2.1 Git Clone (ajánlott)

```bash
# A VPS-en:
cd /opt
git clone https://github.com/emeraldf1/moltbook-agent.git
cd moltbook-agent
```

### 2.2 Alternatíva: rsync

```bash
# A saját gépeden:
rsync -avz --exclude '.venv' --exclude '__pycache__' \
  ~/moltbook-agent/ root@YOUR_VPS_IP:/opt/moltbook-agent/
```

---

## 3. Telepítés

```bash
# A VPS-en:
cd /opt/moltbook-agent
chmod +x deploy/install.sh
sudo ./deploy/install.sh
```

Ez automatikusan:
- Telepíti a Python 3.11-et
- Létrehozza a `moltbook` felhasználót
- Beállítja a virtual environment-et
- Telepíti a systemd service-t

---

## 4. Konfiguráció

### 4.1 .env fájl létrehozása

```bash
cp /opt/moltbook-agent/.env.template /opt/moltbook-agent/.env
nano /opt/moltbook-agent/.env
```

Tartalom:

```env
OPENAI_API_KEY=sk-your-openai-key-here
MOLTBOOK_API_KEY=your-moltbook-api-key-here
MOLTBOOK_AGENT_NAME=YourAgentName
MOLTBOOK_DRY_RUN=true
```

⚠️ **FONTOS:** A `MOLTBOOK_DRY_RUN=true` beállítás miatt az agent NEM fog ténylegesen posztolni!

### 4.2 Policy beállítása

```bash
nano /opt/moltbook-agent/policy.json
```

Módosítsd az `adapter` mezőt:

```json
{
  "adapter": "moltbook",
  ...
}
```

---

## 5. Indítás és Kezelés

### 5.1 Service indítása

```bash
# Indítás
sudo systemctl start moltbook-agent

# Leállítás
sudo systemctl stop moltbook-agent

# Újraindítás
sudo systemctl restart moltbook-agent

# Státusz
sudo systemctl status moltbook-agent
```

### 5.2 Logok megtekintése

```bash
# Systemd log (realtime)
sudo journalctl -u moltbook-agent -f

# Alkalmazás logok
tail -f /opt/moltbook-agent/logs/decisions.jsonl
tail -f /opt/moltbook-agent/logs/moltbook_replies.jsonl
```

---

## 6. Dry-run → Éles Átállás

### 6.1 Dry-run tesztelés

Először mindig dry-run módban tesztelj:

```bash
# Ellenőrizd a logokat
tail -f /opt/moltbook-agent/logs/moltbook_replies.jsonl

# Látnod kell: "dry_run": true
```

### 6.2 Éles mód engedélyezése

**CSAK ha biztos vagy benne**, hogy jól működik:

```bash
# .env módosítása
nano /opt/moltbook-agent/.env
# Állítsd át: MOLTBOOK_DRY_RUN=false

# VAGY: systemd service módosítása
sudo nano /etc/systemd/system/moltbook-agent.service
# Add hozzá a --live flaget az ExecStart sorhoz:
# ExecStart=/opt/moltbook-agent/.venv/bin/python /opt/moltbook-agent/agent_daemon.py --live

# Újraindítás
sudo systemctl daemon-reload
sudo systemctl restart moltbook-agent
```

---

## 7. Hibaelhárítás

### Service nem indul

```bash
# Részletes hiba
sudo journalctl -u moltbook-agent -n 50 --no-pager

# Gyakori okok:
# - .env fájl hiányzik
# - Rossz API kulcs
# - Python dependency hiba
```

### Manuális teszt

```bash
cd /opt/moltbook-agent
source .venv/bin/activate
python agent_daemon.py --once

# Ha működik, a service-nek is kell
```

### Memory hiba

```bash
# Ha OOM killer leállítja:
sudo nano /etc/systemd/system/moltbook-agent.service
# Növeld: MemoryMax=768M
sudo systemctl daemon-reload
sudo systemctl restart moltbook-agent
```

---

## 8. Frissítés

```bash
cd /opt/moltbook-agent

# Kód frissítése
git pull origin main

# Függőségek frissítése
source .venv/bin/activate
pip install -r requirements.txt

# Service újraindítása
sudo systemctl restart moltbook-agent
```

---

## 9. Biztonsági Tippek

1. **Tűzfal beállítása**
   ```bash
   sudo ufw allow ssh
   sudo ufw enable
   ```

2. **SSH kulcs használata** (jelszó helyett)

3. **Rendszeres frissítések**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

4. **API kulcsok védelme**
   - `.env` fájl jogosultságok: `chmod 600 .env`
   - Soha ne commitold a git-be!

---

## 10. Hasznos Parancsok Összefoglaló

| Parancs | Leírás |
|---------|--------|
| `sudo systemctl status moltbook-agent` | Státusz |
| `sudo systemctl start moltbook-agent` | Indítás |
| `sudo systemctl stop moltbook-agent` | Leállítás |
| `sudo systemctl restart moltbook-agent` | Újraindítás |
| `sudo journalctl -u moltbook-agent -f` | Log (élő) |
| `sudo journalctl -u moltbook-agent -n 100` | Utolsó 100 sor |
| `tail -f /opt/moltbook-agent/logs/*.jsonl` | App logok |

---

## Támogatás

Ha problémád van, nézd meg:
1. A logokat (`journalctl` és `logs/` mappa)
2. A `SPEC_EXT.md` dokumentációt
3. Futtasd a SPEC audit-ot: `python -m tools.spec_audit`
