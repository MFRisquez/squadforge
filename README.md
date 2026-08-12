# FutFantasy

Private Fantasy Premier League for ~10 friends. Free to use. Works on **iPhone, Android, and computer** as an installable web app.

## Permanent public link (recommended)

Deploy once to Render (free tier) — this gives a stable HTTPS URL for phones and computers:

1. Push this repo to GitHub (already done for `MFRisquez/squadforge`).
2. Open: [Deploy to Render](https://render.com/deploy?repo=https://github.com/MFRisquez/squadforge)
3. Create a free Web Service from `render.yaml` (includes a free **Postgres** database).
4. After deploy, your app URL looks like: `https://squadforge.onrender.com`
5. Set env var `PUBLIC_BASE_URL` to that URL (for password-reset links).

### Why accounts disappear after Render updates

If `DATABASE_URL` is missing, the app uses a local SQLite file on the web server. Render **deletes that file on every redeploy**. Fix once:

1. Render Dashboard → **New** → **PostgreSQL** → Free → create `squadforge-db`
2. Open that database → copy **Internal Database URL**
3. Open your **web service** → **Environment** → add  
   `DATABASE_URL` = that URL → **Save**
4. Confirm in **Logs** after deploy: `database backend: postgres` (not `sqlite`)
5. Register **once more** — later deploys keep the account

Do **not** remove `DATABASE_URL` when you change branches. Free Postgres expires after 30 days unless upgraded.

Then on iPhone: Safari → that URL → Share → **Add to Home Screen**.

## Run locally

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Computer: http://127.0.0.1:8000  
- Phone on same Wi‑Fi: `http://YOUR_COMPUTER_IP:8000`

Demo league invite code after first boot: **FORGE1**

## Accounts (free)

1. **Register** — User name, Password, Email, Team’s name  
2. **Sign in** — User name or email + password  
3. **Recover password** — from the login page (email link; if SMTP isn’t set, the reset link is shown on screen)

Optional SMTP env vars for real recovery emails: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`.

## What works now (MVP)

1. Free register / sign in / password recovery  
2. Create / join a private league  
3. **Select 15** (2 GK / 5 DEF / 5 MID / 3 ATT)  
4. **Select lineup** for the next GW  
5. **Transfers** — unlimited in GW1; later +1 FT/week (max 5)  
6. Technical Director (bottom-right on pitch) + chips  
7. Live FPL player list + live GW demo mode for testing  

## Rules for friends

- WhatsApp paste: `docs/RULES_WHATSAPP.txt`  
- Chips: `docs/CHIPS.md`  
- Technical Director: `docs/TECHNICAL_DIRECTOR.md`

## If the database schema changed

```bash
rm backend/data/squadforge.db
# then restart uvicorn (it re-seeds clubs/players/GW + FORGE1)
```
