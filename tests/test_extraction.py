"""
Unit tests for Data Extraction Module.
"""

import pytest
from extraction.data_extractor import (
    extract_emails_from_text,
    extract_emails_from_html,
    clean_extracted_email,
    create_buyer_record,
    extract_buyers_from_search_results,
)


def test_clean_extracted_email():
    """Verify extraneous punctuation is stripped from extracted emails."""
    assert clean_extracted_email("contact@company.com.") == "contact@company.com"
    assert clean_extracted_email("<info@zenith.org>") == "info@zenith.org"
    assert clean_extracted_email("(sales@aura.de),") == "sales@aura.de"
    assert clean_extracted_email("  SUPPORT@SHOP.COM; ") == "support@shop.com"


def test_extract_emails_from_text():
    """Verify email extraction from free unstructured text."""
    text = (
        "Please send wholesale price catalogs to import@zenithhealing.com or reach our "
        "regional representative at contact.eu@zenithhealing.de. Avoid spamming support@zenithhealing.com."
    )
    emails = extract_emails_from_text(text)
    assert len(emails) == 3
    assert "import@zenithhealing.com" in emails
    assert "contact.eu@zenithhealing.de" in emails
    assert "support@zenithhealing.com" in emails


def test_extract_emails_from_html():
    """Verify extraction from HTML links (mailto:) and embedded content."""
    html_sample = """
    <html>
        <body>
            <h1>Contact Wholesale Team</h1>
            <p>Direct inquiries: <a href="mailto:purchasing@lotusimports.com?subject=Export">Email Us</a></p>
            <div>General office: info@lotusimports.com</div>
        </body>
    </html>
    """
    emails = extract_emails_from_html(html_sample)
    assert len(emails) == 2
    assert "purchasing@lotusimports.com" in emails
    assert "info@lotusimports.com" in emails


def test_extract_buyers_from_search_results():
    """Verify conversion of raw search adapter results into structured buyer records."""
    mock_search_results = [
        {
            "title": "Zenith Sound Imports",
            "buyer_name": "Marcus Vance",
            "snippet": "Tibetan bowl distributors. Contact wholesale@zenith.com for catalog.",
            "url": "https://www.zenith.com",
            "country": "United States",
            "source_platform": "Google Search",
        },
        {
            "title": "Aura Wellness Supplies",
            "buyer_name": "Elena Rostova",
            "snippet": "German wholesaler. Email contact: elena@aurawellness.de",
            "url": "https://www.aurawellness.de",
            "country": "Germany",
            "source_platform": "Trade Directory",
        },
    ]

    buyers = extract_buyers_from_search_results(mock_search_results)
    assert len(buyers) == 2

    b1 = buyers[0]
    assert b1["buyer_name"] == "Marcus Vance"
    assert b1["email"] == "wholesale@zenith.com"
    assert b1["website"] == "https://www.zenith.com"
    assert b1["country"] == "United States"
    assert b1["source_platform"] == "Google Search"


def test_create_buyer_record_schema():
    """Verify buyer record contains all required normalized keys."""
    record = create_buyer_record(
        buyer_name="John Doe",
        company_name="Acme Importers",
        email="john@acme.com",
        website="https://acme.com",
        country="Canada",
        source_platform="LinkedIn",
    )
    expected_keys = {"buyer_name", "company_name", "email", "website", "country", "source_platform"}
    assert set(record.keys()) == expected_keys
    assert record["email"] == "john@acme.com"
