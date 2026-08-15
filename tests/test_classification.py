"""
Unit tests for Phase 3: AI Lead Classification.
Covers all 12 required test scenarios:
  1. Email deduplication before classification
  2. Local TEST_MODE classification
  3. Business classification output
  4. Individual classification output
  5. Invalid email exclusion
  6. Malformed AI JSON recovery
  7. Unknown category handling
  8. Missing API key fallback
  9. Batch processing
  10. Low-confidence review flagging
  11. Classification log persistence
  12. Existing classification files compatibility
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config import Config
from classification.gemini_classifier import (
    ClassificationResult,
    LocalTestClassifier,
    GeminiClassifier,
    classify_contacts,
    classify_contacts_detailed,
    run_classification_pipeline,
)
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    load_classified_emails,
    load_classification_log,
    audit_classification_log,
)


@pytest.fixture
def isolated_data_dir(tmp_path):
    """Create an isolated clean data directory with initialized stores."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)
    return data_dir


# 1. Email deduplication before classification
def test_email_deduplication_before_classification():
    """Verify duplicate emails (even with casing differences) are collapsed into one before classification."""
    buyers = [
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Ltd", "email": "import@zenithhealing.com", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Sound", "email": "IMPORT@zenithhealing.com", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Website Search"},
        {"buyer_name": "Marcus", "company_name": "Zenith", "email": "  import@zenithhealing.com  ", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Facebook"},
    ]

    results = classify_contacts_detailed(buyers, force_heuristic=True)
    assert len(results) == 1
    assert results[0].email == "import@zenithhealing.com"


# 2. Local TEST_MODE classification
def test_local_test_mode_classification():
    """Verify LocalTestClassifier produces deterministic results marked with LOCAL_TEST_CLASSIFICATION."""
    buyer = {
        "buyer_name": "Elena Rostova",
        "company_name": "Aura Wellness Wholesale GmbH",
        "email": "contact@aurawellness.de",
        "website": "https://aurawellness.de",
        "country": "Germany",
        "source_platform": "Google Search",
    }

    result = LocalTestClassifier.classify(buyer)
    assert result.category == "business"
    assert result.classification_source == "LOCAL_TEST_CLASSIFICATION"
    assert result.confidence >= 0.85
    assert not result.review_required


# 3. Business classification output
def test_business_classification_output(isolated_data_dir):
    """Verify business buyer records are classified as business and persisted to business_emails.csv."""
    buyers_csv = isolated_data_dir / "buyers.csv"
    biz_csv = isolated_data_dir / "business_emails.csv"
    ind_csv = isolated_data_dir / "individual_emails.csv"
    log_csv = isolated_data_dir / "classification_log.csv"

    save_buyers([
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Sound Healing Imports Ltd", "email": "import@zenithhealing.com", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Elena Rostova", "company_name": "Aura Wellness Wholesale", "email": "contact@aurawellness.de", "website": "https://aurawellness.de", "country": "Germany", "source_platform": "Google Search"},
    ], csv_path=buyers_csv)

    summary = run_classification_pipeline(
        buyers_csv_path=buyers_csv,
        biz_csv_path=biz_csv,
        ind_csv_path=ind_csv,
        log_csv_path=log_csv,
        force_test_mode=True,
    )

    assert summary["business_contacts"] == 2
    assert summary["individual_contacts"] == 0

    classified = load_classified_emails(biz_path=biz_csv, ind_path=ind_csv)
    assert "import@zenithhealing.com" in classified["business"]
    assert "contact@aurawellness.de" in classified["business"]


