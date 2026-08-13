# FutFantasy

Private Fantasy Premier League for ~10 friends. Free to use. Works on **iPhone, Android, and computer** as an installable web app.

## Permanent public link (recommended)

**Render** hosts the website (free). **Supabase** hosts the database (free, no 30-day expiry like Render Postgres).

### 1) Create a free Supabase database

1. Go to [https://supabase.com](https://supabase.com) → Sign up / Sign in  
2. **New project** → name it `futfantasy` → set a strong DB password → create  
3. Wait until the project is ready  
4. Click **Connect** (or Project Settings → Database)  
5. Choose **Session pooler** (port **5432**) — works best from Render  
6. Copy the URI. It looks like:  
   `postgresql://postgres.xxxxx:[YOUR-PASSWORD]@aws-0-….pooler.supabase.com:5432/postgres`  
7. Replace `[YOUR-PASSWORD]` with the real database password if needed  

### 2) Point Render at Supabase

1. Open your **FutFantasy / squadforge** web service on Render  
2. **Environment** → add or edit:  
   - **Key:** `DATABASE_URL`  
   - **Value:** paste the Supabase URI from step 6  
3. Optional: `PUBLIC_BASE_URL` = your public site URL (same as the link friends use), e.g. `https://futfantasy.onrender.com`  
4. **Save** → redeploy (Manual Deploy → latest commit)  
5. In **Logs**, confirm: `database backend: postgres`  
6. Register **once** on the live site — later deploys keep the account  

You can **delete / ignore** the expiring Render Postgres database after Supabase works. Do not leave `DATABASE_URL` pointing at the Render DB if you plan to delete it.

### Change the public link (Render URL)

**Rename the free `*.onrender.com` address**
1. Render Dashboard → your **futfantasy** web service → **Settings**
2. Edit **Name** (this becomes `https://NEW-NAME.onrender.com`)
3. Save → wait for redeploy
4. Update env `PUBLIC_BASE_URL` to the new URL (needed for password-reset emails)

**Use your own domain (optional)**  
Settings → **Custom Domains** → add e.g. `play.futfantasy.app` → follow DNS instructions.

### App icon (browser tab + Add to Home Screen)

Icons live in `backend/app/web/static/icons/` (`logo.svg`, `icon-192.png`, `icon-512.png`, `favicon.ico`).  
After deploy: hard-refresh (or delete the old Home Screen shortcut and **Add to Home Screen** again) so the new Fut Fantasy mark shows.

### 3) Deploy branch

Use branch `cursor/supabase-database-9855` (or merge to your deploy branch).

Then on iPhone: Safari → your Render URL → Share → **Add to Home Screen**.

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
