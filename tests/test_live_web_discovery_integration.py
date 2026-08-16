"""
Unit and Integration Tests for Live Web Discovery Feature.
Validates:
1. POST /discover/run executes discovery and redirects to /review
2. Target product keyword and max_results are passed to discovery
3. Existing emails in data/buyers.csv are skipped (never added as duplicates)
4. Contacted emails in data/sent_log.csv are skipped (never added as duplicates)
5. Genuinely new leads are persisted with LIVE_DISCOVERY data_source in provenance
6. GET /review remains strictly read-only and does NOT trigger discovery
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import Config
from web_app import app
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    save_discovery_provenance,
    load_discovery_provenance,
    log_send_attempt,
)
from main import run_discovery_only


@pytest.fixture
def client():
    """Create Flask test client configured with testing flags."""
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-12345"
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


@pytest.fixture
def isolated_data_env(tmp_path, monkeypatch):
    """Set up an isolated data directory for discovery tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)

    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    monkeypatch.setattr(Config, "BUYERS_CSV", data_dir / "buyers.csv")
    monkeypatch.setattr(Config, "DISCOVERY_PROVENANCE_FILE", data_dir / "discovery_provenance.json")
    monkeypatch.setattr(Config, "SENT_LOG_CSV", data_dir / "sent_log.csv")
    monkeypatch.setattr(Config, "QUALIFICATION_LOG_CSV", data_dir / "qualification_log.csv")
    monkeypatch.setattr(Config, "LEAD_REVIEW_LOG_CSV", data_dir / "lead_review_log.csv")

    return data_dir


def test_post_discover_run_executes_and_redirects(client, isolated_data_env):
    """Verify POST /discover/run invokes discovery and redirects to /review with flash feedback."""
    mock_summary = {
        "existing_buyers": 0,
        "search_results": 5,
        "accepted_items": 3,
        "rejected_items": 2,
        "potential_buyers": 2,
        "emails_discovered": 2,
        "valid_emails": 2,
        "duplicates_removed": 0,
        "records_written": 2,
        "source_statuses": {"Google Search": "LIVE"},
    }

    with patch("main.run_discovery_only", return_value=mock_summary) as mock_discover:
        resp = client.post("/discover/run", data={
            "keyword": "Organic Green Tea",
            "max_results": "10",
            "force_refresh": "true",
        }, follow_redirects=False)

        assert resp.status_code == 302
        assert resp.location == "/review"

        mock_discover.assert_called_once()
        kwargs = mock_discover.call_args[1]
        assert kwargs["keyword"] == "Organic Green Tea"
        assert kwargs["max_results"] == 10
        assert kwargs["force_refresh"] is True


