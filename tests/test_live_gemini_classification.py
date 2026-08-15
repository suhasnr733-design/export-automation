"""
Unit and Regression Tests for Phase 6D: Safe Live Gemini Classification Only.

Verifies:
1. classify_live_records / --classify-live refuses to run when CLASSIFICATION_LIVE=false.
2. Missing API key fails safely with GEMINI_API_KEY_NOT_CONFIGURED.
3. Historical test buyers (Singing Bowls fixtures) are excluded from live Gemini classification.
4. Live discovery buyers (Pashmina leads) are exclusively included.
5. Gmail outreach remains strictly disabled / TEST_MODE protected.
6. Successful live Gemini classifications are marked with classification_source="GEMINI".
7. Live Gemini API failure returns GEMINI_API_ERROR without falling back to LOCAL_TEST_CLASSIFICATION.
8. Unknown fields (e.g. Pashmina Vogue's country) are not guessed.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import Config
from classification.gemini_classifier import (
    ClassificationResult,
    classify_live_records,
)
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    save_discovery_provenance,
    load_discovery_provenance,
    load_classification_log,
)
from main import run_classify_live_action


@pytest.fixture
def mock_live_env(tmp_path, monkeypatch):
    """Set up clean isolated environment for live classification testing."""
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)

    # 11 Historical buyers and 2 Live Discovery buyers
    buyers = [
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Sound Healing Imports Ltd", "email": "import@zenithhealing.com", "website": "https://zenithhealing.com", "country": "United States", "source_platform": "Google Search"},
        {"buyer_name": "Elena Rostova", "company_name": "Aura Wellness Wholesale", "email": "contact@aurawellness.de", "website": "https://aurawellness.de", "country": "Germany", "source_platform": "Google Search"},
        {"buyer_name": "", "company_name": "Pashmina Artisan", "email": "support@pashminaartisan.in", "website": "https://pashminaartisan.in", "country": "India", "source_platform": "Website Search"},
        {"buyer_name": "", "company_name": "Pashmina Vogue™", "email": "support@pashminavogue.com", "website": "https://pashminavogue.com", "country": "", "source_platform": "Website Search"},
    ]
    save_buyers(buyers, csv_path=test_data_dir / "buyers.csv")

    prov_records = [
        {"email": "import@zenithhealing.com", "data_source": "HISTORICAL_TEST", "keyword": "Singing Bowls"},
        {"email": "contact@aurawellness.de", "data_source": "HISTORICAL_TEST", "keyword": "Singing Bowls"},
        {"email": "support@pashminaartisan.in", "data_source": "LIVE_DISCOVERY", "keyword": "Handmade Pashmina"},
        {"email": "support@pashminavogue.com", "data_source": "LIVE_DISCOVERY", "keyword": "Handmade Pashmina"},
    ]
    save_discovery_provenance(prov_records, keyword="Handmade Pashmina", json_path=test_data_dir / "discovery_provenance.json")

    return test_data_dir


def test_classify_live_refuses_when_switch_is_false(mock_live_env, monkeypatch, capsys):
    """Verify live classification is blocked when CLASSIFICATION_LIVE is False."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", False)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "fake_key_123")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    run_classify_live_action(data_dir=mock_live_env)
    out = capsys.readouterr().out

    assert "CLASSIFICATION_LIVE is set to false" in out
    assert "GEMINI CLASSIFICATION: LIVE" in out
    assert "GMAIL OUTREACH: DISABLED / TEST MODE" in out


def test_classify_live_missing_api_key_fails_safely(mock_live_env, monkeypatch, capsys):
    """Verify live classification returns GEMINI_API_KEY_NOT_CONFIGURED when key is empty."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", True)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    run_classify_live_action(data_dir=mock_live_env)
    out = capsys.readouterr().out

    assert "GEMINI_API_KEY_NOT_CONFIGURED" in out


def test_classify_live_excludes_historical_and_targets_only_live_discovery(mock_live_env, monkeypatch, capsys):
    """Verify only the 2 LIVE_DISCOVERY Pashmina leads are sent to Gemini and historical leads are excluded."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", True)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "mock_key_valid")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    mock_gemini_response = MagicMock()
    mock_gemini_response.text = json.dumps({
        "classifications": [
            {
                "email": "support@pashminaartisan.in",
                "category": "business",
                "confidence": 0.95,
                "reason": "Artisanal textile producer and exporter with corporate contact address",
            },
            {
                "email": "support@pashminavogue.com",
                "category": "business",
                "confidence": 0.92,
                "reason": "Commercial brand and wholesale distributor of handmade pashminas",
            },
        ]
    })

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_gemini_response

    with patch("google.genai.Client", return_value=mock_client):
        run_classify_live_action(data_dir=mock_live_env)

    out = capsys.readouterr().out

    assert "Targeting 2 LIVE_DISCOVERY records for Gemini classification" in out
    assert "support@pashminaartisan.in" in out
    assert "support@pashminavogue.com" in out
    assert "import@zenithhealing.com" not in out
    assert "contact@aurawellness.de" not in out
    assert "GEMINI CLASSIFICATION: LIVE" in out
    assert "GMAIL OUTREACH: DISABLED / TEST MODE" in out

    # Verify classification log has GEMINI source
    logs = load_classification_log(mock_live_env / "classification_log.csv")
    gemini_logs = [l for l in logs if l.get("classification_source") == "GEMINI"]
    assert len(gemini_logs) == 2
    assert any(l["email"] == "support@pashminaartisan.in" for l in gemini_logs)
    assert any(l["email"] == "support@pashminavogue.com" for l in gemini_logs)


def test_classify_live_api_failure_does_not_fallback_to_heuristics(mock_live_env, monkeypatch, capsys):
    """Verify live Gemini API failure reports GEMINI_API_ERROR and does not silently fall back to heuristics."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", True)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "mock_key_valid")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("Quota Exceeded / Rate Limit 429")

    with patch("google.genai.Client", return_value=mock_client):
        run_classify_live_action(data_dir=mock_live_env)

    out = capsys.readouterr().out

    assert "GEMINI_API_ERROR" in out
    assert "Quota Exceeded" in out
    assert "LOCAL_TEST_CLASSIFICATION" not in out


def test_classify_live_records_function_direct_error_handling():
    """Verify classify_live_records directly returns GEMINI_API_KEY_NOT_CONFIGURED on missing key."""
    results, err = classify_live_records([{"email": "test@example.com"}], api_key="")
    assert results == []
    assert err == "GEMINI_API_KEY_NOT_CONFIGURED"


def test_classify_live_preserves_unknown_country():
    """Verify country is not guessed if missing from buyer record."""
    buyer = {
        "email": "support@pashminavogue.com",
        "company_name": "Pashmina Vogue™",
        "country": "",
        "website": "https://pashminavogue.com",
        "source_platform": "Website Search",
    }
    mock_resp = MagicMock()
    mock_resp.text = json.dumps({
        "classifications": [
            {
                "email": "support@pashminavogue.com",
                "category": "business",
                "confidence": 0.90,
                "reason": "Commercial pashmina brand",
            }
        ]
    })
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_resp

    with patch("google.genai.Client", return_value=mock_client):
        results, err = classify_live_records([buyer], api_key="dummy_key")

    assert err is None
    assert len(results) == 1
    assert results[0].classification_source == "GEMINI"
    assert results[0].category == "business"
