Moltbook Agent – Alkalmazás-specifikáció (v1)

0. Kontextus

Ez a projekt egy helyben futó, költségkontrollált AI agentet valósít meg, amely Moltbook eseményeket figyel és szelektíven válaszol rájuk.

A repository publikus GitHubon.
Semmilyen titok (API kulcs, token, jelszó) vagy futás közbeni állapot nem kerülhet commitolásra.

Jelenleg az agent dry-run módban fut, később valódi Moltbook integrációval bővíthető.

⸻

1. Fő célok
	•	A Moltbook felé kimenő kommunikáció: csak angolul (EN)
	•	Operátori (emberi) nézet: csak magyarul (HU)
	•	A magyar összefoglalók nem használhatnak LLM-et
	•	Szigorú költség- és hívásszám-korlát
	•	Idempotens működés (ugyanarra az eseményre soha ne válaszoljon kétszer)
	•	Minden döntés visszakövethető és naplózott
	•	Publikus GitHub repository esetén is biztonságos

⸻

2. Alapfogalmak

Esemény (Event)

Egyetlen bejövő Moltbook-elem:
	•	post
	•	comment
	•	mention
	•	direct message (DM)

Logikai mezők:
	•	event_id (stabil, egyedi azonosító)
	•	típus
	•	szerző
	•	szöveg
	•	időbélyeg

Döntés (Decision)

Az agent döntése egy eseményről:
	•	action: REPLY | SKIP
	•	reason: gépileg olvasható okkód
	•	priority: P0 | P1 | P2

Kimenő válasz (Outbound Reply)
	•	Csak angol nyelvű szöveg
	•	Rövid, tömör, bullet-stílus
	•	Mondatszám policy által korlátozott

Operátori nézet (Operator View)

Helyi, magyar nyelvű összefoglaló:
	•	Esemény lényege (HU)
	•	Döntés magyarázata (HU)
	•	Válasz lényege (HU, ha volt válasz)

⸻

3. Nem-funkcionális elvárások
	•	Publikus repo esetén is biztonságos
	•	Nincs API kulcs vagy titok a git history-ban
	•	Azonos bemenet → azonos döntés
	•	Dry-run módban nincs tényleges várakozás (sleep)
	•	Minden állapotváltozás naplózott

⸻

4. Feldolgozási pipeline (kötelező sorrend)

Minden esemény pontosan ebben a sorrendben kerül feldolgozásra:
	1.	Esemény beolvasása
	2.	Prioritás meghatározása (P0/P1/P2)
	3.	Duplikáció / idempotencia ellenőrzés
	4.	Költségellenőrzés (USD + napi hívásszám)
	5.	Scheduler (napi ütemezés) ellenőrzés
	6.	Relevancia ellenőrzés
	7.	Angol válasz generálása (ha REPLY)
	8.	Magyar operátori összefoglaló készítése
	9.	Döntés, válasz és state mentése
	10.	Válasz kiküldése (dry-run esetén csak log)

⸻

5. Prioritások jelentése

P0 – Kritikus
	•	Mention (@agent)
	•	Direkt üzenet (DM)
	•	Biztonsági / credential jellegű témák

P1 – Fontos
	•	Egyértelmű kérdések:
	•	Moltbook agentekről
	•	költségkeretről, rate limitekről
	•	memóriáról, adatvédelemről
	•	konfigurációról

P2 – Alacsony prioritás
	•	Vélemények
	•	Off-topic beszélgetés
	•	Általános, nem célzott diskurzus

⸻

6. Duplikáció / Idempotencia
	•	A duplikáció kulcsa: event_id
	•	Csak REPLY döntés után kerül az event „feldolgozottnak” jelölésre
	•	Ha egy event_id már feldolgozott:
	•	Döntés: SKIP
	•	Ok: duplicate_event
	•	Az állapot futások között megmarad
	•	Megőrzés: minimum 30 nap vagy maximum elemszám

⸻

7. Költségkontroll

Kemény limitek
	•	daily_budget_usd
	•	max_calls_per_day

Szabályok
	•	Ha spent_today_usd >= daily_budget_usd:
→ SKIP (budget_exhausted)
	•	Ha calls_today >= max_calls_per_day:
→ SKIP (daily_calls_cap)

(Opcionális később: 80%-os soft cap, ahol csak P0/P1 engedélyezett)

⸻

8. Scheduler – Napi ütemező (Daily Pacer)

Cél: a napi hívások egyenletes elosztása.

Definíció
	•	earned_calls = (ma eltelt másodpercek / nap hossza) * max_calls_per_day

Szabályok
	•	Ha calls_today < floor(earned_calls): ENGEDÉLYEZETT
	•	Ha nem:
	•	P0: napi limitált burst (pl. 8)
	•	P1: napi limitált burst (pl. 4)
	•	P2: nincs burst
	•	Dry-run módban:
	•	nincs várakozás
	•	SKIP ok: scheduler_paced_wait
	•	wait_seconds logolva
	•	Napi limit elérésekor:
	•	SKIP ok: scheduler_daily_calls_cap

A burst számlálók naponta nullázódnak.

⸻

9. Relevancia szabályok
	•	P0: általában válaszolunk
	•	P1: válaszolunk, ha Moltbook-agent témájú
	•	P2:
	•	redirect vagy skip policy szerint
	•	óránkénti P2 limit alkalmazható

⸻

10. Kimeneti formátum

Moltbook felé (EN)
	•	Rövid, lényegre törő
	•	Bullet-pontok
	•	Nincs személyes vélemény

Operátor felé (HU)
	•	Strukturált, fix mezők
	•	Rövid, tömör megfogalmazás
	•	Magyarázza a döntés okát

