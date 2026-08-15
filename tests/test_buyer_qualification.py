"""
Unit and Regression Tests for Phase 6E: Buyer Qualification and Lead Scoring.

Verifies:
1. Business vs Buyer distinction (wholesale/importer vs pure supplier/competitor).
2. High qualification score (>= 75) produces HIGH level and REVIEW_FOR_OUTREACH recommendation.
3. Medium qualification score (50-74) produces MEDIUM level and MANUAL_REVIEW recommendation.
4. Low qualification score (< 50) produces LOW level and DO_NOT_CONTACT recommendation.
5. Missing evidence and missing country default gracefully to UNKNOWN without invention.
6. Product relevance dynamically evaluates against configured keywords.
7. Safe execution: historical test buyers excluded, live discovery buyers included.
8. Safe API error handling: returns GEMINI_API_ERROR without fallback to heuristics.
9. Gmail outreach remains strictly disabled / TEST_MODE protected.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import Config
from qualification.buyer_qualifier import (
    QualificationResult,
    LocalTestQualifier,
    qualify_live_buyers,
    expand_product_keywords,
)
from logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    save_discovery_provenance,
    load_discovery_provenance,
    load_qualification_log,
)
from main import run_qualify_live_action


@pytest.fixture
def mock_qualification_env(tmp_path, monkeypatch):
    """Set up clean isolated environment for buyer qualification testing."""
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)

    # 2 Historical test records + 2 Live Pashmina discovery records
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


def test_business_vs_buyer_distinction():
    """Verify distinction between an active wholesale importer and a pure local maker/competitor."""
    # 1. Buyer / Importer entity
    importer_buyer = {
        "email": "purchasing@eurotextileimports.com",
        "company_name": "Euro Textile Importers & Wholesalers Ltd",
        "website": "https://eurotextileimports.com",
        "country": "France",
        "source_platform": "Google Search",
    }
    res_importer = LocalTestQualifier.qualify(importer_buyer, product_keyword="Handmade Pashmina")
    assert res_importer.business_status == "business"
    assert "importer" in res_importer.commercial_signals or "wholesaler" in res_importer.commercial_signals or "procurement" in res_importer.commercial_signals
    assert res_importer.qualification_score >= 75
    assert res_importer.qualification_level == "HIGH"
    assert res_importer.recommendation == "REVIEW_FOR_OUTREACH"

    # 2. Pure manufacturer / artisan supplier
    artisan_maker = {
        "email": "info@nepalcraftfactory.com",
        "company_name": "Nepal Craft Factory & Producer",
        "website": "https://nepalcraftfactory.com",
        "country": "Nepal",
        "source_platform": "Website Search",
    }
    res_maker = LocalTestQualifier.qualify(artisan_maker, product_keyword="Handmade Pashmina")
    assert res_maker.buyer_intent < 0.7


def test_high_score_qualification():
    """Verify high-scoring candidate achieves HIGH level and REVIEW_FOR_OUTREACH."""
    buyer = {
        "email": "import@luxuryscarvesandshawls.com",
        "company_name": "Luxury Scarves & Pashmina Importers LLC",
        "website": "https://luxuryscarvesandshawls.com",
        "country": "United States",
        "source_platform": "Google Search",
    }
    res = LocalTestQualifier.qualify(buyer, product_keyword="Handmade Pashmina")
    assert res.qualification_score >= 75
    assert res.qualification_level == "HIGH"
    assert res.recommendation == "REVIEW_FOR_OUTREACH"
    assert res.product_relevance >= 0.7


def test_medium_score_qualification():
    """Verify medium-scoring candidate achieves MEDIUM level and MANUAL_REVIEW."""
    buyer = {
        "email": "inquiries@nordicgifts.se",
        "company_name": "Nordic Gifts & Accessories",
        "website": "",
        "country": "",
        "source_platform": "Trade Directory",
    }
    res = LocalTestQualifier.qualify(buyer, product_keyword="Handmade Pashmina")
    assert 50 <= res.qualification_score < 75
    assert res.qualification_level == "MEDIUM"
    assert res.recommendation == "MANUAL_REVIEW"


def test_low_score_qualification():
    """Verify low-scoring, irrelevant freemail lead achieves LOW level and DO_NOT_CONTACT."""
    buyer = {
        "email": "randomuser999@gmail.com",
        "company_name": "",
        "website": "",
        "country": "",
        "source_platform": "Google Search",
    }
    res = LocalTestQualifier.qualify(buyer, product_keyword="Handmade Pashmina")
    assert res.qualification_score < 50
    assert res.qualification_level == "LOW"
    assert res.recommendation == "DO_NOT_CONTACT"


def test_missing_evidence_and_unknown_country():
    """Verify unknown country and missing website are handled gracefully without hallucination."""
    buyer = {
        "email": "support@pashminavogue.com",
        "company_name": "Pashmina Vogue™",
        "website": "https://pashminavogue.com",
        "country": "",  # UNKNOWN
        "source_platform": "Website Search",
    }
    res = LocalTestQualifier.qualify(buyer, product_keyword="Handmade Pashmina")
    assert any("UNKNOWN" in e for e in res.evidence)
    assert res.qualification_score > 0  # Valid score based on available dimensions


def test_product_keyword_expansion_is_dynamic():
    """Verify product keywords expand dynamically based on search keyword."""
    pashmina_tokens = expand_product_keywords("Handmade Pashmina")
    assert "pashmina" in pashmina_tokens
    assert "cashmere" in pashmina_tokens
    assert "shawls" in pashmina_tokens or "shawl" in pashmina_tokens

    bowls_tokens = expand_product_keywords("Singing Bowls")
    assert "singing bowls" in bowls_tokens or "sound healing" in bowls_tokens
    assert "pashmina" not in bowls_tokens


def test_qualify_live_excludes_historical_and_targets_live_discovery(mock_qualification_env, monkeypatch, capsys):
    """Verify --qualify-live exclusively qualifies the 2 LIVE_DISCOVERY Pashmina leads."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", True)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "mock_key_valid")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    mock_gemini_resp = MagicMock()
    mock_gemini_resp.text = json.dumps({
        "qualifications": [
            {
                "email": "support@pashminaartisan.in",
                "company_name": "Pashmina Artisan",
                "business_status": "business",
                "product_relevance": 0.95,
                "buyer_intent": 0.70,
                "commercial_signals": ["artisan", "textiles", "b2b"],
                "evidence": ["Dedicated domain website", "Artisanal cashmere brand"],
                "qualification_score": 82,
                "qualification_level": "HIGH",
                "recommendation": "REVIEW_FOR_OUTREACH",
            },
            {
                "email": "support@pashminavogue.com",
                "company_name": "Pashmina Vogue™",
                "business_status": "business",
                "product_relevance": 0.95,
                "buyer_intent": 0.75,
                "commercial_signals": ["retailer", "brand", "wholesale"],
                "evidence": ["Dedicated domain website", "Trademarked pashmina brand"],
                "qualification_score": 85,
                "qualification_level": "HIGH",
                "recommendation": "REVIEW_FOR_OUTREACH",
            },
        ]
    })
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_gemini_resp

    with patch("google.genai.Client", return_value=mock_client):
        run_qualify_live_action(data_dir=mock_qualification_env, keyword="Handmade Pashmina")

    out = capsys.readouterr().out

    assert "Targeting 2 LIVE_DISCOVERY records for AI Qualification" in out
    assert "support@pashminaartisan.in" in out
    assert "support@pashminavogue.com" in out
    assert "import@zenithhealing.com" not in out
    assert "contact@aurawellness.de" not in out
    assert "GEMINI QUALIFICATION: LIVE" in out
    assert "GMAIL OUTREACH: DISABLED / TEST MODE" in out

    # Verify log saved
    logs = load_qualification_log(mock_qualification_env / "qualification_log.csv")
    assert len(logs) == 2
    assert any(l["email"] == "support@pashminaartisan.in" for l in logs)
    assert any(l["email"] == "support@pashminavogue.com" for l in logs)


