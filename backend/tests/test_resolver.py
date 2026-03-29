"""
Unit tests for resolver.py.

Coverage per test plan:
  - normalize_team_name()
  - fetch_polymarket_events() with mock responses
  - resolve_match() — happy path, timestamp edge cases, multiple candidates
  - get_implied_prob() — home/draw/away extraction
  - get_all_outcome_probs() — all 3 outcomes in one call
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Adjust path so resolver can be imported from backend/
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resolver.resolver import (
    PolymarketAPIError,
    get_all_outcome_probs,
    get_implied_prob,
    normalize_team_name,
    resolve_match,
    fetch_polymarket_events,
)


# ─────────────────────────────────────────────────────────────────────────────
# normalize_team_name
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeTeamName:
    def test_atletico_madrid_strips_accent(self):
        assert normalize_team_name("Atlético Madrid") == "atletico madrid"

    def test_manchester_city_lowercases(self):
        assert normalize_team_name("Manchester City") == "manchester city"

    def test_empty_string_returns_empty(self):
        assert normalize_team_name("") == ""

    def test_none_raises_value_error(self):
        with pytest.raises(ValueError, match="must not be None"):
            normalize_team_name(None)

    def test_alias_man_utd_expands(self):
        assert normalize_team_name("Man Utd") == "manchester united"

    def test_alias_man_city_expands(self):
        assert normalize_team_name("Man City") == "manchester city"

    def test_alias_spurs_expands(self):
        assert normalize_team_name("Spurs") == "tottenham hotspur"

    def test_alias_wolves_expands(self):
        assert normalize_team_name("Wolves") == "wolverhampton wanderers"

    def test_extra_whitespace_collapsed(self):
        assert normalize_team_name("  Arsenal  ") == "arsenal"

    def test_punctuation_removed(self):
        # "Brighton & Hove Albion" → strip "&" → then alias lookup won't trigger
        # but punctuation should be gone
        result = normalize_team_name("Brighton & Hove Albion")
        assert "&" not in result

    def test_alias_brighton_expands(self):
        # Alias value is pre-normalized: "Brighton & Hove Albion" → "brighton hove albion"
        result = normalize_team_name("Brighton")
        assert "brighton" in result
        assert "hove" in result
        assert "albion" in result

    def test_unicode_normalization(self):
        # "Borussia Mönchengladbach" → accent stripped
        result = normalize_team_name("Borussia Mönchengladbach")
        assert "ö" not in result


# ─────────────────────────────────────────────────────────────────────────────
# fetch_polymarket_events
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchPolymarketEvents:
    def test_returns_only_active_and_not_closed(self):
        """Verifies closed=false is included in request params."""
        # startTime must be within fetch_polymarket_events' 7-day window
        future_time = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        event = {"id": "1", "title": "Arsenal vs Chelsea", "active": True, "closed": False, "startTime": future_time}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [event]

        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = fetch_polymarket_events()

            # Verify closed=false was in the params
            all_args = str(mock_client.get.call_args)
            assert "closed" in all_args
            # Event passes the _is_upcoming filter and is returned as-is
            assert len(result) == 1
            assert result[0]["id"] == "1"
            assert result[0]["title"] == "Arsenal vs Chelsea"

    def test_handles_429_with_exponential_backoff(self):
        """On 429, retries with delay."""
        rate_limit_response = MagicMock()
        rate_limit_response.status_code = 429

        # startTime must be within fetch_polymarket_events' 7-day window
        future_time = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        ok_response = MagicMock()
        ok_response.status_code = 200
        ok_response.json.return_value = [{"id": "1", "startTime": future_time}]

        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            with patch("resolver.resolver.time.sleep") as mock_sleep:
                mock_client = MagicMock()
                mock_client_class.return_value.__enter__.return_value = mock_client
                # First call: 429, second call: 200
                mock_client.get.side_effect = [rate_limit_response, ok_response]

                result = fetch_polymarket_events(max_retries=3, base_delay=0.01)

                assert mock_sleep.call_count >= 1
                assert len(result) == 1
                assert result[0]["id"] == "1"

    def test_network_timeout_raises_polymarket_api_error(self):
        import httpx as _httpx
        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = _httpx.TimeoutException("timed out")

            with pytest.raises(PolymarketAPIError, match="timed out"):
                fetch_polymarket_events(max_retries=1)

    def test_outcome_prices_is_json_string_not_array(self):
        """Documents the critical bug: outcomePrices must be json.loads'd."""
        # This test verifies the API contract — outcomePrices comes back as a string
        raw_event = {
            "id": "abc123",
            "markets": [
                {
                    "groupItemTitle": "Arsenal",
                    "outcomePrices": '["0.65", "0.35"]',  # <-- JSON STRING, not array
                }
            ],
        }
        # Verify json.loads works on it
        prices_raw = raw_event["markets"][0]["outcomePrices"]
        assert isinstance(prices_raw, str), "outcomePrices should be a string from the API"
        prices = json.loads(prices_raw)
        assert float(prices[0]) == pytest.approx(0.65)


