# Test Results — Latest Run

**Date:** 2026-04-13
**Time:** 08:53 +03 (Damascus)
**Run by:** Debug Tester agent ([DAM-400](/DAM/issues/DAM-400))

## Summary

| Metric | Value |
|---|---|
| Total tests | 307 |
| Passed | 307 |
| Failed | 0 |
| Errors | 0 |
| Execution time | 879.63s (14m 39s) |

**Result: ALL PASS — 307/307**

## Test Files

| File | Tests | Passed | Failed | Result |
|---|---|---|---|---|
| `tests/test_admin_coverage.py` | 42 | 42 | 0 | PASSED |
| `tests/test_api_contract.py` | 41 | 41 | 0 | PASSED |
| `tests/test_auth_flow.py` | 22 | 22 | 0 | PASSED |
| `tests/test_driver_analytics.py` | 15 | 15 | 0 | PASSED |
| `tests/test_driver_pwa.py` | 28 | 28 | 0 | PASSED |
| `tests/test_eta.py` | 14 | 14 | 0 | PASSED |
| `tests/test_gtfs_rt.py` | 9 | 9 | 0 | PASSED |
| `tests/test_gtfs_static.py` | 35 | 35 | 0 | PASSED |
| `tests/test_happy_paths.py` | 29 | 29 | 0 | PASSED |
| `tests/test_security.py` | 29 | 29 | 0 | PASSED *(fixed)* |
| `tests/test_sse_stream.py` | 34 | 34 | 0 | PASSED |
| `tests/test_ws.py` | 9 | 9 | 0 | PASSED |

## Changes vs Previous Run (2026-04-08)

**4 previously failing tests now pass** in `tests/test_security.py::TestRateLimitHeaders`:

| Test | Status |
|---|---|
| `test_login_429_includes_retry_after` | Fixed — now PASSED |
| `test_routes_429_includes_retry_after` | Fixed — now PASSED |
| `test_vehicles_429_includes_retry_after` | Fixed — now PASSED |
| `test_gtfs_static_429_includes_retry_after` | Fixed — now PASSED |

**Fix applied:** Async tests in `TestRateLimitHeaders` were converted to sync (see [DAM-372](/DAM/issues/DAM-372)).

No new failures detected.

## Warnings (Non-blocking)

- `datetime.utcnow()` deprecated in Python 3.14 — appears across multiple API routers and `tests/stub_server.py`
- `@app.on_event("startup")` deprecated — use lifespan handlers (`api/index.py`)
- `HTTP_422_UNPROCESSABLE_ENTITY` renamed to `HTTP_422_UNPROCESSABLE_CONTENT` in newer FastAPI

## Environment

- Python: 3.14.2
- pytest: 9.0.2
- Platform: darwin