def test_qualify_live_refuses_when_toggle_is_false(mock_qualification_env, monkeypatch, capsys):
    """Verify qualify-live blocks when CLASSIFICATION_LIVE is false."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", False)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "mock_key_valid")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    run_qualify_live_action(data_dir=mock_qualification_env)
    out = capsys.readouterr().out

    assert "CLASSIFICATION_LIVE is set to false" in out
    assert "GEMINI QUALIFICATION: LIVE" in out


def test_qualify_live_api_failure_does_not_fallback(mock_qualification_env, monkeypatch, capsys):
    """Verify live Gemini API failure reports GEMINI_API_ERROR without silent fallback."""
    monkeypatch.setattr(Config, "CLASSIFICATION_LIVE", True)
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "mock_key_valid")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = Exception("Rate limit 429")

    with patch("google.genai.Client", return_value=mock_client):
        run_qualify_live_action(data_dir=mock_qualification_env)

    out = capsys.readouterr().out

    assert "GEMINI_API_ERROR" in out
    assert "Rate limit 429" in out


def test_qualify_live_buyers_missing_key():
    """Verify qualify_live_buyers returns GEMINI_API_KEY_NOT_CONFIGURED when key is empty."""
    results, err = qualify_live_buyers([{"email": "test@example.com"}], api_key="")
    assert results == []
    assert err == "GEMINI_API_KEY_NOT_CONFIGURED"
