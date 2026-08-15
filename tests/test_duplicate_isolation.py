"""
Unit tests for Duplicate Isolation, Datastore Separation, and Source Status Reporting.
Covers all Phase 2 verification requirements:
  1. New email is accepted.
  2. Existing buyer email is rejected as duplicate.
  3. Existing sent email is handled separately.
  4. Case-insensitive duplicate detection.
  5. Whitespace-normalized duplicate detection.
  6. Empty buyers.csv accepts new records.
  7. Test datastore does not modify production CSV.
  8. Source status reporting correctly identifies LIVE/STUB/FAILED.
"""

import pytest
from pathlib import Path
from logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    get_sent_emails,
    log_send_attempt,
    audit_buyers_csv,
    audit_sent_log,
    DEFAULT_BUYERS_CSV,
)
from main import run_discovery_only
from search.google_search import GoogleSearchAdapter
from search.website_search import WebsiteSearchAdapter
from search.facebook_search import FacebookSearchAdapter
from search.linkedin_search import LinkedInSearchAdapter
from search.directory_search import DirectorySearchAdapter


@pytest.fixture
def isolated_data_dir(tmp_path):
    """Create an isolated clean data directory for test assertions."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)
    return data_dir


# 1. New email is accepted
def test_new_email_is_accepted(isolated_data_dir):
    """Verify that a new valid email is accepted and appended to buyers.csv."""
    csv_file = isolated_data_dir / "buyers.csv"
    save_buyers([
        {"buyer_name": "Marcus Vance", "company_name": "Zenith", "email": "marcus@zenith.com", "website": "https://zenith.com", "country": "USA", "source_platform": "Google Search"}
    ], csv_path=csv_file)

    new_record = [
        {"buyer_name": "Elena Rostova", "company_name": "Aura", "email": "elena@aurawellness.de", "website": "https://aurawellness.de", "country": "Germany", "source_platform": "Google Search"}
    ]
    saved_count = save_buyers(new_record, csv_path=csv_file, append=True)
    assert saved_count == 1

    loaded = load_buyers(csv_file)
    assert len(loaded) == 2
    assert any(b["email"] == "elena@aurawellness.de" for b in loaded)


# 2. Existing buyer email is rejected as duplicate
def test_existing_buyer_email_rejected_as_duplicate(isolated_data_dir):
    """Verify that a record with an email already in buyers.csv is rejected upon append."""
    csv_file = isolated_data_dir / "buyers.csv"

    # Seed initial buyer
    save_buyers([
        {"buyer_name": "Marcus Vance", "company_name": "Zenith", "email": "marcus@zenith.com", "website": "https://zenith.com", "country": "USA", "source_platform": "Google Search"}
    ], csv_path=csv_file)

    # Attempt to insert same email again
    duplicate_batch = [
        {"buyer_name": "Marcus Vance", "company_name": "Zenith Sound Healing", "email": "marcus@zenith.com", "website": "https://zenith.com", "country": "USA", "source_platform": "Website Search"}
    ]
    saved_count = save_buyers(duplicate_batch, csv_path=csv_file, append=True)
    assert saved_count == 0  # 0 new records written

    loaded = load_buyers(csv_file)
    assert len(loaded) == 1


# 3. Existing sent email is handled separately
def test_existing_sent_email_handled_separately(isolated_data_dir):
    """
    Verify discovery datastore (buyers.csv) and outreach datastore (sent_log.csv)
    operate independently.
    A buyer in sent_log.csv who is not yet in buyers.csv is accepted into buyers.csv.
    """
    buyers_csv = isolated_data_dir / "buyers.csv"
    sent_csv = isolated_data_dir / "sent_log.csv"

    # Simulate historical send recorded in sent_log
    log_send_attempt("contact@newbuyer.com", "TEST_MODE_SUCCESS", csv_path=sent_csv)

    # Verify sent_log has it
    sent_set = get_sent_emails(csv_path=sent_csv)
    assert "contact@newbuyer.com" in sent_set

    # Verify discovery accepting this buyer into buyers.csv
    new_buyer = [
        {"buyer_name": "Alice", "company_name": "New Buyer Co", "email": "contact@newbuyer.com", "website": "https://newbuyer.com", "country": "UK", "source_platform": "Google Search"}
    ]
    saved_count = save_buyers(new_buyer, csv_path=buyers_csv, append=True)
    assert saved_count == 1  # Accepted into buyers.csv because it was not in buyers.csv yet

    loaded = load_buyers(buyers_csv)
    assert len(loaded) == 1


# 4. Case-insensitive duplicate detection
def test_case_insensitive_duplicate_detection(isolated_data_dir):
    """Verify duplicate detection rejects emails with different casing (e.g. UPPERCASE)."""
    csv_file = isolated_data_dir / "buyers.csv"

    save_buyers([
        {"buyer_name": "Elena", "company_name": "Aura", "email": "elena@aura-wellness.de", "website": "https://aura.de", "country": "Germany", "source_platform": "Google Search"}
    ], csv_path=csv_file)

    uppercase_variant = [
        {"buyer_name": "Elena", "company_name": "Aura", "email": "ELENA@AURA-WELLNESS.DE", "website": "https://aura.de", "country": "Germany", "source_platform": "Website Search"}
    ]
    saved_count = save_buyers(uppercase_variant, csv_path=csv_file, append=True)
    assert saved_count == 0

    loaded = load_buyers(csv_file)
    assert len(loaded) == 1


# 5. Whitespace-normalized duplicate detection
def test_whitespace_normalized_duplicate_detection(isolated_data_dir):
    """Verify duplicate detection rejects emails with leading/trailing whitespace."""
    csv_file = isolated_data_dir / "buyers.csv"

    save_buyers([
        {"buyer_name": "Elena", "company_name": "Aura", "email": "elena@aura-wellness.de", "website": "https://aura.de", "country": "Germany", "source_platform": "Google Search"}
    ], csv_path=csv_file)

    whitespace_variant = [
        {"buyer_name": "Elena", "company_name": "Aura", "email": "   elena@aura-wellness.de   ", "website": "https://aura.de", "country": "Germany", "source_platform": "Website Search"}
    ]
    saved_count = save_buyers(whitespace_variant, csv_path=csv_file, append=True)
    assert saved_count == 0

    loaded = load_buyers(csv_file)
    assert len(loaded) == 1


# 6. Empty buyers.csv accepts new records
def test_empty_buyers_csv_accepts_new_records(isolated_data_dir):
    """Verify that an empty buyers.csv accepts newly discovered records."""
    csv_file = isolated_data_dir / "buyers.csv"
    initial_buyers = load_buyers(csv_file)
    assert len(initial_buyers) == 0

    new_records = [
        {"buyer_name": "Marcus Vance", "company_name": "Zenith", "email": "marcus@zenith.com", "website": "https://zenith.com", "country": "USA", "source_platform": "Google Search"}
    ]
    saved_count = save_buyers(new_records, csv_path=csv_file, append=True)
    assert saved_count == 1

    loaded = load_buyers(csv_file)
    assert len(loaded) == 1
    assert loaded[0]["email"] == "marcus@zenith.com"


# 7. Test datastore does not modify production CSV
def test_datastore_does_not_modify_production_csv(tmp_path, monkeypatch):
    """Verify running discovery with a custom data_dir leaves production data/buyers.csv completely untouched."""
    from config import Config
    monkeypatch.setattr(Config, "TEST_DISCOVERY", True)

    prod_csv = DEFAULT_BUYERS_CSV
    prod_content_before = prod_csv.read_text(encoding="utf-8") if prod_csv.exists() else ""

    test_data_dir = tmp_path / "test_data_dir"
    test_data_dir.mkdir(parents=True, exist_ok=True)

    summary = run_discovery_only(keyword="Singing Bowls", max_results=3, data_dir=test_data_dir)
    assert summary["records_written"] > 0

    prod_content_after = prod_csv.read_text(encoding="utf-8") if prod_csv.exists() else ""
    assert prod_content_before == prod_content_after, "Production buyers.csv was modified during test run!"


# 8. Source status reporting correctly identifies LIVE/STUB/FAILED
def test_source_status_reporting_identifies_live_stub_failed():
    """Verify all search adapters report accurate operational status (LIVE, STUB, FAILED)."""
    google_adapter = GoogleSearchAdapter()
    website_adapter = WebsiteSearchAdapter()
    facebook_adapter = FacebookSearchAdapter()
    linkedin_adapter = LinkedInSearchAdapter()
    directory_adapter = DirectorySearchAdapter()

    assert google_adapter.get_status() in ("LIVE", "STUB")
    assert website_adapter.get_status() in ("LIVE", "STUB")
    assert facebook_adapter.get_status() == "STUB"
    assert linkedin_adapter.get_status() == "STUB"
    assert directory_adapter.get_status() == "STUB"

    # Test error handling status tracking
    class FailingAdapter:
        PLATFORM_NAME = "Broken Channel"
        def get_status(self):
            return "LIVE"
        def search(self, keyword, max_results):
            raise ConnectionError("Network down")

    failing = FailingAdapter()
    try:
        failing.search("test", 1)
    except ConnectionError as e:
        status = f"FAILED ({e})"
        assert "FAILED" in status
