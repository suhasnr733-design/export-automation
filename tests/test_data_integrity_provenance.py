"""
Regression tests for Data Integrity, Provenance Preservation, and Test/Real Data Separation (Phase 6C).

Verifies:
1. TEST_MODE_SUCCESS is strictly counted as simulation, not as actual live SENT.
2. 38 simulations and 0 live sends are audited and distinguished accurately.
3. Last discovery keyword is tracked and displayed correctly.
4. Test fixtures and test runs do not pollute or modify production CSV files.
5. Real discovery records remain intact with verified provenance.
6. Historical records are preserved and properly categorized as HISTORICAL_TEST without deletion.
7. Provenance metadata is loaded, updated, and saved correctly.
"""

import json
import pytest
from pathlib import Path

from config import Config
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    audit_buyers_csv,
    audit_sent_log,
    save_discovery_provenance,
    load_discovery_provenance,
    get_provenance_audit,
    DEFAULT_BUYERS_CSV,
    DEFAULT_SENT_LOG_CSV,
    DEFAULT_PROVENANCE_FILE,
)


def test_test_mode_success_not_counted_as_live_sent(tmp_path):
    """Verify that TEST_MODE_SUCCESS entries are counted as simulations and NEVER as live sends."""
    sent_log = tmp_path / "sent_log.csv"
    with open(sent_log, mode="w", encoding="utf-8") as f:
        f.write("email,status,timestamp\n")
        f.write("buyer1@example.com,TEST_MODE_SUCCESS,2026-08-14T12:00:00Z\n")
        f.write("buyer2@example.com,TEST_MODE_SUCCESS,2026-08-14T12:00:00Z\n")
        f.write("buyer3@example.com,TEST_MODE_SUCCESS,2026-08-14T12:00:00Z\n")

    audit = audit_sent_log(sent_log)
    assert audit["test_mode_records"] == 3
    assert audit["successful_sends"] == 0
    assert audit["unique_simulated_recipients"] == 3
    assert audit["unique_live_contacted"] == 0


def test_audit_sent_log_distinguishes_simulations_from_live():
    """Verify sent_log audit on current production datastore reports simulations and 0 live sends."""
    audit = audit_sent_log(DEFAULT_SENT_LOG_CSV)
    assert audit["test_mode_records"] >= 38
    assert audit["successful_sends"] == 0
    assert audit["unique_live_contacted"] == 0
    assert audit["unique_simulated_recipients"] >= 13


def test_provenance_preservation_and_keyword_tracking(tmp_path):
    """Verify save_discovery_provenance and load_discovery_provenance preserve all metadata."""
    prov_file = tmp_path / "discovery_provenance.json"
    records = [
        {
            "email": "buyer@pashmina.com",
            "company_name": "Pashmina Imports",
            "country": "Germany",
            "source_platform": "Website Search",
            "url": "https://pashmina.com",
            "relevance_decision": "ACCEPT",
            "relevance_reason": "Direct textile wholesaler",
            "data_source": "LIVE_DISCOVERY",
        }
    ]

    save_discovery_provenance(records, keyword="Handmade Pashmina", json_path=prov_file)
    data = load_discovery_provenance(prov_file)

    assert data["metadata"]["last_discovery_keyword"] == "Handmade Pashmina"
    assert "buyer@pashmina.com" in data["records"]
    assert data["records"]["buyer@pashmina.com"]["data_source"] == "LIVE_DISCOVERY"
    assert data["records"]["buyer@pashmina.com"]["keyword"] == "Handmade Pashmina"


def test_historical_buyers_categorized_without_deletion(tmp_path):
    """Verify historical buyers are identified as HISTORICAL_TEST while live leads are identified as LIVE_DISCOVERY."""
    buyers_file = tmp_path / "buyers.csv"
    prov_file = tmp_path / "discovery_provenance.json"

    # Save 3 records: 2 historical and 1 live
    buyers = [
        {"buyer_name": "Marcus", "company_name": "Zenith", "email": "import@zenith.com", "website": "https://zenith.com", "country": "USA", "source_platform": "Google Search"},
        {"buyer_name": "Elena", "company_name": "Aura", "email": "contact@aura.de", "website": "https://aura.de", "country": "Germany", "source_platform": "Google Search"},
        {"buyer_name": "", "company_name": "Pashmina Artisan", "email": "support@pashminaartisan.in", "website": "https://pashminaartisan.in", "country": "India", "source_platform": "Website Search"},
    ]
    save_buyers(buyers, csv_path=buyers_file)

    prov_records = [
        {"email": "import@zenith.com", "data_source": "HISTORICAL_TEST", "keyword": "Singing Bowls"},
        {"email": "contact@aura.de", "data_source": "HISTORICAL_TEST", "keyword": "Singing Bowls"},
        {"email": "support@pashminaartisan.in", "data_source": "LIVE_DISCOVERY", "keyword": "Handmade Pashmina"},
    ]
    save_discovery_provenance(prov_records, keyword="Handmade Pashmina", json_path=prov_file)

    audit = audit_buyers_csv(csv_path=buyers_file, provenance_path=prov_file)
    assert audit["total_records"] == 3
    assert audit["historical_test_count"] == 2
    assert audit["live_discovery_count"] == 1
    assert audit["last_discovery_keyword"] == "Handmade Pashmina"


def test_production_csv_files_remain_intact_and_unpolluted():
    """Verify production buyers.csv has all 13 records intact (11 historical + 2 live discovery)."""
    assert DEFAULT_BUYERS_CSV.exists()
    buyers = load_buyers(DEFAULT_BUYERS_CSV)
    assert len(buyers) == 13

    # Check that historical Singing Bowls leads exist
    emails = [b["email"].lower() for b in buyers]
    assert "import@zenithhealing.com" in emails
    assert "contact@aurawellness.de" in emails

    # Check that live Pashmina leads exist
    assert "support@pashminaartisan.in" in emails
    assert "support@pashminavogue.com" in emails