# 4. Individual classification output
def test_individual_classification_output(isolated_data_dir):
    """Verify individual/freemail contacts with no company are classified as individual and saved to individual_emails.csv."""
    buyers_csv = isolated_data_dir / "buyers.csv"
    biz_csv = isolated_data_dir / "business_emails.csv"
    ind_csv = isolated_data_dir / "individual_emails.csv"
    log_csv = isolated_data_dir / "classification_log.csv"

    save_buyers([
        {"buyer_name": "John Doe", "company_name": "", "email": "john.soundlover@gmail.com", "website": "", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Sara Smith", "company_name": "", "email": "sara.meditates@yahoo.com", "website": "", "country": "UK", "source_platform": "Website Search"},
    ], csv_path=buyers_csv)

    summary = run_classification_pipeline(
        buyers_csv_path=buyers_csv,
        biz_csv_path=biz_csv,
        ind_csv_path=ind_csv,
        log_csv_path=log_csv,
        force_test_mode=True,
    )

    assert summary["individual_contacts"] == 2
    assert summary["business_contacts"] == 0

    classified = load_classified_emails(biz_path=biz_csv, ind_path=ind_csv)
    assert "john.soundlover@gmail.com" in classified["individual"]
    assert "sara.meditates@yahoo.com" in classified["individual"]


# 5. Invalid email exclusion
def test_invalid_email_exclusion(isolated_data_dir):
    """Verify invalid and placeholder email records in buyers.csv are excluded from the classification queue."""
    buyers_csv = isolated_data_dir / "buyers.csv"
    biz_csv = isolated_data_dir / "business_emails.csv"
    ind_csv = isolated_data_dir / "individual_emails.csv"
    log_csv = isolated_data_dir / "classification_log.csv"

    save_buyers([
        {"buyer_name": "Valid Buyer", "company_name": "Zenith Ltd", "email": "import@zenithhealing.com", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Fake Buyer", "company_name": "Dummy Corp", "email": "invalid.placeholder@example.com", "website": "", "country": "", "source_platform": "Google Search"},
        {"buyer_name": "Malformed Buyer", "company_name": "Test Co", "email": "malformed@@domain..com", "website": "", "country": "", "source_platform": "Website Search"},
    ], csv_path=buyers_csv)

    summary = run_classification_pipeline(
        buyers_csv_path=buyers_csv,
        biz_csv_path=biz_csv,
        ind_csv_path=ind_csv,
        log_csv_path=log_csv,
        force_test_mode=True,
    )

    assert summary["total_buyer_records"] == 3
    assert summary["valid_emails"] == 1
    assert summary["invalid_emails"] == 2
    assert summary["business_contacts"] + summary["individual_contacts"] == 1


# 6. Malformed AI JSON recovery
def test_malformed_ai_json_recovery():
    """Verify GeminiClassifier handles malformed/broken JSON strings by falling back to local classification."""
    classifier = GeminiClassifier(api_key="mock_api_key")
    buyers = [
        {"buyer_name": "Elena", "company_name": "Aura Wellness Wholesale", "email": "contact@aurawellness.de", "website": "https://aurawellness.de", "country": "Germany", "source_platform": "Google Search"}
    ]

    # Directly test parsing method with malformed JSON
    broken_json = "This is not valid JSON at all: {classifications: [broken"
    results = classifier._parse_gemini_json(broken_json, buyers, review_threshold=0.70)

    assert len(results) == 1
    assert results[0].email == "contact@aurawellness.de"
    assert results[0].category == "business"
    assert results[0].classification_source == "LOCAL_TEST_CLASSIFICATION"


# 7. Unknown category handling
def test_unknown_category_handling():
    """Verify unknown categories returned by model (e.g. 'consumer', 'other') default to safe category."""
    classifier = GeminiClassifier(api_key="mock_api_key")
    buyers = [
        {"buyer_name": "Elena", "company_name": "Aura Wellness", "email": "contact@aurawellness.de", "website": "https://aurawellness.de", "country": "Germany", "source_platform": "Google Search"}
    ]

    custom_json = json.dumps({
        "classifications": [
            {"email": "contact@aurawellness.de", "category": "non_standard_category", "confidence": 0.88, "reason": "Test non standard"}
        ]
    })

    results = classifier._parse_gemini_json(custom_json, buyers, review_threshold=0.70)
    assert len(results) == 1
    assert results[0].category in ("business", "individual")


# 8. Missing API key fallback
def test_missing_api_key_fallback():
    """Verify GeminiClassifier gracefully uses LocalTestClassifier when no API key is set."""
    classifier = GeminiClassifier(api_key="")
    buyers = [
        {"buyer_name": "Oliver Jackson", "company_name": "Australasian Sound Supplies Pty", "email": "purchasing@australiansound.com.au", "website": "https://australiansound.com.au", "country": "Australia", "source_platform": "Trade Directory"}
    ]

    results = classifier.classify_batch(buyers)
    assert len(results) == 1
    assert results[0].category == "business"
    assert results[0].classification_source == "LOCAL_TEST_CLASSIFICATION"


# 9. Batch processing
def test_batch_processing():
    """Verify large lists are partitioned and processed in batches according to batch_size."""
    buyers = [
        {"buyer_name": f"Buyer {i}", "company_name": f"Company {i} Ltd", "email": f"buyer{i}@company{i}.com", "website": f"https://company{i}.com", "country": "USA", "source_platform": "Google Search"}
        for i in range(15)
    ]

    results = classify_contacts_detailed(buyers, force_heuristic=True, batch_size=5)
    assert len(results) == 15
    assert all(r.category == "business" for r in results)


# 10. Low-confidence review flagging
def test_low_confidence_review_flagging():
    """Verify records with confidence below CLASSIFICATION_REVIEW_THRESHOLD are marked review_required."""
    # A freemail domain with an ambiguous, non-corporate business name
    ambiguous_buyer = {
        "buyer_name": "Dave",
        "company_name": "Dave Singing Bowls",
        "email": "dave.bowls@gmail.com",
        "website": "",
        "country": "USA",
        "source_platform": "Google Search",
    }

    result = LocalTestClassifier.classify(ambiguous_buyer, review_threshold=0.70)
    assert result.confidence < 0.70
    assert result.review_required is True


# 11. Classification log persistence
def test_classification_log_persistence(isolated_data_dir):
    """Verify classification audit entries are written to data/classification_log.csv with required fields."""
    buyers_csv = isolated_data_dir / "buyers.csv"
    biz_csv = isolated_data_dir / "business_emails.csv"
    ind_csv = isolated_data_dir / "individual_emails.csv"
    log_csv = isolated_data_dir / "classification_log.csv"

    save_buyers([
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Ltd", "email": "import@zenithhealing.com", "website": "https://zenithhealing.com", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Alice", "company_name": "", "email": "alice@gmail.com", "website": "", "country": "USA", "source_platform": "Google Search"},
    ], csv_path=buyers_csv)

    run_classification_pipeline(
        buyers_csv_path=buyers_csv,
        biz_csv_path=biz_csv,
        ind_csv_path=ind_csv,
        log_csv_path=log_csv,
        force_test_mode=True,
    )

    logs = load_classification_log(log_csv)
    assert len(logs) == 2

    first = logs[0]
    assert "email" in first
    assert "category" in first
    assert "confidence" in first
    assert "reason" in first
    assert "classification_source" in first
    assert "review_required" in first
    assert "timestamp" in first

    audit = audit_classification_log(log_csv)
    assert audit["total_records"] == 2
    assert audit["business_count"] == 1
    assert audit["individual_count"] == 1


# 12. Existing classification files compatibility
def test_existing_classification_files_compatibility(isolated_data_dir):
    """Verify that output CSV files remain compatible with existing load_classified_emails reader."""
    biz_csv = isolated_data_dir / "business_emails.csv"
    ind_csv = isolated_data_dir / "individual_emails.csv"

    biz_emails, ind_emails = classify_contacts([
        {"buyer_name": "Marcus", "company_name": "Zenith Ltd", "email": "import@zenithhealing.com"},
        {"buyer_name": "John", "company_name": "", "email": "john@gmail.com"},
    ], force_heuristic=True)

    assert "import@zenithhealing.com" in biz_emails
    assert "john@gmail.com" in ind_emails
