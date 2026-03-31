"""
Unit tests for match_analyst_v2.py.

Tests the structured Claude analyst that receives API data instead of web searches.
"""

from __future__ import annotations

import json
import sys
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from resolver.match_analyst_v2 import analyze


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def _match_data_full():
    """Complete match data with all fields populated."""
    return {
        "match": {
            "home": "Arsenal",
            "away": "Chelsea",
            "competition": "Premier League",
            "kickoff": "31 March 2026, 15:00 UTC",
        },
        "lineups": {
            "home_formation": "4-3-3",
            "away_formation": "4-2-3-1",
            "home_xi": ["Raya", "White", "Saliba", "Gabriel", "Timber",
                        "Rice", "Odegaard", "Havertz", "Saka", "Jesus", "Martinelli"],
            "away_xi": ["Sanchez", "James", "Fofana", "Colwill", "Cucurella",
                        "Caicedo", "Fernandez", "Palmer", "Madueke", "Jackson", "Neto"],
            "home_subs": ["Nketiah", "Trossard"],
            "away_subs": ["Mudryk", "Sterling"],
            "confirmed": True,
        },
        "injuries": {
            "home_missing": [{"name": "Tomiyasu", "reason": "injury"}],
            "away_missing": [],
        },
        "form": {
            "home": "V-V-E-V-D · 2.2 pts/j",
            "away": "V-D-V-V-E · 2.0 pts/j",
        },
        "h2h": [
            {"date": "2025-12-01", "home": "Arsenal", "away": "Chelsea", "score": "2-1", "competition": "PL"},
            {"date": "2025-09-15", "home": "Chelsea", "away": "Arsenal", "score": "0-0", "competition": "PL"},
        ],
        "model_probs": {"home": 0.45, "draw": 0.28, "away": 0.27},
        "market_probs": {"home": 0.38, "draw": 0.30, "away": 0.32},
        "edge": {"home": "+7.0pp", "draw": "-2.0pp", "away": "-5.0pp"},
    }


def _match_data_minimal():
    """Minimal match data without lineup or form."""
    return {
        "match": {
            "home": "Japan",
            "away": "South Korea",
            "competition": "Friendly",
            "kickoff": "31 March 2026, 10:00 UTC",
        },
        "lineups": {},
        "injuries": {"home_missing": [], "away_missing": []},
        "form": {},
        "h2h": [],
        "model_probs": {"home": 0.40, "draw": 0.25, "away": 0.35},
        "market_probs": {"home": 0.35, "draw": 0.30, "away": 0.35},
        "edge": {"home": "+5.0pp", "draw": "-5.0pp", "away": "0.0pp"},
    }


