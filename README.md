<p align="center">
  <h1 align="center">DamascusTransit</h1>
  <p align="center">
    Real-time GPS tracking and fleet management for public transit in Damascus, Syria
    <br />
    <strong>نظام النقل العام في دمشق</strong>
  </p>
  <p align="center">
    <a href="#quick-start">Quick Start</a> &middot;
    <a href="#api-reference">API Reference</a> &middot;
    <a href="DEPLOY.md">Deploy Guide</a> &middot;
    <a href="CONTRIBUTING.md">Contributing</a>
  </p>
</p>

---

DamascusTransit is an open-source platform that brings real-time vehicle tracking, route management, and fleet analytics to Damascus's public transportation network. Built with FastAPI, Supabase (PostgreSQL + PostGIS), and MapLibre GL JS, it runs on free-tier infrastructure and scales to 500+ vehicles.

The system covers the full transit lifecycle: passengers find routes and track buses in real time, drivers manage trips from a mobile PWA, dispatchers monitor the fleet and respond to alerts, and administrators manage users, vehicles, and analytics.

## Features

- **Real-time vehicle tracking** — GPS positions streamed via Server-Sent Events (SSE), displayed on an interactive MapLibre GL JS map
- **8 Damascus routes, 42 stops** — Pre-seeded with real route data covering major corridors (Mezzeh, Malki, Bab Touma, Hamra, and more)
- **4 web applications** — Public dashboard, admin panel, passenger PWA, and driver PWA
- **Role-based access control** — JWT authentication with 4 roles: admin, dispatcher, driver, viewer
- **IoT integration** — Traccar GPS webhook support with HMAC signature verification
- **Spatial queries** — PostGIS-powered nearest-stop finder, ETA estimation, and route geometry
- **GTFS feed** — Standard General Transit Feed Specification data, ready for Google Maps submission
- **Bilingual** — Arabic and English throughout (IBM Plex Sans Arabic)
- **PWA support** — Passenger and driver apps work offline with service workers
- **Fleet analytics** — Trip history, on-time performance, speed violations, route deviation alerts
- **Free to deploy** — Runs on Vercel (serverless) + Supabase free tiers at $0/month

## Architecture

```
┌─────────────┐     ┌───────────────────────────────────┐
│  Passengers  │────>│  Vercel (Frontend)                │
│  (PWA)       │     │  ├── /           Dashboard        │
│              │     │  ├── /passenger/ PWA              │
└─────────────┘     │  ├── /driver/    PWA              │
                     │  └── /admin/    Operations        │
┌─────────────┐     │                                    │
│   Drivers    │────>│  Vercel (Serverless API)          │
│  (PWA)       │     │  └── /api/*    FastAPI (26 endpoints)
└─────────────┘     └──────────┬────────────────────────┘
                               │
                    ┌──────────▼────────────────────────┐
                    │  Supabase                          │
                    │  ├── PostgreSQL 16 + PostGIS       │
                    │  ├── 15 tables + RLS policies      │
                    │  ├── Realtime subscriptions         │
                    │  └── Supavisor connection pooling   │
                    └──────────┬────────────────────────┘
                               │
┌─────────────┐     ┌──────────▼──────────┐
│  GPS Devices │────>│  Traccar Server      │──> Webhook /api/traccar/position
│  (Teltonika) │     └─────────────────────┘
└─────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.11), Pydantic, httpx |
| Database | Supabase PostgreSQL 16 + PostGIS |
| Auth | JWT (PyJWT) + bcrypt + RBAC |
| Frontend | Static HTML + MapLibre GL JS 4.0 |
| Real-time | Server-Sent Events (SSE) |
| IoT | Traccar webhooks (HMAC-signed) |
| Caching | Upstash Redis (serverless) |
| Monitoring | Sentry SDK |
| Deployment | Vercel (serverless) / Docker |
| Maps | OpenStreetMap tiles |

## Quick Start

### Option 1: Docker (recommended for local development)

```bash
git clone https://github.com/actuatorsos/SyrianTransitSystem.git
cd SyrianTransitSystem

