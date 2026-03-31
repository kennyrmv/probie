"""
Unit tests for performance.py and fetch_results_for_date().

Coverage:
  - fetch_results_for_date() — happy path, non-200 error, timeout
  - _resolve_from_polymarket() — settled outcome, no settlement
  - _resolve_from_football_data() — happy path, no team match
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resolver.resolver import FootballDataAPIError, fetch_results_for_date
from pipeline.performance import _resolve_from_polymarket, _resolve_from_football_data


# ─────────────────────────────────────────────────────────────────────────────
# fetch_results_for_date
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchResultsForDate:
    def test_happy_path_returns_matches(self):
        """Returns the matches list from the API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "matches": [
                {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
                 "score": {"fullTime": {"home": 2, "away": 1}}}
            ]
        }

        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = fetch_results_for_date("2026-03-01")

        assert len(result) == 1
        assert result[0]["homeTeam"]["name"] == "Arsenal"

    def test_non_200_raises_football_data_error(self):
        """Non-200 status raises FootballDataAPIError."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"

        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            with pytest.raises(FootballDataAPIError, match="403"):
                fetch_results_for_date("2026-03-01")

    def test_timeout_raises_football_data_error(self):
        """Timeout raises FootballDataAPIError."""
        import httpx

        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.get.side_effect = httpx.TimeoutException("timed out")

            with pytest.raises(FootballDataAPIError, match="timed out"):
                fetch_results_for_date("2026-03-01")

    def test_empty_matches_returns_empty_list(self):
        """API response with no matches returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"matches": []}

        with patch("resolver.resolver.httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client
            mock_client.get.return_value = mock_response

            result = fetch_results_for_date("2026-03-01")

        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_from_polymarket
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveFromPolymarket:
    def _make_snapshot(self, prob: float):
        snap = MagicMock()
        snap.polymarket_prob = prob
        return snap

    def _make_db(self, home_prob: float, draw_prob: float, away_prob: float):
        """
        Build a mock DB that returns one snapshot per outcome.
        _resolve_from_polymarket calls .first() once per outcome (home, draw, away)
        in that order — so side_effect drives the sequence.
        """
        db = MagicMock()
        query_chain = MagicMock()
        query_chain.filter.return_value = query_chain
        query_chain.order_by.return_value = query_chain
        # first() is called once per outcome in order: home, draw, away
        query_chain.first.side_effect = [
            self._make_snapshot(home_prob),
            self._make_snapshot(draw_prob),
            self._make_snapshot(away_prob),
        ]
        db.query.return_value = query_chain
        return db

    def test_settled_home_returns_home(self):
        """When home prob > 0.95, returns 'home' immediately."""
        match = MagicMock()
        match.id = "test-id"
        db = self._make_db(home_prob=0.97, draw_prob=0.01, away_prob=0.01)
        result = _resolve_from_polymarket(db, match)
        assert result == "home"

    def test_no_settlement_returns_none(self):
        """When all probs below threshold, returns None."""
        match = MagicMock()
        match.id = "test-id"
        db = self._make_db(home_prob=0.5, draw_prob=0.3, away_prob=0.2)
        result = _resolve_from_polymarket(db, match)
        assert result is None

    def test_exactly_at_threshold_returns_outcome(self):
        """prob == 0.95 (boundary) triggers settlement."""
        match = MagicMock()
        match.id = "test-id"
        db = self._make_db(home_prob=0.5, draw_prob=0.4, away_prob=0.95)
        result = _resolve_from_polymarket(db, match)
        assert result == "away"


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_from_football_data
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveFromFootballData:
    def _make_match(self, home: str, away: str, kickoff_date: str = "2026-03-01"):
        match = MagicMock()
        match.home_team = home
        match.away_team = away
        dt = datetime.fromisoformat(kickoff_date + "T15:00:00+00:00")
        match.kickoff_utc = dt
        return match

    def test_home_win_returns_home(self):
        """2-1 returns ('home', 2, 1)."""
        match = self._make_match("Arsenal", "Chelsea")
        api_result = [
            {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
             "score": {"fullTime": {"home": 2, "away": 1}}}
        ]

        with patch("pipeline.performance.fetch_results_from_espn", return_value=[]), \
             patch("pipeline.performance.fetch_results_for_date", return_value=api_result):
            result = _resolve_from_football_data(match, api_key="test")

        assert result == ("home", 2, 1)

    def test_draw_returns_draw(self):
        """1-1 returns ('draw', 1, 1)."""
        match = self._make_match("Arsenal", "Chelsea")
        api_result = [
            {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
             "score": {"fullTime": {"home": 1, "away": 1}}}
        ]

        with patch("pipeline.performance.fetch_results_from_espn", return_value=[]), \
             patch("pipeline.performance.fetch_results_for_date", return_value=api_result):
            result = _resolve_from_football_data(match, api_key="test")

        assert result == ("draw", 1, 1)

    def test_away_win_returns_away(self):
        """0-2 returns ('away', 0, 2)."""
        match = self._make_match("Arsenal", "Chelsea")
        api_result = [
            {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
             "score": {"fullTime": {"home": 0, "away": 2}}}
        ]

        with patch("pipeline.performance.fetch_results_from_espn", return_value=[]), \
             patch("pipeline.performance.fetch_results_for_date", return_value=api_result):
            result = _resolve_from_football_data(match, api_key="test")

        assert result == ("away", 0, 2)

    def test_no_team_match_returns_none(self):
        """If teams don't match the API result, returns None."""
        match = self._make_match("Arsenal", "Chelsea")
        api_result = [
            {"homeTeam": {"name": "Liverpool"}, "awayTeam": {"name": "Everton"},
             "score": {"fullTime": {"home": 3, "away": 0}}}
        ]

        with patch("pipeline.performance.fetch_results_from_espn", return_value=[]), \
             patch("pipeline.performance.fetch_results_for_date", return_value=api_result):
            result = _resolve_from_football_data(match, api_key="test")

        assert result is None

    def test_api_error_returns_none(self):
        """FootballDataAPIError is swallowed and returns None."""
        match = self._make_match("Arsenal", "Chelsea")

        with patch("pipeline.performance.fetch_results_from_espn",
                   side_effect=FootballDataAPIError("espn fail")), \
             patch("pipeline.performance.fetch_results_for_date",
                   side_effect=FootballDataAPIError("fd fail")):
            result = _resolve_from_football_data(match, api_key="test")

        assert result is None

    def test_espn_takes_priority_over_fd(self):
        """ESPN result is used without calling football-data.org."""
        match = self._make_match("Arsenal", "Chelsea")
        espn_result = [
            {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
             "score": {"fullTime": {"home": 3, "away": 0}}}
        ]

        with patch("pipeline.performance.fetch_results_from_espn", return_value=espn_result) as mock_espn, \
             patch("pipeline.performance.fetch_results_for_date") as mock_fd:
            result = _resolve_from_football_data(match, api_key="test")

        assert result == ("home", 3, 0)
        mock_fd.assert_not_called()  # FD should not be called when ESPN succeeds

    def test_falls_back_to_fd_when_espn_empty(self):
        """If ESPN has no result, falls back to football-data.org."""
        match = self._make_match("Arsenal", "Chelsea")
        fd_result = [
            {"homeTeam": {"name": "Arsenal"}, "awayTeam": {"name": "Chelsea"},
             "score": {"fullTime": {"home": 1, "away": 0}}}
        ]

        with patch("pipeline.performance.fetch_results_from_espn", return_value=[]), \
             patch("pipeline.performance.fetch_results_for_date", return_value=fd_result):
            result = _resolve_from_football_data(match, api_key="test")

        assert result == ("home", 1, 0)