def _mock_claude_response(analysis_dict: dict) -> MagicMock:
    """Create a mock Anthropic response with JSON content."""
    response = MagicMock()
    content_block = MagicMock()
    content_block.text = json.dumps(analysis_dict)
    response.content = [content_block]
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAnalyze:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("resolver.match_analyst_v2.anthropic.Anthropic")
    def test_full_analysis_with_lineup(self, mock_anthropic_cls):
        """Claude receives structured data and returns valid analysis."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        expected = {
            "home_lineup": ["Raya", "White", "Saliba"],
            "away_lineup": ["Sanchez", "James", "Fofana"],
            "home_missing": [{"name": "Tomiyasu", "reason": "injury"}],
            "away_missing": [],
            "top_players_home": [
                {"name": "Saka", "position": "DEL", "impact": "key creator", "form": "good"}
            ],
            "top_players_away": [
                {"name": "Palmer", "position": "MED", "impact": "top scorer", "form": "excellent"}
            ],
            "form_home": "V-V-E-V-D · 2.2 pts/j",
            "form_away": "V-D-V-V-E · 2.0 pts/j",
            "context": "London derby",
            "key_factors": ["Saka form", "Palmer consistency", "Home advantage"],
            "prob_adjustment": {"home": 0.03, "draw": -0.01, "away": -0.02, "reasoning": "Home XI stronger"},
            "bet_signal": {
                "type": "value",
                "side": "home",
                "confidence": "media",
                "reasoning": "Market underprices Arsenal at home",
                "strength_reasons": [],
            },
            "lineup_confirmed": True,
            "confidence": "media",
            "sources": [],
        }
        mock_client.messages.create.return_value = _mock_claude_response(expected)

        result = analyze(_match_data_full())

        assert result["bet_signal"]["type"] == "value"
        assert result["lineup_confirmed"] is True
        assert result["lineup_data_used"] is True
        assert result["source"] == "structured-api"
        assert "analyzed_at" in result

        # Verify Claude was called with structured data, not web search
        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "PARTIDO: Arsenal vs Chelsea" in prompt
        assert "XI OFICIAL CONFIRMADO" in prompt
        assert "DuckDuckGo" not in prompt

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("resolver.match_analyst_v2.anthropic.Anthropic")
    def test_minimal_analysis_without_lineup(self, mock_anthropic_cls):
        """Analysis works with minimal data (no lineup)."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        expected = {
            "home_lineup": [],
            "away_lineup": [],
            "home_missing": [],
            "away_missing": [],
            "top_players_home": [],
            "top_players_away": [],
            "form_home": "",
            "form_away": "",
            "context": "Asian rivalry friendly",
            "key_factors": ["Unknown lineups"],
            "prob_adjustment": {"home": 0.0, "draw": 0.0, "away": 0.0, "reasoning": "No data"},
            "bet_signal": {"type": "none", "side": None, "confidence": "baja", "reasoning": "Insufficient data", "strength_reasons": []},
            "lineup_confirmed": False,
            "confidence": "baja",
            "sources": [],
        }
        mock_client.messages.create.return_value = _mock_claude_response(expected)

        result = analyze(_match_data_minimal())

        assert result["lineup_confirmed"] is False
        assert result["lineup_data_used"] is False

    def test_raises_without_api_key(self):
        """Should raise ValueError if ANTHROPIC_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                analyze(_match_data_full())

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("resolver.match_analyst_v2.anthropic.Anthropic")
    def test_prompt_includes_structured_sections(self, mock_anthropic_cls):
        """Verify the prompt sent to Claude contains all structured sections."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response({
            "home_lineup": [], "away_lineup": [], "home_missing": [], "away_missing": [],
            "top_players_home": [], "top_players_away": [],
            "form_home": "", "form_away": "", "context": "", "key_factors": [],
            "prob_adjustment": {"home": 0, "draw": 0, "away": 0, "reasoning": ""},
            "bet_signal": {"type": "none", "side": None, "confidence": "baja", "reasoning": "", "strength_reasons": []},
            "lineup_confirmed": True, "confidence": "baja", "sources": [],
        })

        analyze(_match_data_full())

        call_args = mock_client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]

        # All structured sections should be present
        assert "PARTIDO:" in prompt
        assert "XI OFICIAL CONFIRMADO:" in prompt
        assert "LESIONES/BAJAS:" in prompt
        assert "FORMA RECIENTE:" in prompt
        assert "H2H" in prompt
        assert "PROBABILIDADES MODELO vs MERCADO:" in prompt
        assert "modelo=" in prompt
        assert "mercado=" in prompt
        assert "edge=" in prompt

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("resolver.match_analyst_v2.anthropic.Anthropic")
    def test_max_tokens_is_smaller_than_v1(self, mock_anthropic_cls):
        """v2 uses max_tokens=2500 (vs v1's 3000) — structured input needs less output."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response({
            "home_lineup": [], "away_lineup": [], "home_missing": [], "away_missing": [],
            "top_players_home": [], "top_players_away": [],
            "form_home": "", "form_away": "", "context": "", "key_factors": [],
            "prob_adjustment": {"home": 0, "draw": 0, "away": 0, "reasoning": ""},
            "bet_signal": {"type": "none", "side": None, "confidence": "baja", "reasoning": "", "strength_reasons": []},
            "lineup_confirmed": False, "confidence": "baja", "sources": [],
        })

        analyze(_match_data_minimal())

        call_args = mock_client.messages.create.call_args
        assert call_args.kwargs["max_tokens"] == 2500


class TestAnalyzeAPIFootballIntegration:
    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("resolver.match_analyst_v2.anthropic.Anthropic")
    def test_strength_signal_includes_reasons(self, mock_anthropic_cls):
        """Strength signals must include strength_reasons list."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        expected = {
            "home_lineup": ["Raya", "White", "Saliba"],
            "away_lineup": ["Sanchez"],
            "home_missing": [],
            "away_missing": [],
            "top_players_home": [],
            "top_players_away": [],
            "form_home": "V-V-V-V-V",
            "form_away": "D-D-D-D-D",
            "context": "Arsenal dominant",
            "key_factors": ["Form gap"],
            "prob_adjustment": {"home": 0.05, "draw": -0.02, "away": -0.03, "reasoning": "Arsenal superior"},
            "bet_signal": {
                "type": "strength",
                "side": "home",
                "confidence": "alta",
                "reasoning": "Arsenal clearly superior",
                "strength_reasons": ["5 wins in a row", "Chelsea 5 losses", "Home advantage"],
            },
            "lineup_confirmed": True,
            "confidence": "alta",
            "sources": [],
        }
        mock_client.messages.create.return_value = _mock_claude_response(expected)

        result = analyze(_match_data_full())

        assert result["bet_signal"]["type"] == "strength"
        assert len(result["bet_signal"]["strength_reasons"]) >= 3
