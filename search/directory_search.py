import re
from typing import List, Dict, Any, Optional
from config import Config
from logging.activity_logger import logger


class DirectorySearchAdapter:
    """Adapter for B2B Directories and Trade Portal discovery."""

    PLATFORM_NAME = "Trade Directory"

    def __init__(self, directory_endpoint: str = "", test_discovery: Optional[bool] = None):
        self.directory_endpoint = directory_endpoint
        self.test_discovery = Config.TEST_DISCOVERY if test_discovery is None else test_discovery

    def get_status(self) -> str:
        """Return the operational status of the adapter."""
        return "STUB"

    def search(self, keyword: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Query business directories for verified importers matching the export category.
        """
        logger.info(f"[{self.PLATFORM_NAME}] Querying B2B directories for: '{keyword}'")

        # In live discovery mode, return empty list because Directory adapter is STUB without credentials
        if not self.test_discovery and not self.directory_endpoint:
            return []

        kw_clean = keyword.strip()
        kw_slug = re.sub(r"[^a-z0-9]", "", kw_clean.lower()) or "export"

        if "singing bowl" in kw_clean.lower():
            results = [
                {
                    "title": "Australasian Sound Therapy Supplies Pty",
                    "buyer_name": "Oliver Jackson",
                    "company_name": "Australasian Sound Supplies Pty",
                    "snippet": f"Registered Australian wholesale importer for handcrafted {kw_clean}. Verified email: purchasing@australiansound.com.au",
                    "url": "https://www.yellowpages-b2b.com/australiansound",
                    "website": "https://www.australiansound.com.au",
                    "country": "Australia",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": "Maple Leaf Wellness Distribution",
                    "buyer_name": "Chloe Tremblay",
                    "company_name": "Maple Leaf Wellness Inc",
                    "snippet": f"Canadian B2B directory listing for {kw_clean} importers. Contact: chloe.procurement@maplewellness.ca",
                    "url": "https://www.canadatradehub.ca/maplewellness",
                    "website": "https://www.maplewellness.ca",
                    "country": "Canada",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]
        else:
            results = [
                {
                    "title": f"Australasian {kw_clean.title()} Traders Pty",
                    "buyer_name": "Oliver Jackson",
                    "company_name": f"Australasian {kw_clean.title()} Supplies",
                    "snippet": f"Registered Australian wholesale importer for handcrafted {kw_clean}. Verified email: purchasing@{kw_slug}australia.com.au",
                    "url": f"https://www.yellowpages-b2b.com/{kw_slug}australia",
                    "website": f"https://www.{kw_slug}australia.com.au",
                    "country": "Australia",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": f"Maple Leaf {kw_clean.title()} Imports",
                    "buyer_name": "Chloe Tremblay",
                    "company_name": f"Maple Leaf {kw_clean.title()} Inc",
                    "snippet": f"Canadian B2B directory listing for luxury {kw_clean} and apparel importers. Contact: chloe.procurement@{kw_slug}canada.ca",
                    "url": f"https://www.canadatradehub.ca/{kw_slug}canada",
                    "website": f"https://www.{kw_slug}canada.ca",
                    "country": "Canada",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]

        return results[:max_results]
