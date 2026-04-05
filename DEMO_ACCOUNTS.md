# Damascus Transit System - Demo Accounts

All demo accounts use the Damascus Transit Authority operator and share the same password.

**Password:** `damascus2025`

> **Warning:** Change all passwords before production deployment.

---

## Demo Credentials

| Role | Email | System Role | Description |
|------|-------|-------------|-------------|
| Admin | `admin@damascus-transit.demo` | `admin` | Full control: manage users, vehicles, routes, view analytics |
| Operator | `operator@damascus-transit.demo` | `dispatcher` | Fleet operations: assign vehicles, manage trips, resolve alerts |
| Driver | `driver@damascus-transit.demo` | `driver` | Mobile: update GPS position, start/end trips, report passenger counts |
| Passenger | `passenger@damascus-transit.demo` | `viewer` | Read-only: view routes, stops, schedules, real-time vehicle positions |

---

## Login URLs

| App | URL |
|-----|-----|
| Main Dashboard | `https://syrian-transit-system.vercel.app/dashboard/` |
| Admin Panel | `https://syrian-transit-system.vercel.app/admin/` |
| Driver PWA | `https://syrian-transit-system.vercel.app/driver/` |
| Passenger PWA | `https://syrian-transit-system.vercel.app/passenger/` |

**API Base URL:** `https://syrian-transit-system.vercel.app/api`

All public endpoints require `?operator=damascus` query parameter.

---

## API Examples

### Login (get JWT token)

```bash
# Admin login
curl -X POST https://syrian-transit-system.vercel.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@damascus-transit.demo", "password": "damascus2025"}'

# Driver login
curl -X POST https://syrian-transit-system.vercel.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "driver@damascus-transit.demo", "password": "damascus2025"}'

# Operator (dispatcher) login
curl -X POST https://syrian-transit-system.vercel.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "operator@damascus-transit.demo", "password": "damascus2025"}'

# Passenger (viewer) login
curl -X POST https://syrian-transit-system.vercel.app/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "passenger@damascus-transit.demo", "password": "damascus2025"}'
```

Response:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "user_id": "uuid",
  "role": "admin"
}
```

### Using the token

```bash
# Save token from login response
TOKEN="<access_token from login response>"

# List routes (public, no auth needed)
curl https://syrian-transit-system.vercel.app/api/routes?operator=damascus

# List all stops
curl https://syrian-transit-system.vercel.app/api/stops?operator=damascus

# Find nearest stops (within 1km of Marjeh Square)
curl "https://syrian-transit-system.vercel.app/api/stops/nearest?operator=damascus&lat=33.5105&lon=36.3025"

# Get fleet statistics
curl https://syrian-transit-system.vercel.app/api/stats?operator=damascus

# Admin: list all users
curl -H "Authorization: Bearer $TOKEN" \
  https://syrian-transit-system.vercel.app/api/admin/users?operator=damascus

# Admin: list vehicles
curl -H "Authorization: Bearer $TOKEN" \
  https://syrian-transit-system.vercel.app/api/admin/vehicles?operator=damascus

# Driver: update GPS position
curl -X POST https://syrian-transit-system.vercel.app/api/driver/position \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"latitude": 33.5105, "longitude": 36.3025, "speed": 30, "heading": 180}'

# Driver: start a trip
curl -X POST https://syrian-transit-system.vercel.app/api/driver/trip/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"route_id": "R001"}'
```

---

## Role Permissions

### Admin (`admin`)
- Manage users (create, update, list)
- Manage vehicles (create, update, assign)
- View analytics and dashboard overview
- Resolve alerts
- View trip history

### Operator/Dispatcher (`dispatcher`)
- Manage vehicles (create, update, assign)
- View and resolve alerts
- View trip history
- Monitor real-time fleet positions

### Driver (`driver`)
- Update own GPS position
- Start and end trips
- Report passenger counts
- View assigned route

### Passenger/Viewer (`viewer`)
- View all routes and stops
- View real-time vehicle positions
- View schedules and fares
- Find nearest stops

---

## Seeding Demo Accounts

To insert demo accounts into the database, run:

```bash
psql "$DATABASE_URL" -f db/demo_accounts.sql
```

Or via Supabase SQL Editor: copy and run the contents of `db/demo_accounts.sql`.

---

## Existing Seed Accounts

The system also ships with 20 seed accounts in `db/seed.sql` (same password: `damascus2025`):

- `admin@damascustransit.sy` (admin)
- `dispatcher@damascustransit.sy` (dispatcher)
- `driver01@damascustransit.sy` through `driver18@damascustransit.sy` (drivers)
