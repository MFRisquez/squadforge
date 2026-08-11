# SquadForge

Private Fantasy Premier League for ~10 friends. Built as a **phone web app** (installable PWA) that also works on desktop.

## Run it

```bash
cd ~/Projects/squadforge/backend
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open on your phone (same Wi‑Fi): `http://YOUR_COMPUTER_IP:8000`  
Or on this Mac: http://127.0.0.1:8000

Demo league invite code after first boot: **FORGE1**

## Install on your cellphone

1. Open SquadForge in **Chrome (Android)** or **Safari (iPhone)**.
2. Android: tap **Install** when the banner appears (or Chrome menu → Install app).
3. iPhone: Share → **Add to Home Screen**.
4. Launch from the home-screen icon — it opens fullscreen like a native app.

> Install prompts need a secure context. `localhost` works; on a real phone over LAN, use HTTPS or a tunnel (e.g. Cloudflare Tunnel / ngrok) if Chrome won’t offer Install.

## Test as if a gameweek is already live

Signed in on Home → **Phone app · live GW test**:

1. **Start live GW demo** — locks the current GW deadline, auto-fills your 15 + XI if empty, invents mid-GW fixtures + demo points, then opens **XI**.
2. Browse **XI / Fixtures / Table** on your phone as a live gameweek.
3. **End live demo** — restores the real deadline and fixture state.

You can also tap **Demo scores** on the locked XI page anytime.

## What works now (MVP)

1. Sign in with name + PIN  
2. Create / join a private league  
3. **Select 15** (2 GK / 5 DEF / 5 MID / 3 ATT) with search + filters  
4. **Select lineup** for the next GW (formation bands like FPL)  
5. **Transfers** — unlimited in GW1; from GW2: **+1 FT per week, cumulative (max 5)**  
6. Technical Director + chip inventory  
7. **Live FPL player list** (2025/26 season feed) — refresh on Home or each server start  
8. Installable phone PWA + live GW demo mode for testing  

## Refresh players weekly

```bash
# while logged in: Home → “Refresh players from FPL”
# or restart the server (startup sync)
```

## Rules for friends

- WhatsApp paste: `docs/RULES_WHATSAPP.txt`  
- Chips: `docs/CHIPS.md`  
- Technical Director: `docs/TECHNICAL_DIRECTOR.md`

## If the database schema changed

```bash
rm backend/data/squadforge.db
# then restart uvicorn (it re-seeds clubs/players/GW + FORGE1)
```

## Next build steps

- Play chips (TC, Bench Boost, Super Sub, Free Hit, WC)  
- Pull live PL stats + compute GW points  
- Auto-subs + standings that move  
- Optional: wrap in Expo / Capacitor for App Store later  