⸻

11. Biztonsági szabályok (Publikus GitHub)

A repository-ban SOHA nem lehet:
	•	.env, *.env
	•	API kulcs (pl. “sk-…”)
	•	agent_state.json
	•	log fájlok
	•	SQLite / DB fájlok

Kulcskezelés:
	•	Local: .env (gitignored)
	•	Deploy: secret manager

⸻

12. Jövőbeli bővítés
	•	Valódi Moltbook adapter (polling / webhook)
	•	SQLite perzisztencia
	•	CI-alapú GPT review
	•	Több agent / több policy támogatása

⸻

13. Policy modell (Konfigurálható viselkedés)

Ez a szekció határozza meg, hogy mit lehet konfigurációval változtatni, és mi számít fix, nem felülírható szabálynak az agent működésében.

13.1 Policy célja
	•	Az agent viselkedésének finomhangolása kódmódosítás nélkül
	•	Biztonságos korlátok biztosítása (ne lehessen “túlhajtani”)
	•	Átlátható döntési logika az operátor számára

A policy nem tartalmazhat titkokat vagy API kulcsokat.

13.2 Konfigurálható policy elemek

Az alábbi elemek konfigurációból (pl. policy.json) állíthatók:

Költség és híváskorlát
	•	daily_budget_usd
	•	max_calls_per_day
	•	max_replies_per_hour_p2

Scheduler paraméterek
	•	burst_p0
	•	burst_p1
	•	min_seconds_between_calls

Válaszstílus (EN outbound)
	•	max_sentences
	•	reply_style (pl. bullet, short_paragraph)
	•	allow_redirects (P2 esetén)

Relevancia szabályok
	•	Engedélyezett témakörök listája
	•	Tiltott témakörök listája
	•	Kulcsszó-alapú P0/P1 erősítések

13.3 Nem konfigurálható (fix) szabályok

Az alábbi szabályok nem írhatók felül policy-ből:
	•	Kimenő kommunikáció nyelve: csak EN
	•	Operátori összefoglaló nyelve: csak HU
	•	Magyar összefoglaló nem hívhat LLM-et
	•	API kulcs, token, credential soha nem adható ki
	•	Duplikált eseményre nem válaszolunk

13.4 Policy érvényesítés
	•	A policy betöltése indításkor történik
	•	Érvénytelen vagy hiányos policy esetén:
	•	az agent nem indul el, vagy
	•	biztonságos default értékekre áll vissza
	•	A ténylegesen használt policy értékek naplózásra kerülnek

13.5 Policy és audit
	•	Minden döntés visszavezethető:
	•	esemény → policy szabály → döntés
	•	Operátori nézetben megjelenik:
	•	mely policy szabály volt meghatározó

⸻

14. Állapotkezelés (State lifecycle)

Ez a szekció rögzíti, hogy milyen állapotokat kezel az agent, ezek meddig élnek, mikor resetelődnek, és mi történik újraindítás vagy hiba esetén.

14.1 Állapottípusok

Az agent az alábbi állapotokat kezeli:

Hosszú élettartamú állapotok
	•	Feldolgozott event_id-k listája (dedup / idempotencia)
	•	Utolsó futás időpontja

Ezek az állapotok futások között megmaradnak, és nem kötődnek napi vagy órás időablakhoz.

Időablakhoz kötött állapotok
Napi állapotok (UTC naphoz kötve):
	•	calls_today
	•	spent_today_usd
	•	burst_used_p0
	•	burst_used_p1

Órás állapotok (UTC órához kötve):
	•	p2_replies_this_hour

Az időablakhoz kötött állapotok újraindítás után is megmaradnak az adott időablakon belül.

⸻

14.2 Napváltás és resetelés
	•	A „nap” definíciója: UTC 00:00 – 23:59
	•	Napváltáskor az alábbi állapotok resetelődnek:
	•	napi számlálók (calls_today, spent_today_usd)
	•	burst számlálók (burst_used_p0, burst_used_p1)
	•	Az órához kötött számlálók órahatárnál resetelődnek (UTC).
	•	A deduplikációs állapot nem resetelődik napváltáskor.

⸻

14.3 Újraindítás (restart) viselkedés
	•	Újraindítás esetén az agent:
	•	betölti a perzisztens állapotot
	•	nem nullázza le a számlálókat
	•	folytatja a feldolgozást az aktuális időablak szabályai szerint

Restart nem használható a költség- vagy rate limit megkerülésére.

⸻

14.4 Hiba és crash esetek
	•	Ha az agent futás közben összeomlik (crash):
	•	inkább nem válaszol, mint hogy duplikált választ küldjön
	•	részben feldolgozott esemény nem kerül „feldolgozottként” jelölésre

Az agent válaszadási modellje: at-most-once.

⸻

14.5 Állapot törlése (operator műveletek)

Az állapot törlésére külön parancsok szolgálnak:
	•	clear counters
	•	törli a napi és órás számlálókat
	•	nem érinti a dedup állapotot
	•	clear dedup
	•	törli a feldolgozott event_id-k listáját
	•	veszélyes művelet, külön megerősítést igényel
	•	clear all
	•	minden állapotot töröl
	•	dupla megerősítéssel végezhető el

⸻

14.6 Állapot tárolása
	•	Az állapot tárolásának módja implementációfüggő
	•	Kötelező elvárás:
	•	perzisztens (futások között megmarad)
	•	atomicitás biztosított (ne sérüljön crash esetén)

Ajánlás:
	•	Local fejlesztés: JSON fájl
	•	Production: SQLite vagy hasonló megbízható tároló

⸻
