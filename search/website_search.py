"""
Website Search and Contact Inspector Adapter.

Politely inspects public website pages (e.g. Contact, About, Wholesale) of target domains
to discover company details, location, and procurement email contacts.
"""

import re
import time
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Any, Optional, Set
import requests
from bs4 import BeautifulSoup

from config import Config
from app_logging.activity_logger import logger
from extraction.data_extractor import (
    extract_buyers_from_website,
    extract_emails_from_html,
    clean_extracted_email,
)

# Standard candidate contact/wholesale endpoints
TARGET_PATH_CANDIDATES = [
    "",
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/wholesale",
    "/importers",
    "/distribution",
]


class WebsiteSearchAdapter:
    """Polite website crawler for discovering contact and company information."""

    PLATFORM_NAME = "Website Search"

    def __init__(
        self,
        target_domains: Optional[List[str]] = None,
        timeout: Any = 5.0,
        user_agent: Optional[str] = None,
        max_pages_per_site: int = 2,
        max_websites: Optional[int] = None,
        test_discovery: Optional[bool] = None,
    ):
        self.target_domains = target_domains or []
        self.timeout = timeout
        self.user_agent = user_agent or Config.DEFAULT_USER_AGENT
        self.max_pages_per_site = max_pages_per_site
        self.max_websites = max_websites or Config.MAX_WEBSITES_PER_RESULT
        self.test_discovery = Config.TEST_DISCOVERY if test_discovery is None else test_discovery

    def get_status(self) -> str:
        """Return the operational status of the adapter (LIVE or STUB)."""
        is_stub = self.test_discovery if self.test_discovery is not None else Config.TEST_DISCOVERY
        return "STUB" if is_stub else "LIVE"

    def _get_base_url(self, raw_url: str) -> str:
        """Extract scheme and netloc from URL."""
        if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = "https://" + raw_url
        parsed = urlparse(raw_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def inspect_website(self, root_url: str, keyword: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Politely inspect key public pages of a website for buyer information.
        Returns a list of extracted normalized buyer records with metadata.
        """
        base_url = self._get_base_url(root_url)
        logger.info(f"[{self.PLATFORM_NAME}] Inspecting target website: {root_url}")

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        visited_urls: Set[str] = set()
        discovered_buyers: List[Dict[str, Any]] = []
        pages_checked = 0

        # Step 1: Inspect the EXACT target URL first
        target_urls = [root_url]
        # Step 2: Add candidate subpaths relative to base URL
        for path in ["/contact", "/contact-us", "/about", "/about-us", "/wholesale"]:
            cand = urljoin(base_url, path)
            if cand.lower() not in [u.lower() for u in target_urls]:
                target_urls.append(cand)

        for u in target_urls:
            if pages_checked >= self.max_pages_per_site:
                break
            if u.lower() in visited_urls:
                continue
            visited_urls.add(u.lower())

            try:
                resp = requests.get(u, headers=headers, timeout=self.timeout)
                pages_checked += 1

                if resp.status_code == 200 and resp.text:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    page_title = soup.title.string.strip() if (soup.title and soup.title.string) else ""
                    text_content = soup.get_text(separator=" ")
                    snippet = text_content[:400].strip()

                    records = extract_buyers_from_website(
                        html_content=resp.text,
                        url=root_url,
                        title=page_title,
                        source_platform=self.PLATFORM_NAME,
                    )
                    for r in records:
                        r["title"] = page_title or r.get("company_name", "")
                        r["snippet"] = snippet
                        r["content"] = text_content[:2000]
                        if keyword:
                            r["keyword"] = keyword

                    email_records = [r for r in records if r.get("email")]
                    if email_records:
                        discovered_buyers.extend(email_records)
                        break
                    elif records and not discovered_buyers:
                        discovered_buyers.extend(records)
            except (requests.ConnectionError, requests.Timeout):
                if u == root_url and u == base_url:
                    break
                continue
            except Exception:
                continue

        return discovered_buyers

    def crawl_and_extract(self, urls: List[str], keyword: Optional[str] = None) -> List[Dict[str, Any]]:
        """Crawl a list of external URLs obtained from current search results and extract buyer records."""
        is_stub = self.test_discovery if self.test_discovery is not None else Config.TEST_DISCOVERY
        if is_stub:
            return self._get_synthetic_test_seeds(keyword or Config.SEARCH_KEYWORD)

        if not urls:
            return []

        results = []
        for u in urls:
            records = self.inspect_website(u, keyword=keyword)
            results.extend(records)
        return results

    def _get_synthetic_test_seeds(self, keyword: str) -> List[Dict[str, Any]]:
        """Return keyword-aligned seed catalog entries strictly for offline testing."""
        kw_clean = keyword.strip()
        kw_slug = re.sub(r"[^a-z0-9]", "", kw_clean.lower()) or "export"

        if "singing bowl" in kw_clean.lower():
            return [
                {
                    "title": "Kyoto Zen Harmonix Imports",
                    "buyer_name": "Kenji Sato",
                    "company_name": "Kyoto Zen Harmonix",
                    "snippet": f"Import catalog for traditional {kw_clean}, bells, and chimes. Wholesale queries: wholesale@kyotozenharmonix.jp",
                    "url": "https://www.kyotozenharmonix.jp/wholesale",
                    "website": "https://www.kyotozenharmonix.jp",
                    "country": "Japan",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": "Sol y Luna Importadores de Arte Sanador",
                    "buyer_name": "Mateo Morales",
                    "company_name": "Sol y Luna Distribuciones",
                    "snippet": f"Importador directo para España y Sudamérica. {kw_clean} al por mayor: compras@solylunadist.es",
                    "url": "https://www.solylunadist.es/contacto",
                    "website": "https://www.solylunadist.es",
                    "country": "Spain",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]

        return [
            {
                "title": f"Kyoto {kw_clean.title()} Imports",
                "buyer_name": "Kenji Sato",
                "company_name": f"Kyoto {kw_clean.title()} Trading",
                "snippet": f"Import catalog for traditional {kw_clean}, textiles, and luxury fabrics. Wholesale: wholesale@{kw_slug}kyoto.jp",
                "url": f"https://www.{kw_slug}kyoto.jp/wholesale",
                "website": f"https://www.{kw_slug}kyoto.jp",
                "country": "Japan",
                "source_platform": self.PLATFORM_NAME,
            },
            {
                "title": f"Sol y Luna Importadores de {kw_clean.title()}",
                "buyer_name": "Mateo Morales",
                "company_name": f"Sol y Luna {kw_clean.title()} Distribuciones",
                "snippet": f"Importador directo de {kw_clean} para Europa: compras@{kw_slug}solyluna.es",
                "url": f"https://www.{kw_slug}solyluna.es/contacto",
                "website": f"https://www.{kw_slug}solyluna.es",
                "country": "Spain",
                "source_platform": self.PLATFORM_NAME,
            },
        ]

    def search(
        self,
        keyword: str,
        max_results: Optional[int] = None,
        domain_list: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute website inspection across passed domains. If no domains provided, returns empty list in live mode.
        """
        limit = max_results or Config.MAX_WEBSITES_PER_RESULT
        if Config.TEST_DISCOVERY:
            logger.info(f"[{self.PLATFORM_NAME}] Test discovery mode active: returning keyword seed records.")
            return self._get_synthetic_test_seeds(keyword)[:limit]

        domains = domain_list or self.target_domains
        if not domains:
            return []

        logger.info(f"[{self.PLATFORM_NAME}] Querying target website catalogs for keyword: '{keyword}'")

        results: List[Dict[str, Any]] = []
        for d in domains[:limit]:
            try:
                records = self.inspect_website(d)
                for r in records:
                    results.append({
                        "title": r.get("company_name", d),
                        "buyer_name": r.get("buyer_name", ""),
                        "company_name": r.get("company_name", ""),
                        "email": r.get("email", ""),
                        "snippet": f"Catalog and buyer info for {keyword}",
                        "url": r.get("website", d),
                        "website": r.get("website", d),
                        "country": r.get("country", ""),
                        "source_platform": self.PLATFORM_NAME,
                    })
            except Exception as e:
                logger.warning(f"Failed to inspect website '{d}': {e}")
                continue

        return results[:limit]