# Copy environment template
cp .env.example .env
# Edit .env with your Supabase credentials (see DEPLOY.md)

# Start the API server
docker compose up --build

# Open http://localhost:8000
```

### Option 2: Local Python

```bash
git clone https://github.com/actuatorsos/SyrianTransitSystem.git
cd SyrianTransitSystem

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env

# Run with uvicorn
uvicorn api.index:app --reload --port 8000
```

### Option 3: Deploy to Vercel (production)

See the full [Deployment Guide](DEPLOY.md) for step-by-step instructions. Total cost: **$0** on free tiers.

```bash
vercel
```

### Database Setup

1. Create a [Supabase](https://supabase.com) project (free tier)
2. Enable PostGIS: `CREATE EXTENSION IF NOT EXISTS postgis;`
3. Run `db/schema.sql` in the SQL Editor (15 tables, RLS policies, spatial functions)
4. Run `db/seed.sql` to load Damascus route data (8 routes, 42 stops, 24 vehicles)

## API Reference

The API serves 26 endpoints. Full OpenAPI 3.0 spec available in [`openapi.json`](openapi.json).

### Public Endpoints (no auth required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check with DB status |
| `POST` | `/api/auth/login` | Login, returns JWT |
| `GET` | `/api/routes` | List all routes |
| `GET` | `/api/routes/{id}` | Single route with stops |
| `GET` | `/api/stops` | All stops with coordinates |
| `GET` | `/api/stops/nearest` | Nearest stops (lat/lon, 1km radius) |
| `GET` | `/api/schedules/{route_id}` | Departure schedule |
| `GET` | `/api/vehicles` | All vehicles with positions |
| `GET` | `/api/vehicles/positions` | Raw GPS position data |
| `GET` | `/api/stream` | SSE real-time position stream |
| `GET` | `/api/stats` | Fleet statistics |

### Driver Endpoints (JWT required, `driver` role)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/driver/position` | Update GPS coordinates |
| `POST` | `/api/driver/trip/start` | Begin trip on route |
| `POST` | `/api/driver/trip/end` | End trip with stats |
| `POST` | `/api/driver/trip/passenger-count` | Update occupancy |

### Admin/Dispatcher Endpoints (JWT required, `admin`/`dispatcher` role)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET/POST` | `/api/admin/users` | List/create users |
| `PUT` | `/api/admin/users/{id}` | Update user |
| `GET/POST` | `/api/admin/vehicles` | List/create vehicles |
| `PUT` | `/api/admin/vehicles/{id}` | Update vehicle |
| `POST` | `/api/admin/vehicles/{id}/assign` | Assign driver/route |
| `GET` | `/api/admin/alerts` | Unresolved alerts |
| `PUT` | `/api/admin/alerts/{id}/resolve` | Resolve alert |
| `GET` | `/api/admin/trips` | Historical trip data |
| `GET` | `/api/admin/analytics/overview` | Dashboard summary |

### IoT Endpoints (HMAC-signed)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/traccar/position` | Traccar GPS webhook |
| `POST` | `/api/traccar/event` | Traccar event webhook |

## Web Applications

| App | Path | Description |
|-----|------|-------------|
| **Dashboard** | `/` | Public real-time map with vehicle markers and route overlays |
| **Admin Panel** | `/admin/` | Fleet management, alerts, trip analytics |
| **Passenger PWA** | `/passenger/` | Route lookup, stop finder, fare info, offline support |
| **Driver PWA** | `/driver/` | Trip controls, passenger counting, GPS reporting |

## Database

15 PostgreSQL tables with PostGIS spatial extensions and Row-Level Security:

