# DamascusTransit — Deployment Guide

Deploy the full platform to **Vercel** (frontend + API) + **Supabase** (database).
Total cost: **$0** on free tiers.

---

## Prerequisites

- [Node.js 18+](https://nodejs.org/) installed
- [Vercel CLI](https://vercel.com/docs/cli): `npm i -g vercel`
- A [Supabase](https://supabase.com) account (free tier)
- A [GitHub](https://github.com) account (optional, for auto-deploy)

---

## Step 1: Create Supabase Project

1. Go to [supabase.com](https://supabase.com) → **New Project**
2. Choose a name (e.g., `damascus-transit`) and set a database password
3. Select region closest to Damascus: **Frankfurt (eu-central-1)** recommended
4. Wait for the project to be ready (~2 minutes)

### Enable PostGIS

1. In Supabase dashboard → **SQL Editor**
2. Run: `CREATE EXTENSION IF NOT EXISTS postgis;`

### Run Schema

1. Open **SQL Editor** → **New query**
2. Copy the entire contents of `db/schema.sql` and run it
3. Copy the entire contents of `db/seed.sql` and run it
4. Verify: Run `SELECT count(*) FROM routes;` → should return **8**
5. Verify: Run `SELECT count(*) FROM stops;` → should return **42**
6. Verify: Run `SELECT count(*) FROM vehicles;` → should return **24**

### Enable Realtime

In the SQL Editor, run:
```sql
ALTER PUBLICATION supabase_realtime ADD TABLE vehicle_positions_latest;
ALTER PUBLICATION supabase_realtime ADD TABLE alerts;
```

### Enable Connection Pooling (Supavisor) — REQUIRED for 500+ vehicles

Without this, the 20-connection free-tier pool exhausts at ~120 concurrent vehicles, causing 5xx errors.

1. Go to **Settings** → **Database** → **Connection Pooling**
2. Enable **Supavisor** (Transaction mode)
3. Copy the **Pooler connection string** — it looks like:
   `postgresql://postgres.xxxx:[password]@aws-0-eu-central-1.pooler.supabase.com:6543/postgres`
4. In Vercel → **Settings** → **Environment Variables**, update `SUPABASE_URL` to the pooler host:
   `https://aws-0-eu-central-1.pooler.supabase.com` (substitute your project's region)
5. Redeploy after updating env vars

> **Note:** The REST API URL format (`https://...`) does not include the `:6543` port — that port applies only to direct PostgreSQL connection strings. The pooler HTTP endpoint is always HTTPS/443.

### Get Your Keys

1. Go to **Settings** → **API**
2. Copy these values (you'll need them in Step 3):
   - **Project URL** → `SUPABASE_URL` (use the pooler URL above, not the default project URL)
   - **anon/public key** → `SUPABASE_KEY`
   - **service_role key** → `SUPABASE_SERVICE_KEY`

---

## Step 2: Deploy to Vercel

### Option A: CLI Deploy (Quickest)

```bash
cd damascus-transit-platform

# Login to Vercel
vercel login

# Deploy
vercel

# Follow prompts:
#   - Link to existing project? → No
#   - Project name? → damascus-transit
#   - Framework? → Other
#   - Override settings? → No
```

### Option B: GitHub Deploy (Auto-deploy on push)

1. Push `damascus-transit-platform/` to a GitHub repo
2. Go to [vercel.com/new](https://vercel.com/new) → Import your repo
3. Framework Preset: **Other**
4. Build Command: `pip install -r requirements.txt`
5. Output Directory: `public`
6. Deploy

---

## Step 3: Set Environment Variables

In Vercel dashboard → your project → **Settings** → **Environment Variables**:

| Variable | Value | Notes |
|----------|-------|-------|
| `SUPABASE_URL` | `https://aws-0-<region>.pooler.supabase.com` | Supavisor pooler URL (see Step 1) — **required for 500-vehicle scale** |
| `SUPABASE_KEY` | `eyJ...` | anon/public key |
| `SUPABASE_SERVICE_KEY` | `eyJ...` | service_role key (keep secret!) |
| `JWT_SECRET` | (generate one) | Run: `openssl rand -hex 32` |
| `TRACCAR_WEBHOOK_SECRET` | (optional) | Only if using Traccar GPS server |

After adding variables, **redeploy**:
```bash
vercel --prod
```

---

## Step 4: Verify Deployment

Visit your Vercel URL (e.g., `damascus-transit-xxxx.vercel.app`):

| URL | What It Shows |
|-----|--------------|
| `/` | Public tracking dashboard with live map |
| `/admin/` | Admin/dispatcher operations center |
| `/passenger/` | Passenger mobile app (PWA) |
| `/driver/` | Driver companion app (PWA) |
| `/api/health` | API health check → `{"status": "ok"}` |
| `/api/routes` | All 8 Damascus routes as JSON |
| `/api/stops` | All 42 stops with coordinates |
| `/api/stats` | Fleet statistics |

### Test Login

```bash
curl -X POST https://YOUR-URL.vercel.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@damascustransit.sy", "password": "YOUR_ADMIN_PASSWORD"}'
```

Should return a JWT token. The seed data uses placeholder hashes — set real bcrypt hashes before running it (see `db/seed.sql` comments).

---

## Step 5: Start the Simulator (Optional)

The simulator from the Docker demo can push positions to the Vercel API:

```bash
# In the damascus-transit-demo folder
cd ../damascus-transit-demo/simulator

# Edit simulator.py to point to your Vercel URL instead of localhost
# Then run:
python3 simulator.py
```

Or use the OsmAnd app on your phone to send real GPS data through Traccar.

---

## Architecture Diagram

```
┌─────────────┐     ┌─────────────────────────────────┐
│  Passengers  │────→│  Vercel (Frontend)               │
│  (PWA app)   │     │  ├── / (Dashboard)               │
└─────────────┘     │  ├── /passenger/ (PWA)           │
                     │  ├── /driver/ (PWA)              │
┌─────────────┐     │  └── /admin/ (Operations)        │
│   Drivers    │────→│                                   │
│  (PWA app)   │     │  Vercel (Serverless API)         │
└─────────────┘     │  └── /api/* (FastAPI)             │
                     └──────────┬──────────────────────┘
                                │
                     ┌──────────▼──────────────────────┐
                     │  Supabase (PostgreSQL + PostGIS)  │
                     │  ├── Routes, Stops, Vehicles      │
                     │  ├── Position history              │
                     │  ├── Realtime subscriptions        │
                     │  └── Auth & RLS                    │
                     └──────────┬──────────────────────┘
                                │
┌─────────────┐     ┌──────────▼──────────┐
│  GPS Devices │────→│  Traccar Server      │──→ Webhook to /api/traccar/position
│  (Teltonika) │     │  (separate VPS)      │
└─────────────┘     └─────────────────────┘
```

---

## File Structure

```
damascus-transit-platform/
├── vercel.json              # Vercel deployment config
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
├── DEPLOY.md                # This file
│
├── api/
│   └── index.py             # FastAPI backend (26 endpoints)
│
├── lib/
│   ├── __init__.py
│   ├── auth.py              # JWT + RBAC
│   └── database.py          # Supabase client
│
├── db/
│   ├── schema.sql           # Database schema (15 tables)
│   ├── seed.sql             # Seed data (42 stops, 8 routes, 24 vehicles)
│   └── gtfs/                # Standard GTFS feed
│       ├── agency.txt
│       ├── stops.txt
│       ├── routes.txt
│       ├── trips.txt
│       ├── stop_times.txt
│       ├── calendar.txt
│       └── feed_info.txt
│
└── public/
    ├── index.html           # Public tracking dashboard
    ├── admin/
    │   └── index.html       # Admin operations center
    ├── passenger/
    │   ├── index.html       # Passenger PWA
    │   └── manifest.json
    └── driver/
        ├── index.html       # Driver PWA
        └── manifest.json
```

---

## What's Next After Deployment

1. **Change default passwords** in Supabase users table
2. **Test the simulator** — verify vehicles appear on the map
3. **Test with a real phone** — install OsmAnd, point to Traccar, see your position on the dashboard
4. **Share the URL** — the public dashboard works for anyone with the link
5. **Add your domain** — Vercel Settings → Domains → add your custom domain when ready

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| API returns 500 | Check Vercel logs: `vercel logs` — likely missing env vars |
| Map is blank | Check browser console — MapLibre needs HTTPS or localhost |
| No vehicles on map | Run the simulator or check that seed data was loaded |
| Login fails | Verify the users table has the seed admin user |
| PostGIS error | Make sure you ran `CREATE EXTENSION postgis` in Supabase |
| SSE disconnects | Normal on Vercel — client auto-reconnects every 25s |