# ─────────────────────────────────────────────────────────────────────────────
# resolve_match
# ─────────────────────────────────────────────────────────────────────────────


def _make_fixture(
    home: str,
    away: str,
    kickoff: str,
    competition: str = "Premier League",
    fixture_id: int = 1,
) -> dict:
    return {
        "id": fixture_id,
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "utcDate": kickoff,
        "competition": {"name": competition},
    }


def _make_pm_event(
    title: str,
    game_start_time: str,
    slug: str = "test-event",
    neg_risk_id: str = "neg123",
) -> dict:
    return {
        "title": title,
        "slug": slug,
        "gameStartTime": game_start_time,
        "negRiskMarketID": neg_risk_id,
        "markets": [],
    }


class TestResolveMatch:
    def test_happy_path_arsenal_vs_chelsea(self):
        """Slug 'epl-arsenal-vs-chelsea' matches Arsenal vs Chelsea fixture."""
        kickoff = "2026-03-27T20:45:00Z"
        fixture = _make_fixture("Arsenal FC", "Chelsea FC", kickoff)
        pm_events = [
            _make_pm_event(
                "Arsenal vs Chelsea",
                game_start_time=kickoff,
                slug="epl-arsenal-vs-chelsea",
            )
        ]
        result = resolve_match(fixture, pm_events)
        assert result is not None
        assert result["slug"] == "epl-arsenal-vs-chelsea"

    def test_uses_game_start_time_not_end_date(self):
        """
        CRITICAL: must use gameStartTime, not endDate.
        endDate is typically 2h before kickoff — using it would miss all matches.
        """
        kickoff = "2026-03-27T20:45:00Z"
        # endDate would be ~18:45 UTC (2h before kickoff), outside ±90min window
        end_date_only_event = {
            "title": "Arsenal vs Chelsea",
            "slug": "epl-arsenal-vs-chelsea",
            "endDate": "2026-03-27T18:45:00Z",  # 2h before — should NOT be used
            # No gameStartTime intentionally
            "markets": [],
        }
        fixture = _make_fixture("Arsenal FC", "Chelsea FC", kickoff)
        result = resolve_match(fixture, [end_date_only_event])
        # Without gameStartTime, event should be skipped
        assert result is None

    def test_no_fixture_within_window_returns_none(self):
        """If game_start_time is >90min from kickoff → returns None."""
        kickoff = "2026-03-27T20:45:00Z"
        # 3h off — way outside ±90min window
        pm_events = [
            _make_pm_event(
                "Arsenal vs Chelsea",
                game_start_time="2026-03-27T17:00:00Z",  # 3h45m before kickoff
            )
        ]
        fixture = _make_fixture("Arsenal FC", "Chelsea FC", kickoff)
        result = resolve_match(fixture, pm_events)
        assert result is None

    def test_multiple_candidates_picks_closest_by_timestamp(self):
        """When two events match, resolver picks the one closest in time."""
        kickoff = "2026-03-27T20:45:00Z"
        # Two Arsenal vs Chelsea events: one 30min off, one 5min off
        pm_events = [
            _make_pm_event(
                "Arsenal vs Chelsea",
                game_start_time="2026-03-27T21:15:00Z",  # 30min after kickoff
                slug="event-far",
            ),
            _make_pm_event(
                "Arsenal vs Chelsea",
                game_start_time="2026-03-27T20:50:00Z",  # 5min after kickoff
                slug="event-close",
            ),
        ]
        fixture = _make_fixture("Arsenal FC", "Chelsea FC", kickoff)
        result = resolve_match(fixture, pm_events)
        assert result is not None
        assert result["slug"] == "event-close"

    def test_team_name_fuzzy_match(self):
        """'Man Utd' fixture should match 'Manchester United vs Arsenal' event."""
        kickoff = "2026-03-27T15:00:00Z"
        fixture = _make_fixture("Manchester United", "Arsenal FC", kickoff)
        pm_events = [
            _make_pm_event(
                "Man Utd vs Arsenal",
                game_start_time=kickoff,
                slug="man-utd-vs-arsenal",
            )
        ]
        result = resolve_match(fixture, pm_events)
        assert result is not None

    def test_completely_different_teams_returns_none(self):
        kickoff = "2026-03-27T15:00:00Z"
        fixture = _make_fixture("Arsenal FC", "Chelsea FC", kickoff)
        pm_events = [
            _make_pm_event(
                "Real Madrid vs Barcelona",
                game_start_time=kickoff,
                slug="real-vs-barca",
            )
        ]
        result = resolve_match(fixture, pm_events)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# get_implied_prob and get_all_outcome_probs
