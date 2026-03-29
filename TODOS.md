# TODOS

## Tests

**P0 — Fix pre-existing test failures in test_resolver.py**
- `TestFetchPolymarketEvents::test_returns_only_active_and_not_closed`
- `TestFetchPolymarketEvents::test_handles_429_with_exponential_backoff`
- Root cause: mock responses don't include a `startDate` field that passes the time-window filter in `fetch_polymarket_events`. Tests need updated fixtures with a valid future `startDate`.
- Noticed on branch: `feat/performance-tracker-clv` (2026-03-29)
- **Priority:** P0

## Sprint Queue

**P1 — Arbitrage Scanner (Polymarket)**
- Scan Polymarket for arbitrage opportunities across outcomes
- Deferred from performance tracker sprint

**P1 — Backtesting / Historical Validation**
- Replay historical Dixon-Coles predictions against known results
- Validate model calibration on domestic leagues (PL, La Liga)

## Completed

