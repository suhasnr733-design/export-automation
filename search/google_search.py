"""
Google and Public-Web Search Discovery Adapter.

Executes multi-intent search queries against public web search endpoints,
extracting prospective buyer URLs, page titles, and snippets.
"""

import re
import time
from urllib.parse import unquote, urlparse
from typing import List, Dict, Any, Optional, Tuple
import requests
from bs4 import BeautifulSoup

from config import Config
from app_logging.activity_logger import logger
from .query_builder import SearchQueryBuilder
from .search_cache import SearchCache


class SearchDiagnostic:
    """Diagnostic data container for live search queries."""

    def __init__(
        self,
        query: str,
        status: str,
        http_status: Optional[int] = None,
        response_received: bool = False,
        response_length: int = 0,
        parsed_results: int = 0,
        failure_type: Optional[str] = None,
        error_message: Optional[str] = None,
        endpoint: str = "",
    ):
        self.query = query
        self.status = status  # SEARCH_SUCCESS, SEARCH_EMPTY, SEARCH_BLOCKED, SEARCH_TIMEOUT, SEARCH_ERROR, PARSER_ERROR
        self.http_status = http_status
        self.response_received = response_received
        self.response_length = response_length
        self.parsed_results = parsed_results
        self.failure_type = failure_type
        self.error_message = error_message
        self.endpoint = endpoint

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "status": self.status,
            "http_status": self.http_status,
            "response_received": self.response_received,
            "response_length": self.response_length,
            "parsed_results": self.parsed_results,
            "failure_type": self.failure_type,
            "error_message": self.error_message,
            "endpoint": self.endpoint,
        }

    def format_report(self) -> str:
        lines = [
            f"Query            : {self.query}",
            f"Status           : {self.status}",
            f"HTTP status      : {self.http_status if self.http_status is not None else 'N/A'}",
            f"Response received: {'Yes' if self.response_received else 'No'} ({self.response_length} bytes)",
            f"Parsed results   : {self.parsed_results}",
            f"Failure type     : {self.failure_type or 'None'}",
        ]
        return "\n".join(lines)


