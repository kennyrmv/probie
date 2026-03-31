"""
Unit tests for data_collector.py.

Tests the structured data collection layer that gathers API data for Claude analysis.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resolver.data_collector import collect_match_data, query_form, query_h2h


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _make_match(
    home="Arsenal",
    away="Chelsea",
    kickoff=None,
    lineup_data=None,
    analysis_data=None,
    competition="Premier League",
):
    match = MagicMock()
    match.id = "test-uuid-123"
    match.home_team = home
    match.away_team = away
    match.kickoff_utc = kickoff or datetime(2026, 3, 31, 15, 0, tzinfo=timezone.utc)
    match.competition = competition
    match.lineup_data = lineup_data
    match.analysis_data = analysis_data
    return match


def _make_historical(home_name, away_name, home_goals, away_goals, date_str, competition="PL"):
    row = MagicMock()
    row.home_team_name = home_name
    row.away_team_name = away_name
    row.home_goals = home_goals
    row.away_goals = away_goals
    row.date = datetime.fromisoformat(date_str)
    row.competition = competition
    return row


def _lineup_data_confirmed():
    return {
        "source": "api-football",
        "lineup_confirmed": True,
        "home_formation": "4-3-3",
        "away_formation": "4-2-3-1",
        "home_starters": [
            {"name": "Raya", "position": "G"},
            {"name": "White", "position": "D"},
            {"name": "Saliba", "position": "D"},
            {"name": "Gabriel", "position": "D"},
            {"name": "Timber", "position": "D"},
            {"name": "Rice", "position": "M"},
            {"name": "Odegaard", "position": "M"},
            {"name": "Havertz", "position": "M"},
            {"name": "Saka", "position": "F"},
            {"name": "Jesus", "position": "F"},
            {"name": "Martinelli", "position": "F"},
        ],
        "away_starters": [
            {"name": "Sanchez", "position": "G"},
            {"name": "James", "position": "D"},
            {"name": "Fofana", "position": "D"},
            {"name": "Colwill", "position": "D"},
            {"name": "Cucurella", "position": "D"},
            {"name": "Caicedo", "position": "M"},
            {"name": "Fernandez", "position": "M"},
            {"name": "Palmer", "position": "M"},
            {"name": "Madueke", "position": "F"},
            {"name": "Jackson", "position": "F"},
            {"name": "Neto", "position": "F"},
        ],
        "home_subs": [{"name": "Nketiah"}, {"name": "Trossard"}],
        "away_subs": [{"name": "Mudryk"}, {"name": "Sterling"}],
        "home_missing": [{"name": "Tomiyasu", "reason": "injury"}],
        "away_missing": [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# query_h2h
# ─────────────────────────────────────────────────────────────────────────────


class TestQueryH2H:
    def test_returns_h2h_matches(self):
        db = MagicMock()
        rows = [
            _make_historical("Arsenal", "Chelsea", 2, 1, "2025-12-01"),
            _make_historical("Chelsea", "Arsenal", 0, 0, "2025-09-15"),
            _make_historical("Arsenal", "Chelsea", 3, 2, "2025-03-01"),
        ]
        db.query.return_value.order_by.return_value.all.return_value = rows
        result = query_h2h(db, "Arsenal", "Chelsea")
        assert len(result) == 3
        assert result[0]["score"] == "2-1"

    def test_returns_empty_when_too_few_matches(self):
        db = MagicMock()
        rows = [_make_historical("Arsenal", "Chelsea", 2, 1, "2025-12-01")]
        db.query.return_value.order_by.return_value.all.return_value = rows
        result = query_h2h(db, "Arsenal", "Chelsea")
        assert result == []


# ─────────────────────────────────────────────────────────────────────────────
# query_form
# ─────────────────────────────────────────────────────────────────────────────


class TestQueryForm:
    def test_computes_form_correctly(self):
        db = MagicMock()
        rows = [
            _make_historical("Arsenal", "Tottenham", 3, 0, "2025-12-01"),  # W
            _make_historical("Liverpool", "Arsenal", 1, 1, "2025-11-20"),  # D
            _make_historical("Arsenal", "Brighton", 2, 1, "2025-11-10"),   # W
        ]
        db.query.return_value.order_by.return_value.all.return_value = rows
        result = query_form(db, "Arsenal")
        assert result["results"] == "V-E-V"
        assert result["pts_per_game"] == round(7 / 3, 2)
        assert result["matches"] == 3

    def test_returns_empty_when_too_few(self):
        db = MagicMock()
        rows = [_make_historical("Arsenal", "Chelsea", 1, 0, "2025-12-01")]
        db.query.return_value.order_by.return_value.all.return_value = rows
        result = query_form(db, "Arsenal")
        assert result == {}


# ─────────────────────────────────────────────────────────────────────────────
# collect_match_data
# ─────────────────────────────────────────────────────────────────────────────


class TestCollectMatchData:
    def test_returns_structured_dict_with_lineup(self):
        """Full collection with confirmed lineup."""
        db = MagicMock()
        match = _make_match(lineup_data=_lineup_data_confirmed())

        # Mock prediction
        pred = MagicMock()
        pred.model_home_prob = 0.45
        pred.model_draw_prob = 0.28
        pred.model_away_prob = 0.27

        # Return pred for first query chain, None for snapshot queries
        db.query.return_value.filter.return_value.order_by.return_value.first.side_effect = [
            pred,    # Prediction query
            None,    # MarketSnapshot home
            None,    # MarketSnapshot draw
            None,    # MarketSnapshot away
        ]

        # Mock historical for form/h2h (return empty — national teams)
        db.query.return_value.order_by.return_value.all.return_value = []

        result = collect_match_data(match, db)

        assert result["match"]["home"] == "Arsenal"
        assert result["match"]["away"] == "Chelsea"
        assert result["lineups"]["confirmed"] is True
        assert len(result["lineups"]["home_xi"]) == 11
        assert result["injuries"]["home_missing"][0]["name"] == "Tomiyasu"
        assert result["model_probs"]["home"] == 0.45

    def test_returns_empty_lineups_when_no_lineup(self):
        """No lineup data — lineups should be empty dict."""
        db = MagicMock()
        match = _make_match(lineup_data=None)
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        db.query.return_value.order_by.return_value.all.return_value = []

        result = collect_match_data(match, db)
        assert result["lineups"] == {}
        assert result["model_probs"] == {}

    def test_includes_market_probs_and_edge(self):
        """When snapshots exist, market_probs and edge are populated."""
        db = MagicMock()
        match = _make_match()

        pred = MagicMock()
        pred.model_home_prob = 0.50
        pred.model_draw_prob = 0.25
        pred.model_away_prob = 0.25

        snapshot = MagicMock()
        snapshot.polymarket_prob = 0.40
        snapshot.snapshotted_at = datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc)

        # Each call to .first() returns pred or snapshot
        first_mock = MagicMock()
        first_mock.first.side_effect = [pred, snapshot, snapshot, snapshot]
        db.query.return_value.filter.return_value.order_by.return_value = first_mock
        db.query.return_value.order_by.return_value.all.return_value = []

        result = collect_match_data(match, db)
        assert "home" in result["market_probs"]
        assert "home" in result["edge"]
