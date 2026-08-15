"""
Regression Tests for Phase 6 Discovery Isolation & Keyword Propagation.

Verifies:
1. 'Handmade Pashmina' queries never return legacy Singing Bowls fixture domains.
2. The exact requested keyword is propagated across search adapters and query builders.
3. The SearchCache strictly isolates entries by (keyword, query, source).
4. Unrelated legacy domains (e.g. singing bowls/sound therapy) are rejected by the relevance filter.
5. Empty live search results do not fall back to stale legacy domains.
6. Historical buyers remain untouched in buyers.csv when new discovery runs.
7. Deduplication compares new discovery records against historical buyers without dropping new unique leads.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config import Config
from logging.activity_logger import init_data_stores, save_buyers, load_buyers
from search import (
    SearchQueryBuilder,
    GoogleSearchAdapter,
    FacebookSearchAdapter,
    LinkedInSearchAdapter,
    DirectorySearchAdapter,
    WebsiteSearchAdapter,
    SearchCache,
    evaluate_result_relevance,
)
from main import run_discovery_only


# ==============================================================================
# 1. Keyword Propagation & Clean Queries
# ==============================================================================
def test_query_builder_propagates_keyword_without_niche_bleed():
    """Verify SearchQueryBuilder creates generic B2B export queries for Pashmina without Singing Bowl terms."""
    builder = SearchQueryBuilder()
    queries = builder.build_queries("Handmade Pashmina")

    assert len(queries) > 0
    for q in queries:
        assert '"Handmade Pashmina"' in q
        assert "sound healing" not in q
        assert "singing bowl" not in q
        assert "meditation supplies" not in q
        assert "yoga accessories" not in q


# ==============================================================================
# 2. Search Cache Isolation
# ==============================================================================
def test_search_cache_isolates_by_keyword():
    """Verify results cached for 'Singing Bowls' are never returned for 'Handmade Pashmina'."""
    cache = SearchCache()
    cache.clear()

    singing_bowls_results = [
        {"title": "Zenith Sound Healing", "url": "https://www.zenithhealing.com"}
    ]
    cache.set("Singing Bowls", '"Singing Bowls" importer', "Google Search", singing_bowls_results)

    # Querying for Handmade Pashmina with identical query modifier must return None
    cached_pashmina = cache.get("Handmade Pashmina", '"Singing Bowls" importer', "Google Search")
    assert cached_pashmina is None

    # Querying for Singing Bowls must return cached result
    cached_bowls = cache.get("Singing Bowls", '"Singing Bowls" importer', "Google Search")
    assert cached_bowls is not None
    assert cached_bowls[0]["url"] == "https://www.zenithhealing.com"


# ==============================================================================
# 3. Legacy Seed Fallback Prevention
# ==============================================================================
def test_pashmina_search_never_returns_singing_bowl_domains():
    """Verify searching for 'Handmade Pashmina' in live mode returns only pashmina results or empty, never singing bowl seeds."""
    adapter = GoogleSearchAdapter(test_discovery=False)

    # Mock _fetch_public_search to return empty (simulating no hits / rate limit)
    with patch.object(adapter, "_fetch_public_search", return_value=[]):
        results = adapter.search("Handmade Pashmina", max_results=5, use_live_web=True)
        # Must return empty list, NOT zenithhealing.com or aurawellness.de
        assert results == []
        assert not any("zenithhealing.com" in r.get("url", "") for r in results)
        assert not any("aurawellness.de" in r.get("url", "") for r in results)


def test_offline_test_mode_generates_keyword_aligned_seeds():
    """Verify offline test mode generates synthetic seeds matching the requested keyword."""
    adapter = GoogleSearchAdapter(test_discovery=True)
    results = adapter.search("Handmade Pashmina", max_results=3, use_live_web=False)

    assert len(results) > 0
    for r in results:
        # All URLs and titles must be related to pashmina, not singing bowls
        assert "zenithhealing.com" not in r.get("url", "")
        assert "aurawellness.de" not in r.get("url", "")
        assert "pashmina" in r.get("snippet", "").lower() or "pashmina" in r.get("title", "").lower()


# ==============================================================================
# 4. Relevance Filter & Unrelated Website Rejection
# ==============================================================================
def test_relevance_filter_rejects_singing_bowl_sites_for_pashmina():
    """Verify singing bowls websites are marked REJECT with reason when target keyword is Pashmina."""
    singing_bowl_item = {
        "title": "Zenith Sound Healing Imports Ltd",
        "url": "https://www.zenithhealing.com",
        "snippet": "Direct wholesale distributor of handcrafted Tibetan singing bowls and meditation bells.",
        "company_name": "Zenith Sound Healing Imports Ltd",
        "country": "United States",
    }

    audit = evaluate_result_relevance(singing_bowl_item, keyword="Handmade Pashmina")
    assert audit.decision == "REJECT"
    assert audit.product_relevance == "NONE"
    assert "unrelated" in audit.reason.lower() or "no product keywords" in audit.reason.lower()


def test_relevance_filter_accepts_valid_pashmina_importers():
    """Verify legitimate textile/pashmina wholesale leads are marked ACCEPT."""
    pashmina_item = {
        "title": "Kashmir Pashmina & Silk Wholesale UK",
        "url": "https://www.kashmircraft.co.uk",
        "snippet": "Leading UK importer and distributor of authentic handmade pashmina shawls and cashmere scarves. Wholesale inquiries: info@kashmircraft.co.uk",
        "company_name": "Kashmir Pashmina Imports Ltd",
        "country": "United Kingdom",
        "email": "info@kashmircraft.co.uk",
    }

    audit = evaluate_result_relevance(pashmina_item, keyword="Handmade Pashmina")
    assert audit.decision == "ACCEPT"
    assert audit.product_relevance in ("HIGH", "MEDIUM")
    assert audit.buyer_relevance in ("HIGH", "MEDIUM")


# ==============================================================================
# 5. WebsiteSearchAdapter Zero-URL Behavior
# ==============================================================================
def test_website_adapter_empty_urls_returns_zero_records():
    """Verify WebsiteSearchAdapter does not crawl stale fallback domains when url list is empty."""
    adapter = WebsiteSearchAdapter(test_discovery=False)
    results = adapter.crawl_and_extract(urls=[], keyword="Handmade Pashmina")
    assert results == []

    search_res = adapter.search("Handmade Pashmina", domain_list=[])
    assert search_res == []


# ==============================================================================
# 6. Historical Data Preservation & Independent Deduplication
# ==============================================================================
def test_discovery_preserves_historical_buyers_and_deduplicates(tmp_path, monkeypatch):
    """Verify historical buyers in buyers.csv are preserved and new discoveries are cleanly deduplicated."""
    test_data_dir = tmp_path / "data"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    buyers_csv = test_data_dir / "buyers.csv"

    # Pre-populate historical singing bowl buyers
    historical_buyers = [
        {
            "buyer_name": "Marcus Vance",
            "company_name": "Zenith Sound Imports Ltd",
            "email": "import@zenithhealing.com",
            "website": "https://www.zenithhealing.com",
            "country": "United States",
            "source_platform": "Google Search",
        }
    ]
    save_buyers(historical_buyers, csv_path=buyers_csv)
    assert len(load_buyers(buyers_csv)) == 1

    # Mock search to return 1 duplicate and 1 genuinely new pashmina buyer
    mock_search_results = [
        {
            "title": "Zenith Sound Healing Imports Ltd",
            "url": "https://www.zenithhealing.com",
            "snippet": "Tibetan singing bowls import@zenithhealing.com",
            "company_name": "Zenith Sound Imports Ltd",
            "email": "import@zenithhealing.com",
            "source_platform": "Google Search",
        },
        {
            "title": "Kashmir Pashmina Imports Ltd",
            "url": "https://www.kashmircraft.co.uk",
            "snippet": "Handmade pashmina shawls and cashmere. Contact procurement at import@kashmircraft.co.uk",
            "company_name": "Kashmir Pashmina Imports Ltd",
            "email": "import@kashmircraft.co.uk",
            "source_platform": "Google Search",
            "country": "United Kingdom",
        },
    ]

    with patch("main.GoogleSearchAdapter.search", return_value=mock_search_results), \
         patch("main.FacebookSearchAdapter.search", return_value=[]), \
         patch("main.LinkedInSearchAdapter.search", return_value=[]), \
         patch("main.DirectorySearchAdapter.search", return_value=[]), \
         patch("main.WebsiteSearchAdapter.crawl_and_extract", return_value=[]):

        summary = run_discovery_only(
            keyword="Handmade Pashmina",
            max_results=10,
            data_dir=test_data_dir,
        )

        assert summary["existing_buyers"] == 1
        assert summary["accepted_items"] == 1  # Only Pashmina accepted; Zenith rejected by relevance filter
        assert summary["records_written"] == 1

        final_buyers = load_buyers(buyers_csv)
        assert len(final_buyers) == 2
        assert any(b["email"] == "import@zenithhealing.com" for b in final_buyers)  # Historical preserved
        assert any(b["email"] == "import@kashmircraft.co.uk" for b in final_buyers)  # New record written
