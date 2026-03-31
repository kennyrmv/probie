"""
Unit tests for api_football.py.

Tests fixture caching and injuries home/away separation fix.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resolver.api_football import (
    fetch_fixtures_for_date,
    fetch_injuries,
    _fixture_cache,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture caching
# ─────────────────────────────────────────────────────────────────────────────


class TestFixtureCaching:
    def setup_method(self):
        _fixture_cache.clear()

    @patch("resolver.api_football._request")
    def test_first_call_hits_api(self, mock_request):
        mock_request.return_value = {"response": [{"fixture": {"id": 1}}]}
        result = fetch_fixtures_for_date("2026-03-31")
        assert len(result) == 1
        mock_request.assert_called_once()

    @patch("resolver.api_football._request")
    def test_second_call_uses_cache(self, mock_request):
        mock_request.return_value = {"response": [{"fixture": {"id": 1}}]}
        fetch_fixtures_for_date("2026-03-31")
        fetch_fixtures_for_date("2026-03-31")
        # API should only be called once — second call hits cache
        mock_request.assert_called_once()

    @patch("resolver.api_football._request")
    def test_different_dates_hit_api_separately(self, mock_request):
        mock_request.return_value = {"response": []}
        fetch_fixtures_for_date("2026-03-31")
        fetch_fixtures_for_date("2026-04-01")
        assert mock_request.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# Injuries home/away separation
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchInjuries:
    @patch("resolver.api_football._request")
    def test_separates_home_away_by_team_id(self, mock_request):
        mock_request.return_value = {
            "response": [
                {"player": {"name": "Saka", "reason": "hamstring"}, "team": {"id": 42}},
                {"player": {"name": "Palmer", "reason": "ankle"}, "team": {"id": 99}},
                {"player": {"name": "Rice", "reason": "knee"}, "team": {"id": 42}},
            ]
        }
        result = fetch_injuries(fixture_id=123, home_team_id=42)
        assert len(result["home_missing"]) == 2
        assert len(result["away_missing"]) == 1
        assert result["home_missing"][0]["name"] == "Saka"
        assert result["away_missing"][0]["name"] == "Palmer"

    @patch("resolver.api_football._request")
    def test_fallback_all_to_home_without_team_id(self, mock_request):
        mock_request.return_value = {
            "response": [
                {"player": {"name": "Saka", "reason": "hamstring"}, "team": {"id": 42}},
                {"player": {"name": "Palmer", "reason": "ankle"}, "team": {"id": 99}},
            ]
        }
        # No home_team_id — legacy behavior
        result = fetch_injuries(fixture_id=123)
        assert len(result["home_missing"]) == 2
        assert len(result["away_missing"]) == 0

    @patch("resolver.api_football._request")
    def test_returns_empty_on_api_error(self, mock_request):
        from resolver.api_football import LineupAPIError
        mock_request.side_effect = LineupAPIError("403 forbidden")
        result = fetch_injuries(fixture_id=123, home_team_id=42)
        assert result == {"home_missing": [], "away_missing": []}
