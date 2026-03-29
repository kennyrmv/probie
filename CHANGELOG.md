# Changelog

All notable changes to EdgeFút are documented here.

## [1.0.1.0] - 2026-03-29

### Added

**Performance Tracker (CLV / Market Drift)**
- New `backend/pipeline/performance.py` — hourly job that resolves match results and computes CLV-style market drift tracking
- Tracks only AI-confirmed signals: `⚡ Edge confirmado` (bet_signal.type = "value") and `💪 Apuesta de fuerza` (bet_signal.type = "strength")
- Requires confirmed lineup data (`match.lineup_data.home_starters`) before logging a prediction — ensures only high-quality analysis is tracked
- Dual-source result resolution: Polymarket settlement (prob > 0.95) with football-data.org fallback
- Market Drift metric: `(closing_poly_prob - entry_poly_prob) × 100pp` — positive = market confirmed our signal before kickoff
- Separate performance breakdown for `edge` vs `fuerza` signals to compare which strategy performs better

**API Endpoints**
- `GET /api/performance` — full performance dashboard (win rate, Brier score, Market Drift, ROI simulation, breakdown by signal type, last 20 resolved signals)
- `POST /api/admin/resolve-results` — manual trigger for result resolution job

**Migrations (006 + 007)**
- Migration 006: adds CLV tracking fields to `calibration_log` (`signal_outcome`, `signal_tier`, `model_prob`, `entry_poly_prob`, `closing_poly_prob`, `clv_pp`) + index on `prediction_id`
- Migration 007: adds `signal_source` ("edge"/"fuerza") and `lineup_confirmed` boolean; clears old tier-based records

**Frontend**
- New `/performance` page — stat cards (win rate, Market Drift, ROI simulation), Brier Score comparison panel, edge vs fuerza breakdown, recent signals table
- Added "Performance →" link to the main navigation header

**Scheduler**
- Hourly cron job (`resolve_results`, runs at :10) that auto-resolves finished matches and writes CalibrationLog entries

### Changed
- `models.py`: `CalibrationLog` expanded with signal metadata + CLV fields + `Boolean` type import
- `resolver.py`: exported `fetch_results_for_date()` for football-data.org result fetching
- `api/routes.py`: widened match window from 2h to 4h post-kickoff for Polymarket settlement capture; `record_match_result` no longer writes incomplete `CalibrationLog` rows (hourly job handles this properly)
- `.gitignore`: added `backend/.lineup_state.json` (runtime state file)

### Fixed
- `_resolve_from_polymarket`: was using `limit(9)` which could miss outcomes if burst of same-outcome snapshots; now queries per-outcome explicitly
- `record_match_result`: score comparison now uses `int()` cast before comparison — prevented wrong outcome on scores like "10" vs "9" (string lexicographic bug)
- LLM trust boundary: `signal_side` from analysis JSONB validated against `("home", "draw", "away")` before writing to DB; `lineup_data_used` gate now cross-checks actual `match.lineup_data` instead of relying solely on LLM self-report
- Duplicate match logging: `already_resolved_matches` set prevents a match with multiple predictions from being logged twice in the same job run