- `users` — Authentication and role management
- `routes` — Transit routes with LineString geometry
- `stops` — Bus stops with Point coordinates
- `route_stops` — Stop sequences with arrival offsets
- `vehicles` — Fleet inventory with GPS device mapping
- `vehicle_positions` — Historical GPS position log
- `vehicle_positions_latest` — Materialized latest positions (trigger-updated)
- `trips` — Trip records with passenger counts and on-time metrics
- `alerts` — Speed violations, route deviations, SOS, breakdowns
- `geofences` — Zone/depot/terminal polygons with speed limits
- `schedules` — Weekly departure frequencies
- `audit_log` — User action tracking (JSONB details)

Key spatial functions:
- `upsert_vehicle_position()` — Atomic GPS insert + latest position update
- `find_nearest_stops()` — ST_DWithin query within configurable radius
- `estimate_arrival()` — ETA from speed + route geometry

## Project Structure

```
SyrianTransitSystem/
├── api/
│   ├── index.py              # FastAPI backend (26 endpoints)
│   └── test.py               # Diagnostic endpoint
├── db/
│   ├── schema.sql            # 15 tables, PostGIS, RLS, functions
│   ├── seed.sql              # 8 routes, 42 stops, 24 vehicles
│   └── gtfs/                 # GTFS feed (agency, stops, routes, trips)
├── public/
│   ├── index.html            # Public tracking dashboard
│   ├── admin/index.html      # Admin operations center
│   ├── passenger/            # Passenger PWA
│   └── driver/               # Driver PWA
├── tests/
│   ├── test_happy_paths.py   # Integration tests
│   ├── test_api_contract.py  # Contract tests (Pact)
│   ├── stub_server.py        # Mock Supabase server
│   └── locustfile.py         # Load testing (1000 users)
├── scripts/                  # Deployment and setup scripts
├── lib/                      # Shared utilities
├── openapi.json              # OpenAPI 3.0 specification
├── docker-compose.yml        # Local development
├── docker-compose.prod.yml   # Production Docker deployment
├── Dockerfile                # Python 3.11-slim + uvicorn
├── vercel.json               # Vercel serverless config
├── requirements.txt          # Python dependencies
├── DEPLOY.md                 # Full deployment guide
└── CONTRIBUTING.md           # Contribution guidelines
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL (use Supavisor pooler URL for scale) |
| `SUPABASE_KEY` | Yes | Supabase anon/public key |
| `SUPABASE_SERVICE_KEY` | Yes | Supabase service role key |
| `JWT_SECRET` | Yes | Secret for JWT token signing |
| `TRACCAR_WEBHOOK_SECRET` | No | HMAC secret for Traccar webhooks |
| `UPSTASH_REDIS_REST_URL` | No | Upstash Redis URL for caching |
| `UPSTASH_REDIS_REST_TOKEN` | No | Upstash Redis auth token |

## Testing

```bash
# Unit and integration tests
pytest tests/ -v

# Load testing (requires running server)
locust -f tests/locustfile.py --host http://localhost:8000
```

## GTFS Feed

The `db/gtfs/` directory contains a complete GTFS feed for Damascus transit routes:

- `agency.txt` — DamascusTransit agency info
- `routes.txt` — 8 bus/microbus routes
- `stops.txt` — 42 stops with coordinates
- `trips.txt` — Trip definitions
- `stop_times.txt` — Arrival/departure times
- `calendar.txt` — Service calendar
- `feed_info.txt` — Feed metadata

This feed can be submitted to Google Maps for official transit directions.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and how to submit pull requests.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [MapLibre GL JS](https://maplibre.org/) — Open-source map rendering
- [Supabase](https://supabase.com/) — Open-source Firebase alternative
- [FastAPI](https://fastapi.tiangolo.com/) — Modern Python web framework
- [OpenStreetMap](https://www.openstreetmap.org/) — Map tile data
- [Traccar](https://www.traccar.org/) — Open-source GPS tracking
- [IBM Plex Sans Arabic](https://fonts.google.com/specimen/IBM+Plex+Sans+Arabic) — Bilingual typography