class GoogleSearchAdapter:
    """Public web search adapter for discovering international buyers and distributors."""

    PLATFORM_NAME = "Google Search"

    def __init__(
        self,
        api_key: str = "",
        cse_id: str = "",
        user_agent: Optional[str] = None,
        timeout: float = 8.0,
        max_results: Optional[int] = None,
        test_discovery: Optional[bool] = None,
    ):
        self.api_key = api_key or getattr(Config, "GOOGLE_API_KEY", "")
        self.cse_id = cse_id or getattr(Config, "GOOGLE_CSE_ID", "")
        self.user_agent = user_agent or Config.DEFAULT_USER_AGENT
        self.timeout = timeout
        self.max_results = max_results or Config.MAX_SEARCH_RESULTS
        self.test_discovery = Config.TEST_DISCOVERY if test_discovery is None else test_discovery
        self.query_builder = SearchQueryBuilder()
        self.cache = SearchCache()
        self.last_diagnostics: List[SearchDiagnostic] = []

    def get_status(self) -> str:
        """Return the operational status of the adapter (LIVE or STUB)."""
        is_stub = self.test_discovery if self.test_discovery is not None else Config.TEST_DISCOVERY
        return "STUB" if is_stub else "LIVE"

    def _clean_search_url(self, raw_url: str) -> str:
        """Clean redirect links (e.g. DuckDuckGo / Google redirect wrappers) to direct URLs."""
        if not raw_url:
            return ""
        if "uddg=" in raw_url:
            match = re.search(r"uddg=([^&]+)", raw_url)
            if match:
                return unquote(match.group(1))
        if "/url?q=" in raw_url:
            match = re.search(r"/url\?q=([^&]+)", raw_url)
            if match:
                return unquote(match.group(1))
        return raw_url.strip()

    def fetch_with_diagnostic(self, query: str, max_items: int = 5) -> Tuple[List[Dict[str, Any]], SearchDiagnostic]:
        """
        Execute search query with explicit error classification and diagnostic tracking.
        Distinguishes:
        - SEARCH_SUCCESS
        - SEARCH_EMPTY
        - SEARCH_BLOCKED
        - SEARCH_TIMEOUT
        - SEARCH_ERROR
        - PARSER_ERROR
        """
        results: List[Dict[str, Any]] = []
        endpoint_url = "https://html.duckduckgo.com/html/"

        # 1. Check if Google Custom Search JSON API is configured
        if self.api_key and self.cse_id:
            api_endpoint = "https://www.googleapis.com/customsearch/v1"
            try:
                params = {
                    "key": self.api_key,
                    "cx": self.cse_id,
                    "q": query,
                    "num": min(max_items, 10),
                }
                resp = requests.get(api_endpoint, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    for it in items:
                        results.append({
                            "title": it.get("title", "").strip(),
                            "url": it.get("link", "").strip(),
                            "snippet": it.get("snippet", "").strip(),
                            "source_platform": self.PLATFORM_NAME,
                        })
                    status = "SEARCH_SUCCESS" if results else "SEARCH_EMPTY"
                    diag = SearchDiagnostic(
                        query=query,
                        status=status,
                        http_status=200,
                        response_received=True,
                        response_length=len(resp.content),
                        parsed_results=len(results),
                        endpoint="Google Custom Search API",
                    )
                    return results, diag
                elif resp.status_code in (403, 429):
                    diag = SearchDiagnostic(
                        query=query,
                        status="SEARCH_BLOCKED",
                        http_status=resp.status_code,
                        response_received=True,
                        response_length=len(resp.content),
                        failure_type=f"Google API Quota / Rate limit exceeded (HTTP {resp.status_code})",
                        endpoint="Google Custom Search API",
                    )
                    return [], diag
                else:
                    diag = SearchDiagnostic(
                        query=query,
                        status="SEARCH_ERROR",
                        http_status=resp.status_code,
                        response_received=True,
                        response_length=len(resp.content),
                        failure_type=f"Google API Error (HTTP {resp.status_code})",
                        endpoint="Google Custom Search API",
                    )
                    return [], diag
            except requests.exceptions.Timeout:
                diag = SearchDiagnostic(
                    query=query,
                    status="SEARCH_TIMEOUT",
                    failure_type="Connection Timeout to Google Custom Search API",
                    endpoint="Google Custom Search API",
                )
                return [], diag
            except Exception as e:
                diag = SearchDiagnostic(
                    query=query,
                    status="SEARCH_ERROR",
                    failure_type=f"Google Custom Search API Exception: {e}",
                    error_message=str(e),
                    endpoint="Google Custom Search API",
                )
                return [], diag

        # 2. Public Web Search via HTML Endpoint with standard browser headers
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        data = {"q": query, "b": ""}

        try:
            resp = requests.post(endpoint_url, data=data, headers=headers, timeout=self.timeout)
            resp_length = len(resp.content)
            http_code = resp.status_code

            # Check for bot block or rate limiting
            if http_code in (403, 429):
                diag = SearchDiagnostic(
                    query=query,
                    status="SEARCH_BLOCKED",
                    http_status=http_code,
                    response_received=True,
                    response_length=resp_length,
                    failure_type=f"Rate limited or forbidden by search engine (HTTP {http_code})",
                    endpoint=endpoint_url,
                )
                return [], diag

            if http_code == 202:
                # 202 Accepted without search results indicates anti-bot challenge
                diag = SearchDiagnostic(
                    query=query,
                    status="SEARCH_BLOCKED",
                    http_status=202,
                    response_received=True,
                    response_length=resp_length,
                    failure_type="Anti-bot challenge or CAPTCHA required (HTTP 202 Accepted)",
                    endpoint=endpoint_url,
                )
                return [], diag

            if http_code != 200:
                diag = SearchDiagnostic(
                    query=query,
                    status="SEARCH_ERROR",
                    http_status=http_code,
                    response_received=True,
                    response_length=resp_length,
                    failure_type=f"Unexpected HTTP status {http_code}",
                    endpoint=endpoint_url,
                )
                return [], diag

            # Parse HTML content
            try:
                soup = BeautifulSoup(resp.text, "html.parser")
                result_elements = soup.find_all("div", class_=re.compile(r"result\s|results_links"))
                if not result_elements:
                    result_elements = soup.find_all("div", class_="result")

                for res_elem in result_elements:
                    title_elem = (
                        res_elem.find("a", class_="result__url")
                        or res_elem.find("a", class_="result__a")
                        or res_elem.find("a", class_=re.compile(r"result__snippet|result__url|result__a"))
                        or res_elem.find("a")
                    )
                    snippet_elem = res_elem.find("a", class_="result__snippet") or res_elem.find(class_=re.compile(r"snippet"))

                    if title_elem and title_elem.get("href"):
                        link = self._clean_search_url(title_elem["href"])
                        title = title_elem.get_text().strip()
                        snippet = snippet_elem.get_text().strip() if snippet_elem else ""

                        if link.startswith("http") and "duckduckgo.com" not in link:
                            results.append({
                                "title": title,
                                "url": link,
                                "snippet": snippet,
                                "source_platform": self.PLATFORM_NAME,
                            })
                            if len(results) >= max_items:
                                break

                if results:
                    status = "SEARCH_SUCCESS"
                    failure_type = None
                else:
                    status = "SEARCH_EMPTY"
                    failure_type = "Search engine returned 0 result items for query"

                diag = SearchDiagnostic(
                    query=query,
                    status=status,
                    http_status=200,
                    response_received=True,
                    response_length=resp_length,
                    parsed_results=len(results),
                    failure_type=failure_type,
                    endpoint=endpoint_url,
                )
                return results, diag

            except Exception as pe:
                diag = SearchDiagnostic(
                    query=query,
                    status="PARSER_ERROR",
                    http_status=200,
                    response_received=True,
                    response_length=resp_length,
                    failure_type=f"HTML parsing exception: {pe}",
                    error_message=str(pe),
                    endpoint=endpoint_url,
                )
                return [], diag

        except requests.exceptions.Timeout:
            diag = SearchDiagnostic(
                query=query,
                status="SEARCH_TIMEOUT",
                failure_type=f"Request timed out after {self.timeout}s",
                endpoint=endpoint_url,
            )
            return [], diag
        except Exception as ge:
            diag = SearchDiagnostic(
                query=query,
                status="SEARCH_ERROR",
                failure_type=f"Network exception: {ge}",
                error_message=str(ge),
                endpoint=endpoint_url,
            )
            return [], diag

    def _fetch_public_search(self, query: str, max_items: int = 5) -> List[Dict[str, Any]]:
        """Fetch search items and record diagnostic metadata."""
        results, diag = self.fetch_with_diagnostic(query, max_items=max_items)
        self.last_diagnostics.append(diag)
        return results

    def _get_synthetic_test_seeds(self, keyword: str) -> List[Dict[str, Any]]:
        """
        Keyword-aware synthetic seed generator strictly for offline test suites (when use_live_web=False).
        Never called in live web discovery.
        """
        kw_clean = keyword.strip()
        kw_slug = re.sub(r"[^a-z0-9]", "", kw_clean.lower()) or "export"

        if "singing bowl" in kw_clean.lower():
            return [
                {
                    "title": "Zenith Sound Healing Imports Ltd",
                    "buyer_name": "Marcus Vance",
                    "company_name": "Zenith Sound Healing Imports Ltd",
                    "snippet": f"Direct wholesale distributor of handcrafted Tibetan {kw_clean} and bells. Contact procurement at import@zenithhealing.com.",
                    "url": "https://www.zenithhealing.com",
                    "website": "https://www.zenithhealing.com",
                    "country": "United States",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": "Aura Wellness Wholesale Supplies",
                    "buyer_name": "Elena Rostova",
                    "company_name": "Aura Wellness Wholesale",
                    "snippet": f"Leading European importer of authentic {kw_clean}, gongs, and yoga accessories. Inquiries: contact@aurawellness.de",
                    "url": "https://www.aurawellness.de",
                    "website": "https://www.aurawellness.de",
                    "country": "Germany",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": "Lotus Living Retail & Distribution",
                    "buyer_name": "Sophie Turner",
                    "company_name": "Lotus Living Global",
                    "snippet": f"Retail chain sourcing artisanal {kw_clean}. Reach our buyer desk at buyer.sophie@lotusliving.co.uk",
                    "url": "https://www.lotusliving.co.uk",
                    "website": "https://www.lotusliving.co.uk",
                    "country": "United Kingdom",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]

        # Dynamic keyword-aligned seed records for non-Singing Bowls test keywords (e.g. Pashmina)
        return [
            {
                "title": f"{kw_clean.title()} Wholesale Global Ltd",
                "buyer_name": "Marcus Vance",
                "company_name": f"{kw_clean.title()} Imports International",
                "snippet": f"Direct wholesale distributor of authentic {kw_clean}, artisanal textiles, and shawls. Contact procurement at import@{kw_slug}wholesale.com.",
                "url": f"https://www.{kw_slug}wholesale.com",
                "website": f"https://www.{kw_slug}wholesale.com",
                "country": "United States",
                "source_platform": self.PLATFORM_NAME,
            },
            {
                "title": f"European {kw_clean.title()} & Cashmere Distribution",
                "buyer_name": "Elena Rostova",
                "company_name": f"Aura {kw_clean.title()} Wholesale",
                "snippet": f"Leading European importer and distributor of authentic {kw_clean} and luxury scarves. Inquiries: contact@{kw_slug}europe.de",
                "url": f"https://www.{kw_slug}europe.de",
                "website": f"https://www.{kw_slug}europe.de",
                "country": "Germany",
                "source_platform": self.PLATFORM_NAME,
            },
            {
                "title": f"British {kw_clean.title()} Traders Ltd",
                "buyer_name": "Sophie Turner",
                "company_name": f"Lotus {kw_clean.title()} Traders",
                "snippet": f"Wholesale procurement of handmade {kw_clean} and textiles. Reach our buyer desk at buyer.sophie@{kw_slug}traders.co.uk",
                "url": f"https://www.{kw_slug}traders.co.uk",
                "website": f"https://www.{kw_slug}traders.co.uk",
                "country": "United Kingdom",
                "source_platform": self.PLATFORM_NAME,
            },
        ]

    def search(
        self,
        keyword: str,
        max_results: Optional[int] = None,
        use_live_web: Optional[bool] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Execute multi-query search for prospective buyers across public search engines.
        Deduplicates URLs and returns structured raw results strictly relevant to the keyword.
        """
        limit = max_results or Config.MAX_SEARCH_RESULTS
        should_use_live = not Config.TEST_DISCOVERY if use_live_web is None else use_live_web

        queries = self.query_builder.build_queries(keyword, max_queries=4)
        logger.info(f"[{self.PLATFORM_NAME}] Executing {len(queries)} discovery queries for '{keyword}' (target max: {limit})")

        all_results: List[Dict[str, Any]] = []
        seen_urls = set()
        self.last_diagnostics = []

        if should_use_live:
            for q in queries:
                logger.info(f"[{self.PLATFORM_NAME}] Query: '{q}'")

                # Check keyword-isolated cache (bypass if force_refresh=True)
                cached_items = self.cache.get(keyword, q, self.PLATFORM_NAME) if not force_refresh else None
                if cached_items is not None:
                    items = cached_items
                else:
                    items = self._fetch_public_search(q, max_items=5)
                    self.cache.set(keyword, q, self.PLATFORM_NAME, items)

                for item in items:
                    u = item["url"].lower()
                    if u not in seen_urls:
                        seen_urls.add(u)
                        all_results.append(item)
                        if len(all_results) >= limit:
                            break

                if len(all_results) >= limit:
                    break

                if Config.SEARCH_DELAY > 0:
                    time.sleep(Config.SEARCH_DELAY)
        else:
            # Test / Offline mode only
            seed_items = self._get_synthetic_test_seeds(keyword)
            for item in seed_items:
                u = item["url"].lower()
                if u not in seen_urls:
                    seen_urls.add(u)
                    all_results.append(item)
                    if len(all_results) >= limit:
                        break

        logger.info(f"[{self.PLATFORM_NAME}] Discovery complete. Collected {len(all_results)} raw search items.")
        return all_results[:limit]