def test_discover_skips_existing_buyers_and_sent_log(isolated_data_env):
    """Verify discovery engine never adds duplicates from buyers.csv or sent_log.csv."""
    buyers_file = isolated_data_env / "buyers.csv"
    sent_log_file = isolated_data_env / "sent_log.csv"

    # Pre-populate buyers.csv with an existing buyer
    save_buyers([{
        "buyer_name": "Existing Buyer",
        "company_name": "Existing Imports",
        "email": "existing@importer.com",
        "website": "https://existing.com",
        "country": "Germany",
        "source_platform": "Website Search",
    }], csv_path=buyers_file)

    # Pre-populate sent_log.csv with a contacted buyer
    log_send_attempt(
        email="contacted@buyer.com",
        status="TEST_MODE_SUCCESS",
        send_type="TEST_MODE_SIMULATION",
        csv_path=sent_log_file,
    )

    # Mock search & extraction returning:
    # 1. An existing buyer (existing@importer.com)
    # 2. A previously contacted buyer (contacted@buyer.com)
    # 3. A genuinely new buyer (fresh@newbuyer.com)
    raw_mock_results = [
        {
            "title": "Existing Pashmina Importer",
            "buyer_name": "Existing Buyer",
            "company_name": "Existing Pashmina Imports",
            "snippet": "Direct wholesale importer of authentic handmade pashmina shawls. Contact us at existing@importer.com.",
            "url": "https://existing.com",
            "website": "https://existing.com",
            "country": "Germany",
            "source_platform": "Google Search",
        },
        {
            "title": "Contacted Pashmina Buyer",
            "buyer_name": "Contacted Buyer",
            "company_name": "Contacted Pashmina Wholesale",
            "snippet": "Distributor of luxury cashmere and pashmina scarves. Inquiries to contacted@buyer.com.",
            "url": "https://contacted.com",
            "website": "https://contacted.com",
            "country": "United States",
            "source_platform": "Google Search",
        },
        {
            "title": "Fresh Pashmina Buyer Global",
            "buyer_name": "Fresh Buyer",
            "company_name": "Fresh Pashmina Wholesale Ltd",
            "snippet": "Wholesale procurement of handmade pashmina textiles and shawls. Inquiries: orders@freshnewbuyer.com.",
            "url": "https://freshnewbuyer.com",
            "website": "https://freshnewbuyer.com",
            "country": "United Kingdom",
            "source_platform": "Google Search",
        },
    ]

    with patch("search.google_search.GoogleSearchAdapter.search", return_value=raw_mock_results), \
         patch("search.website_search.WebsiteSearchAdapter.crawl_and_extract", return_value=[]):
        
        summary = run_discovery_only(
            keyword="Handmade Pashmina",
            max_results=10,
            data_dir=isolated_data_env,
        )

        assert summary["records_written"] == 1
        assert summary["duplicates_removed"] >= 2

        # Verify buyers.csv only has existing + fresh (total 2 records)
        updated_buyers = load_buyers(buyers_file)
        emails = [b["email"].lower() for b in updated_buyers]
        assert "existing@importer.com" in emails
        assert "orders@freshnewbuyer.com" in emails
        assert "contacted@buyer.com" not in emails

        # Verify discovery_provenance.json tagged fresh buyer as LIVE_DISCOVERY
        prov = load_discovery_provenance(isolated_data_env / "discovery_provenance.json")
        assert "orders@freshnewbuyer.com" in prov["records"]
        assert prov["records"]["orders@freshnewbuyer.com"]["data_source"] == "LIVE_DISCOVERY"
        assert prov["records"]["orders@freshnewbuyer.com"]["keyword"] == "Handmade Pashmina"


def test_get_review_is_readonly_and_never_triggers_discovery(client, isolated_data_env):
    """Verify GET /review only displays existing records and NEVER triggers web discovery."""
    buyers_file = isolated_data_env / "buyers.csv"
    save_buyers([{
        "buyer_name": "Live Buyer 1",
        "company_name": "Live Co",
        "email": "live@example.com",
        "website": "https://live.com",
        "country": "France",
        "source_platform": "Website Search",
    }], csv_path=buyers_file)

    save_discovery_provenance([{
        "email": "live@example.com",
        "company_name": "Live Co",
        "data_source": "LIVE_DISCOVERY",
    }], keyword="Singing Bowls", json_path=isolated_data_env / "discovery_provenance.json")

    with patch("main.run_discovery_only") as mock_discover, \
         patch("search.google_search.GoogleSearchAdapter.search") as mock_search:
        
        resp = client.get("/review")
        assert resp.status_code == 200
        text = resp.data.decode("utf-8")

        assert "Live Web Buyer Discovery" in text
        assert "Discover New Leads" in text
        assert "live@example.com" in text

        # Assert no discovery function was called
        mock_discover.assert_not_called()
        mock_search.assert_not_called()


def test_review_html_contains_discovery_form_elements(client, isolated_data_env):
    """Verify review.html renders keyword input, max results select, and submit button."""
    resp = client.get("/review")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")

    assert 'action="/discover/run"' in html
    assert 'name="keyword"' in html
    assert 'name="max_results"' in html
    assert 'Discover New Leads' in html
    assert 'Force Fresh Search' in html
