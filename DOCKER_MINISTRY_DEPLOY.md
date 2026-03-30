# DamascusTransit — Ministry Self-Hosted Deployment Guide

This guide explains how the **Ministry of Transport** can run the DamascusTransit platform on its own infrastructure, independent of Vercel or any external cloud provider.

**Stack:** Nginx (TLS) → FastAPI/Gunicorn → Redis → Supabase PostgreSQL

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Linux server (Ubuntu 22.04 LTS recommended) | Minimum 2 vCPU, 2 GB RAM |
| Docker Engine ≥ 24 | `curl -fsSL https://get.docker.com \| sh` |
| Docker Compose plugin ≥ 2.20 | Included with Docker Engine |
| Supabase project | Free tier at supabase.com, or self-hosted |
| Domain name (optional but recommended) | e.g. `transit.mot.gov.sy` |

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/YOUR-ORG/TransitSystem.git
cd TransitSystem
```

---

## Step 2: Configure Environment

```bash
cp .env.ministry.example .env
nano .env   # fill in all required values
```

Required variables:

| Variable | Where to get it |
|----------|----------------|
| `SUPABASE_URL` | Supabase dashboard → Settings → API |
| `SUPABASE_KEY` | Supabase dashboard → Settings → API (anon key) |
| `SUPABASE_SERVICE_KEY` | Supabase dashboard → Settings → API (service_role) |
| `SUPABASE_ANON_KEY` | Same as `SUPABASE_KEY` |
| `JWT_SECRET` | `openssl rand -hex 32` |
| `ALLOWED_ORIGINS` | Your Ministry domain(s), comma-separated |

---

## Step 3: Set Up SSL Certificates

**Option A — Let's Encrypt (production, requires a public domain):**

```bash
bash scripts/setup-ssl.sh --domain transit.mot.gov.sy
```

**Option B — Self-signed certificate (internal networks / staging):**

```bash
bash scripts/setup-ssl.sh
```

Certificates are written to `nginx/ssl/` and mounted into the Nginx container.

---

## Step 4: Set Up the Database

Connect to your Supabase project and run the following SQL files in order:

```bash
# From the Supabase SQL Editor:
# 1. Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

# 2. Run schema
# Paste the contents of db/schema.sql

# 3. Run seed data
# Paste the contents of db/seed.sql

# 4. Enable realtime
ALTER PUBLICATION supabase_realtime ADD TABLE vehicle_positions_latest;
ALTER PUBLICATION supabase_realtime ADD TABLE alerts;
```

---

## Step 5: Start the Stack

```bash
bash scripts/ministry-deploy.sh start
```

This builds the API image, starts Redis and Nginx, and runs health checks. First boot takes ~60 seconds.

Verify everything is running:

```bash
bash scripts/ministry-deploy.sh status
bash scripts/ministry-deploy.sh health
```

Expected output from `health`:
```json
{"status": "ok", "database": "connected", "redis": "connected"}
```

---

## Step 6: Verify the Deployment

| URL | What to expect |
|-----|---------------|
| `https://YOUR-DOMAIN/` | Public tracking dashboard |
| `https://YOUR-DOMAIN/admin/` | Admin operations center |
| `https://YOUR-DOMAIN/passenger/` | Passenger mobile PWA |
| `https://YOUR-DOMAIN/driver/` | Driver companion PWA |
| `https://YOUR-DOMAIN/api/health` | `{"status": "ok"}` |
| `https://YOUR-DOMAIN/docs` | Swagger API documentation |

---

## Architecture

```
Internet
   │
   ▼
[Nginx :443]  ←── TLS termination, static files, rate limiting
   │
   ├─── /          → public/ (static HTML, served by Nginx directly)
   └─── /api/*     → [API :8000] (FastAPI + 4 Gunicorn workers)
                            │
                      [Redis :6379]  ←── local cache (5s vehicle TTL)
                            │
                      [Supabase]     ←── PostgreSQL + PostGIS (external)
```

---

## Daily Operations

| Task | Command |
|------|---------|
| View live logs | `bash scripts/ministry-deploy.sh logs` |
| Restart after config change | `bash scripts/ministry-deploy.sh restart` |
| Apply code update | `bash scripts/ministry-deploy.sh update` |
| Stop everything | `bash scripts/ministry-deploy.sh stop` |
| Check health | `bash scripts/ministry-deploy.sh health` |

---

## Updating the Platform

```bash
git pull origin main
bash scripts/ministry-deploy.sh update
```

The `update` command rebuilds only the API image, then performs a rolling restart. Nginx and Redis are not interrupted.

---

## Security Hardening Checklist

- [ ] Change all default passwords in `db/seed.sql` before first use
- [ ] Set `ALLOWED_ORIGINS` to only your Ministry domain(s)
- [ ] Use a strong (64+ char) random `JWT_SECRET`
- [ ] Keep `SUPABASE_SERVICE_KEY` secret — it bypasses Row Level Security
- [ ] Enable Ubuntu automatic security updates: `unattended-upgrades`
- [ ] Configure a firewall: allow only ports 80, 443, and SSH from trusted IPs
- [ ] Rotate the JWT secret quarterly; existing tokens will be invalidated

---

## Resource Requirements

| Component | RAM | CPU |
|-----------|-----|-----|
| API (4 workers) | 256–512 MB | 1–2 cores |
| Redis | 128 MB | minimal |
| Nginx | 32–64 MB | minimal |
| **Total** | **~700 MB** | **2 cores** |

A 2 vCPU / 2 GB RAM VPS handles ~500 concurrent users comfortably.
Scale to 4 vCPU / 4 GB RAM for 1,000+ concurrent users.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `502 Bad Gateway` | API is not healthy — check `ministry-deploy.sh logs` |
| API returns 500 | Missing environment variable — re-check `.env` |
| SSL certificate errors | Re-run `setup-ssl.sh`; ensure ports 80/443 are open |
| Redis connection refused | Redis container not healthy — `docker compose -f docker-compose.prod.yml restart redis` |
| Map shows no vehicles | Run the simulator in `damascus-transit-demo/` pointing at your server URL |
| Login fails | Verify `db/seed.sql` was applied and passwords match |

---

## Backup & Recovery

The platform stores all data in Supabase. To back up:

1. **Enable Supabase PITR** (Point-in-Time Recovery) in your Supabase dashboard.
2. **Export schema and seed data** are already version-controlled in `db/`.
3. For disaster recovery, create a new Supabase project, run `db/schema.sql` + `db/seed.sql`, and update `.env` with new credentials.

---

## Support

For technical issues, contact the DamascusTransit engineering team or raise an issue in the project repository.