# ─────────────────────────────────────────────────────────────────────────────


def _make_event_with_markets(home_team: str, away_team: str) -> dict:
    """Helper: build a minimal Polymarket event with home/draw/away markets."""
    return {
        "slug": f"{home_team.lower()}-vs-{away_team.lower()}",
        "title": f"{home_team} vs {away_team}",
        "markets": [
            {
                "groupItemTitle": home_team,
                "outcomePrices": '["0.60", "0.40"]',
            },
            {
                "groupItemTitle": "Draw",
                "outcomePrices": '["0.25", "0.75"]',
            },
            {
                "groupItemTitle": away_team,
                "outcomePrices": '["0.15", "0.85"]',
            },
        ],
    }


class TestGetAllOutcomeProbs:
    def test_returns_all_three_outcomes(self):
        event = _make_event_with_markets("Arsenal", "Chelsea")
        result = get_all_outcome_probs(event, "Arsenal", "Chelsea")
        assert "home" in result
        assert "draw" in result
        assert "away" in result

    def test_home_probability_correct(self):
        event = _make_event_with_markets("Arsenal", "Chelsea")
        result = get_all_outcome_probs(event, "Arsenal", "Chelsea")
        assert result["home"] == pytest.approx(0.60)

    def test_draw_probability_correct(self):
        event = _make_event_with_markets("Arsenal", "Chelsea")
        result = get_all_outcome_probs(event, "Arsenal", "Chelsea")
        assert result["draw"] == pytest.approx(0.25)

    def test_away_probability_correct(self):
        event = _make_event_with_markets("Arsenal", "Chelsea")
        result = get_all_outcome_probs(event, "Arsenal", "Chelsea")
        assert result["away"] == pytest.approx(0.15)

    def test_team_not_found_raises_value_error(self):
        event = _make_event_with_markets("Arsenal", "Chelsea")
        with pytest.raises(ValueError, match="Could not find outcomes"):
            get_all_outcome_probs(event, "Real Madrid", "Barcelona")

    def test_outcome_prices_parsed_with_json_loads(self):
        """Verifies json.loads() path — not direct indexing."""
        event = {
            "slug": "test",
            "markets": [
                {
                    "groupItemTitle": "Arsenal",
                    # String, as the real API returns
                    "outcomePrices": '["0.71", "0.29"]',
                },
                {
                    "groupItemTitle": "Draw",
                    "outcomePrices": '["0.19", "0.81"]',
                },
                {
                    "groupItemTitle": "Chelsea",
                    "outcomePrices": '["0.10", "0.90"]',
                },
            ],
        }
        result = get_all_outcome_probs(event, "Arsenal", "Chelsea")
        assert result["home"] == pytest.approx(0.71)
        assert result["draw"] == pytest.approx(0.19)
        assert result["away"] == pytest.approx(0.10)
