# TODOS

## Tests

✅ **P0 DONE — Fix pre-existing test failures in test_resolver.py** (2026-03-29)
- Root cause: mock `startTime` was `"2099-12-31"` (beyond `_is_upcoming`'s 7-day window) → events were filtered out → result `[]` ≠ expected
- Fix: use `datetime.now() + timedelta(days=1)` in mock fixtures; update assertions to check by `id` instead of full dict equality
- All 28 tests green

## Sprint Queue

**P1 — Arbitrage Scanner (Polymarket)**
- Scan Polymarket for arbitrage opportunities across outcomes
- Deferred from performance tracker sprint

## Completed

