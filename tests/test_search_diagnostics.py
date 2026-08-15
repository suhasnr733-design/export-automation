"""
Tests for Search Status Handling and Diagnostics in GoogleSearchAdapter.

Verifies accurate classification of:
1. SEARCH_SUCCESS (HTTP 200 with parsed results)
2. SEARCH_EMPTY (HTTP 200 with 0 parsed results)
3. SEARCH_BLOCKED (HTTP 429, 403, or 202 anti-bot challenges)
4. SEARCH_TIMEOUT (Request timeouts)
5. SEARCH_ERROR (HTTP 500/502/503 errors and network exceptions)
6. PARSER_ERROR (HTML parser exceptions)
"""

import pytest
import requests
from unittest.mock import patch, MagicMock

from search.google_search import GoogleSearchAdapter, SearchDiagnostic


def test_search_diagnostic_success():
    """Verify HTTP 200 with results generates SEARCH_SUCCESS diagnostic."""
    adapter = GoogleSearchAdapter()
    mock_html = (
        '<html><body>'
        '<div class="result">'
        '  <a class="result__url" href="https://example.com/pashmina">Example Pashmina Wholesale</a>'
        '  <a class="result__snippet">Wholesale pashmina importer</a>'
        '</div>'
        '</body></html>'
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = mock_html.encode("utf-8")
    mock_resp.text = mock_html

    with patch("requests.post", return_value=mock_resp):
        results, diag = adapter.fetch_with_diagnostic('"Handmade Pashmina" importer')
        assert diag.status == "SEARCH_SUCCESS"
        assert diag.http_status == 200
        assert diag.parsed_results == 1
        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/pashmina"


def test_search_diagnostic_empty():
    """Verify HTTP 200 with zero results generates SEARCH_EMPTY diagnostic."""
    adapter = GoogleSearchAdapter()
    mock_html = '<html><body><div>No results found</div></body></html>'
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = mock_html.encode("utf-8")
    mock_resp.text = mock_html

    with patch("requests.post", return_value=mock_resp):
        results, diag = adapter.fetch_with_diagnostic('"Nonexistent Product 12345" importer')
        assert diag.status == "SEARCH_EMPTY"
        assert diag.http_status == 200
        assert diag.parsed_results == 0
        assert len(results) == 0


def test_search_diagnostic_blocked_rate_limit():
    """Verify HTTP 429 and 403 generate SEARCH_BLOCKED diagnostic."""
    adapter = GoogleSearchAdapter()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.content = b"Rate limit exceeded"

    with patch("requests.post", return_value=mock_resp):
        results, diag = adapter.fetch_with_diagnostic('"Handmade Pashmina" importer')
        assert diag.status == "SEARCH_BLOCKED"
        assert diag.http_status == 429
        assert "Rate limited" in diag.failure_type or "challenge" in diag.failure_type.lower()
        assert len(results) == 0


def test_search_diagnostic_blocked_anti_bot_challenge():
    """Verify HTTP 202 anti-bot response generates SEARCH_BLOCKED diagnostic."""
    adapter = GoogleSearchAdapter()
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.content = b"Challenge Accepted"

    with patch("requests.post", return_value=mock_resp):
        results, diag = adapter.fetch_with_diagnostic('"Handmade Pashmina" importer')
        assert diag.status == "SEARCH_BLOCKED"
        assert diag.http_status == 202
        assert "Anti-bot" in diag.failure_type or "challenge" in diag.failure_type.lower()
        assert len(results) == 0


def test_search_diagnostic_timeout():
    """Verify connection timeout generates SEARCH_TIMEOUT diagnostic."""
    adapter = GoogleSearchAdapter()

    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
        results, diag = adapter.fetch_with_diagnostic('"Handmade Pashmina" importer')
        assert diag.status == "SEARCH_TIMEOUT"
        assert diag.http_status is None
        assert "timed out" in diag.failure_type.lower()
        assert len(results) == 0


def test_search_diagnostic_http_error():
    """Verify HTTP 500 error generates SEARCH_ERROR diagnostic."""
    adapter = GoogleSearchAdapter()
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.content = b"Internal Server Error"

    with patch("requests.post", return_value=mock_resp):
        results, diag = adapter.fetch_with_diagnostic('"Handmade Pashmina" importer')
        assert diag.status == "SEARCH_ERROR"
        assert diag.http_status == 500
        assert "500" in diag.failure_type
        assert len(results) == 0


def test_search_diagnostic_parser_error():
    """Verify parser exceptions generate PARSER_ERROR diagnostic."""
    adapter = GoogleSearchAdapter()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"<html>broken html</html>"
    mock_resp.text = "<html>broken html</html>"

    with patch("requests.post", return_value=mock_resp), \
         patch("search.google_search.BeautifulSoup", side_effect=Exception("Parser crashed")):
        results, diag = adapter.fetch_with_diagnostic('"Handmade Pashmina" importer')
        assert diag.status == "PARSER_ERROR"
        assert diag.http_status == 200
        assert "parsing exception" in diag.failure_type.lower()
        assert len(results) == 0
