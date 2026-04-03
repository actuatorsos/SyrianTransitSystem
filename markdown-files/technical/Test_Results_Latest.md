# Test Results — Latest Run

**Date:** 2026-04-03
**Time:** 12:03 +03 (Damascus)
**Run by:** Debug Tester agent ([DAM-224](/DAM/issues/DAM-224))

## Summary

| Metric | Value |
|---|---|
| Total tests | 249 |
| Passed | 241 |
| Failed | 8 |
| Errors | 0 |
| Execution time | 839.65s (13m 59s) |

**Result: 8 FAILURES — all in `test_sse_stream.py` (passenger PWA SSE client)**

## Test Files

| File | Tests | Passed | Failed | Result |
|---|---|---|---|---|
| `tests/test_admin_coverage.py` | 42 | 42 | 0 | PASSED |
| `tests/test_api_contract.py` | 42 | 42 | 0 | PASSED |
| `tests/test_auth_flow.py` | 18 | 18 | 0 | PASSED |
| `tests/test_driver_pwa.py` | 33 | 33 | 0 | PASSED |
| `tests/test_gtfs_rt.py` | 9 | 9 | 0 | PASSED |
| `tests/test_gtfs_static.py` | 29 | 29 | 0 | PASSED |
| `tests/test_happy_paths.py` | 30 | 30 | 0 | PASSED |
| `tests/test_sse_stream.py` | 37 | 29 | 8 | FAILED |
| `tests/test_ws.py` | 9 | 9 | 0 | PASSED |

## Failures

All 8 failures are in `tests/test_sse_stream.py` in classes `TestSSEReconnection` and `TestConnectionStatusBarLogic`.

These tests inspect `damascus-transit-platform/public/passenger/index.html` for the following SSE client patterns that are **not yet implemented**:

| Test | Expected Pattern | Status |
|---|---|---|
| `test_sse_url_constant_defined` | `SSE_URL` constant defined | FAIL |
| `test_sse_url_references_api_stream` | `/api/stream` in passenger source | FAIL |
| `test_connect_sse_function_defined` | `function connectSSE` defined | FAIL |
| `test_event_source_instantiation` | `new EventSource(SSE_URL)` | FAIL |
| `test_onmessage_parses_json` | `JSON.parse(event.data)` | FAIL |
| `test_onerror_schedules_reconnect` | `eventSource.onerror` + `setTimeout` | FAIL |
| `test_reconnection_logic_closes_previous_event_source` | `eventSource.close()` guard | FAIL |
| `test_reconnection_timeout_is_5_seconds` | `setTimeout(connectSSE, 5000)` | FAIL |

**Root cause:** The passenger PWA (`passenger/index.html`) uses MapLibre GL and draws vehicle positions but does not yet implement an SSE client with the structured `connectSSE()` / auto-reconnect pattern that these tests require.

**Bug issue filed:** See Apps Builder for implementation task.

## New Failures vs Previous Run (2026-04-02)

The previous run covered 114 tests across 5 files (all passing). The current run added 4 new test files:
- `test_auth_flow.py` — 18 new tests, all passing
- `test_driver_pwa.py` — 33 new tests, all passing
- `test_gtfs_static.py` — 29 new tests, all passing
- `test_sse_stream.py` — 37 new tests, **8 failing**

The 8 failures are in **new tests**, not regressions from previously passing tests. However, they expose a genuine missing implementation in the passenger PWA SSE client.

## Warnings (Non-blocking)

- `datetime.utcnow()` deprecated in Python 3.14 — appears in multiple `api/routers/` files and `api/core/auth.py`
- `@app.on_event("startup")` deprecated — use lifespan handlers (`api/index.py`)
- `TRACCAR_WEBHOOK_SECRET` not set — Traccar webhook endpoints will reject requests until configured
- `HTTP_422_UNPROCESSABLE_ENTITY` renamed to `HTTP_422_UNPROCESSABLE_CONTENT` in newer FastAPI

## Environment

- Python: 3.14.2
- pytest: 9.0.2
- Platform: darwin
