# Test Results — Latest Run

**Date:** 2026-04-08
**Time:** 14:50 +03 (Damascus)
**Run by:** Debug Tester agent ([DAM-368](/DAM/issues/DAM-368))

## Summary

| Metric | Value |
|---|---|
| Total tests | 307 |
| Passed | 303 |
| Failed | 4 |
| Errors | 0 |
| Execution time | 879.80s (14m 39s) |

**Result: 4 FAILURES — 303/307 passed**

## Test Files

| File | Tests | Passed | Failed | Result |
|---|---|---|---|---|
| `tests/test_admin_coverage.py` | 42 | 42 | 0 | PASSED |
| `tests/test_api_contract.py` | 41 | 41 | 0 | PASSED |
| `tests/test_auth_flow.py` | 22 | 22 | 0 | PASSED |
| `tests/test_driver_analytics.py` | 15 | 15 | 0 | PASSED *(new)* |
| `tests/test_driver_pwa.py` | 28 | 28 | 0 | PASSED |
| `tests/test_eta.py` | 14 | 14 | 0 | PASSED *(new)* |
| `tests/test_gtfs_rt.py` | 9 | 9 | 0 | PASSED |
| `tests/test_gtfs_static.py` | 35 | 35 | 0 | PASSED |
| `tests/test_happy_paths.py` | 29 | 29 | 0 | PASSED |
| `tests/test_security.py` | 29 | 25 | 4 | **FAILED** *(new)* |
| `tests/test_sse_stream.py` | 34 | 34 | 0 | PASSED |
| `tests/test_ws.py` | 9 | 9 | 0 | PASSED |

## New Failures vs Previous Run (2026-04-04)

**4 new failures** in `tests/test_security.py::TestRateLimitHeaders`:

| Test | Failure Reason |
|---|---|
| `test_login_429_includes_retry_after` | `async def` not supported — missing `pytest-asyncio` plugin |
| `test_routes_429_includes_retry_after` | `async def` not supported — missing `pytest-asyncio` plugin |
| `test_vehicles_429_includes_retry_after` | `async def` not supported — missing `pytest-asyncio` plugin |
| `test_gtfs_static_429_includes_retry_after` | `async def` not supported — missing `pytest-asyncio` plugin |

**Root cause:** `tests/test_security.py` uses `@pytest.mark.asyncio` and `async def` test functions but `pytest-asyncio` is not installed. The tests are registered as unknown marks and the async functions cannot run natively.

**Fix:** Add `pytest-asyncio` to `requirements.txt` (or `requirements-dev.txt`) and configure `asyncio_mode = "auto"` in `pytest.ini` / `pyproject.toml`, or add `@pytest.mark.asyncio` decorator support.

Bug issue filed: see [DAM-372](/DAM/issues/DAM-372) *(assigned to Apps Builder)*

## New Tests Since Previous Run

The following test files are new since the 2026-04-04 run:

- `tests/test_driver_analytics.py` — 15 tests, all passing
- `tests/test_eta.py` — 14 tests, all passing
- `tests/test_security.py` — 29 tests, 25 passing, **4 failing**

Total test count grew from 249 → 307 (+58 tests).

## Warnings (Non-blocking)

- `datetime.utcnow()` deprecated in Python 3.14 — appears across multiple API routers and `tests/stub_server.py`
- `@app.on_event("startup")` deprecated — use lifespan handlers (`api/index.py`)
- `pytest.mark.asyncio` unknown mark in `test_security.py` — caused by missing `pytest-asyncio`
- `HTTP_422_UNPROCESSABLE_ENTITY` renamed to `HTTP_422_UNPROCESSABLE_CONTENT` in newer FastAPI

## Environment

- Python: 3.14.2
- pytest: 9.0.2
- Platform: darwin
