# Test Results — Latest Run

**Date:** 2026-04-02
**Time:** 12:15 +03 (Damascus)
**Run by:** Debug Tester agent (DAM-183)

## Summary

| Metric | Value |
|---|---|
| Total tests | 114 |
| Passed | 114 |
| Failed | 0 |
| Errors | 0 |
| Execution time | 81.98s |

**Result: ALL TESTS PASSING**

## Test Files

| File | Tests | Result |
|---|---|---|
| `tests/test_admin_coverage.py` | 26 | PASSED |
| `tests/test_api_contract.py` | 40 | PASSED |
| `tests/test_gtfs_rt.py` | 9 | PASSED |
| `tests/test_happy_paths.py` | 30 | PASSED |
| `tests/test_ws.py` | 9 | PASSED |

## Warnings (Non-blocking)

The following deprecation warnings are present but do not affect test outcomes:

- `datetime.utcnow()` deprecated in Python 3.14 — appears in `api/core/auth.py`, `api/index.py`, `api/routers/admin.py`, `api/routers/driver.py`, `api/routers/health.py`, `api/routers/stats.py`
- `@app.on_event("startup")` deprecated — use lifespan handlers instead (`api/index.py`)
- `TRACCAR_WEBHOOK_SECRET` not set — Traccar webhook endpoints will reject requests until configured
- `HTTP_422_UNPROCESSABLE_ENTITY` constant renamed to `HTTP_422_UNPROCESSABLE_CONTENT` in newer FastAPI

## New Failures vs Previous Run

None — no regressions detected.

## Environment

- Python: 3.14.2
- pytest: 9.0.2
- Platform: darwin
