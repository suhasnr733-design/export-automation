"""
Unit tests for Phase 2: Real Buyer Discovery, Query Generation, and Extraction.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from search.query_builder import SearchQueryBuilder, DEFAULT_INTENT_MODIFIERS
from search.google_search import GoogleSearchAdapter
from search.website_search import WebsiteSearchAdapter
from extraction.data_extractor import (
    extract_company_name,
    extract_country,
    extract_buyer_name,
    calculate_relevance_score,
    extract_buyers_from_website,
    extract_buyers_from_search_results,
)
from app_logging.activity_logger import save_buyers, load_buyers


def test_query_builder_default_modifiers():
    """Verify SearchQueryBuilder generates expected queries with proper quoting."""
    builder = SearchQueryBuilder()
    queries = builder.build_queries("Singing Bowls")

    assert len(queries) == len(DEFAULT_INTENT_MODIFIERS)
    assert '"Singing Bowls" importer' in queries
    assert '"Singing Bowls" distributor' in queries
    assert '"Singing Bowls" wholesaler' in queries
    assert '"Singing Bowls" "contact"' in queries


def test_query_builder_custom_modifiers():
    """Verify custom modifier list and query limits."""
    builder = SearchQueryBuilder(modifiers=["importer", "distributor", "buyer"])
    queries = builder.build_queries("Tibetan Bowls", max_queries=2)

    assert len(queries) == 2
    assert queries[0] == '"Tibetan Bowls" importer'
    assert queries[1] == '"Tibetan Bowls" distributor'


def test_query_builder_dorks():
    """Verify generation of specialized search operators."""
    builder = SearchQueryBuilder()
    dorks = builder.build_targeted_dorks("Singing Bowls")
    assert any("inurl:contact" in d for d in dorks)
    assert any("inurl:wholesale" in d for d in dorks)


def test_extract_company_name():
    """Verify company name extraction from HTML OpenGraph, title tag, and domain name."""
    html_og = '<html><head><meta property="og:site_name" content="Zenith Sound Healing Ltd"></head></html>'
    assert extract_company_name(html_content=html_og) == "Zenith Sound Healing Ltd"

    html_title = '<html><head><title>Aura Wellness Wholesale - Contact Us</title></head></html>'
    assert extract_company_name(html_content=html_title) == "Aura Wellness Wholesale"

    # From domain name when no title
    assert extract_company_name(url="https://www.lotus-living.co.uk/contact") == "Lotus Living"


def test_extract_country_cctld_and_text():
    """Verify country detection from domain ccTLDs and textual address blocks."""
    # From ccTLD
    assert extract_country(url="https://www.aurawellness.de/contact") == "Germany"
    assert extract_country(url="https://www.soundsupplies.com.au") == "Australia"
    assert extract_country(url="https://www.zenithhealing.co.uk") == "United Kingdom"
    assert extract_country(url="https://www.maplewellness.ca") == "Canada"
    assert extract_country(url="https://www.solyluna.es") == "Spain"

    # From text content
    text_usa = "Our headquarters is located in Austin, Texas, United States. Call +1-555-0199."
    assert extract_country(text=text_usa, url="https://example.com") == "United States"

    # Uncertain / No data -> blank
    assert extract_country(text="Contact us at info@genericdomain.com", url="https://genericdomain.com") == ""


def test_extract_buyer_name():
    """Verify extraction of contact person names from public text."""
    text_with_name = "For wholesale export catalogs, Contact Person: Marcus Vance (Procurement)."
    assert extract_buyer_name(text_with_name) == "Marcus Vance"

    # Without explicit name -> blank
    text_without_name = "Welcome to our store. Send us a message below."
    assert extract_buyer_name(text_without_name) == ""


def test_calculate_relevance_score():
    """Verify relevance scoring calculates appropriate weight for target and trade keywords."""
    relevant_text = "We are an importer and wholesaler of authentic singing bowls, gongs, and sound healing supplies."
    score = calculate_relevance_score(relevant_text, keyword="singing bowls")
    assert score > 5.0

    irrelevant_text = "Learn how to play acoustic guitar with our free beginner video lessons."
    low_score = calculate_relevance_score(irrelevant_text, keyword="singing bowls")
    assert low_score == 0.0


def test_extract_buyers_from_website():
    """Verify full extraction from a website HTML document."""
    html = """
    <html>
        <head>
            <meta property="og:site_name" content="Himalayan Sound Imports LLC">
            <title>Wholesale Singing Bowls - Contact Us</title>
        </head>
        <body>
            <h1>Direct Wholesaler & Importer</h1>
            <p>Attn: Tenzin Norbu (Import Director)</p>
            <p>Email our procurement desk: <a href="mailto:purchasing@himalayansound.de">purchasing@himalayansound.de</a></p>
            <p>Located in Munich, Germany.</p>
        </body>
    </html>
    """
    records = extract_buyers_from_website(
        html_content=html,
        url="https://www.himalayansound.de/contact",
        source_platform="Website Search",
    )

    assert len(records) == 1
    rec = records[0]
    assert rec["email"] == "purchasing@himalayansound.de"
    assert rec["company_name"] == "Himalayan Sound Imports LLC"
    assert rec["country"] == "Germany"
    assert rec["buyer_name"] == "Tenzin Norbu"
    assert rec["source_platform"] == "Website Search"


def test_google_search_adapter_deduplication():
    """Verify GoogleSearchAdapter deduplicates URLs across queries."""
    adapter = GoogleSearchAdapter()
    results = adapter.search("Singing Bowls", max_results=5, use_live_web=False)

    urls = [r["url"].lower() for r in results]
    assert len(urls) == len(set(urls)), "Search results must have unique URLs"


def test_website_search_graceful_failure():
    """Verify WebsiteSearchAdapter handles connection timeouts and errors without crashing."""
    adapter = WebsiteSearchAdapter(timeout=(0.1, 0.1))

    # Inspect connection-refused address
    records = adapter.inspect_website("http://127.0.0.1:59999")
    assert isinstance(records, list)
    assert len(records) == 0


def test_discovery_persistence_and_deduplication(tmp_path):
    """Verify discovery records are saved and deduplicated in buyers.csv."""
    csv_file = tmp_path / "buyers.csv"

    initial_buyers = [
        {"buyer_name": "Marcus", "company_name": "Zenith", "email": "marcus@zenith.com", "website": "https://zenith.com", "country": "USA", "source_platform": "Google Search"}
    ]
    save_buyers(initial_buyers, csv_path=csv_file)

    new_batch = [
        {"buyer_name": "Marcus", "company_name": "Zenith", "email": "MARCUS@ZENITH.COM", "website": "https://zenith.com", "country": "USA", "source_platform": "Google Search"},  # Duplicate
        {"buyer_name": "Elena", "company_name": "Aura", "email": "elena@aura.de", "website": "https://aura.de", "country": "Germany", "source_platform": "Website Search"},     # New
    ]

    saved_count = save_buyers(new_batch, csv_path=csv_file, append=True)
    assert saved_count == 1

    loaded = load_buyers(csv_file)
    assert len(loaded) == 2
    assert loaded[0]["email"] == "marcus@zenith.com"
    assert loaded[1]["email"] == "elena@aura.de"
