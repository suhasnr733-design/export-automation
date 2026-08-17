"""
Regression Test Suite for Multi-Keyword Live Discovery Isolation and Deduplication.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import Config
from app_logging.activity_logger import (
    init_data_stores,
    save_buyers,
    load_buyers,
    load_discovery_provenance,
    save_discovery_provenance,
)
from search.google_search import GoogleSearchAdapter
from search.website_search import WebsiteSearchAdapter
from search.relevance_filter import evaluate_result_relevance, get_product_terms_for_keyword
from search.search_cache import SearchCache
from main import run_discovery_only


@pytest.fixture
def isolated_discovery_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    init_data_stores(base_dir=tmp_path)

    monkeypatch.setattr(Config, "DATA_DIR", data_dir)
    monkeypatch.setattr(Config, "BUYERS_CSV", data_dir / "buyers.csv")
    monkeypatch.setattr(Config, "DISCOVERY_PROVENANCE_FILE", data_dir / "discovery_provenance.json")
    monkeypatch.setattr(Config, "SENT_LOG_CSV", data_dir / "sent_log.csv")
    monkeypatch.setattr(Config, "QUALIFICATION_LOG_CSV", data_dir / "qualification_log.csv")
    monkeypatch.setattr(Config, "LEAD_REVIEW_LOG_CSV", data_dir / "lead_review_log.csv")
    monkeypatch.setattr(Config, "TEST_MODE", True)

    SearchCache().clear()
    return data_dir


def test_relevance_filter_supports_yoga_and_pashmina():
    pashmina_terms = get_product_terms_for_keyword("Pashmina")
    assert "pashmina" in pashmina_terms
    assert "cashmere" in pashmina_terms

    yoga_terms = get_product_terms_for_keyword("yoga accessories")
    assert "yoga" in yoga_terms
    assert "accessories" in yoga_terms

    pashmina_item = {
        "title": "Kashmir Pashmina Wholesalers",
        "company_name": "Kashmir Crafts",
        "url": "https://kashmircrafts.com",
        "snippet": "Direct wholesale distributor of handmade pashmina and cashmere scarves.",
        "email": "sales@kashmircrafts.com",
    }
    audit_p = evaluate_result_relevance(pashmina_item, keyword="Pashmina")
    assert audit_p.decision == "ACCEPT"

    yoga_item = {
        "title": "Manduka Eco Fitness & Yoga",
        "company_name": "Manduka Distributors",
        "url": "https://manduka.com",
        "snippet": "Leading distributor of organic yoga mats, blocks, and accessories.",
        "email": "wholesale@manduka.com",
    }
    audit_y = evaluate_result_relevance(yoga_item, keyword="yoga accessories")
    assert audit_y.decision == "ACCEPT"


def test_multi_keyword_discovery_produces_distinct_results(isolated_discovery_env):
    mock_pashmina_google = [{"title": "Pashmina Luxe", "url": "https://pashminaluxe.com", "snippet": "Wholesale", "source_platform": "Google Search"}]
    mock_pashmina_web = [{
        "buyer_name": "Amina Khan",
        "company_name": "Pashmina Luxe",
        "email": "amina@pashminaluxe.com",
        "website": "https://pashminaluxe.com",
        "country": "United Kingdom",
        "source_platform": "Website Search",
        "title": "Pashmina Luxe Wholesale",
        "snippet": "Direct wholesale importer of handmade pashmina",
        "keyword": "Pashmina",
    }]

    with patch.object(GoogleSearchAdapter, "search", return_value=mock_pashmina_google), \
         patch.object(WebsiteSearchAdapter, "crawl_and_extract", return_value=mock_pashmina_web):
        summary_1 = run_discovery_only(keyword="Pashmina", max_results=5, data_dir=isolated_discovery_env, force_refresh=True)
        assert summary_1["records_written"] == 1
        assert summary_1["duplicates_removed"] == 0

    with patch.object(GoogleSearchAdapter, "search", return_value=mock_pashmina_google), \
         patch.object(WebsiteSearchAdapter, "crawl_and_extract", return_value=mock_pashmina_web):
        summary_2 = run_discovery_only(keyword="Pashmina", max_results=5, data_dir=isolated_discovery_env, force_refresh=True)
        assert summary_2["records_written"] == 0
        assert summary_2["duplicates_removed"] == 1

    mock_yoga_google = [{"title": "Zen Yoga", "url": "https://zenyogasupplies.com", "snippet": "Wholesale", "source_platform": "Google Search"}]
    mock_yoga_web = [{
        "buyer_name": "Maya Lin",
        "company_name": "Zen Yoga Supplies",
        "email": "maya@zenyogasupplies.com",
        "website": "https://zenyogasupplies.com",
        "country": "United States",
        "source_platform": "Website Search",
        "title": "Zen Yoga Wholesale",
        "snippet": "Wholesale yoga accessories and mats",
        "keyword": "yoga accessories",
    }]

    with patch.object(GoogleSearchAdapter, "search", return_value=mock_yoga_google), \
         patch.object(WebsiteSearchAdapter, "crawl_and_extract", return_value=mock_yoga_web):
        summary_3 = run_discovery_only(keyword="yoga accessories", max_results=5, data_dir=isolated_discovery_env, force_refresh=True)
        assert summary_3["records_written"] == 1
        assert summary_3["duplicates_removed"] == 0

    buyers = load_buyers(isolated_discovery_env / "buyers.csv")
    emails = {b["email"].lower() for b in buyers}
    assert "amina@pashminaluxe.com" in emails
    assert "maya@zenyogasupplies.com" in emails
    assert len(buyers) == 2

    prov = load_discovery_provenance(isolated_discovery_env / "discovery_provenance.json")
    records = prov.get("records", {})
    assert records["amina@pashminaluxe.com"]["keyword"] == "Pashmina"
    assert records["maya@zenyogasupplies.com"]["keyword"] == "yoga accessories"
    assert records["amina@pashminaluxe.com"]["data_source"] == "LIVE_DISCOVERY"
    assert records["maya@zenyogasupplies.com"]["data_source"] == "LIVE_DISCOVERY"
