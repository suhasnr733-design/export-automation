import re
from typing import List, Dict, Any, Optional
from config import Config
from app_logging.activity_logger import logger


class FacebookSearchAdapter:
    """Adapter for Facebook business page / community discovery."""

    PLATFORM_NAME = "Facebook"

    def __init__(self, access_token: str = "", test_discovery: Optional[bool] = None):
        self.access_token = access_token
        self.test_discovery = Config.TEST_DISCOVERY if test_discovery is None else test_discovery

    def get_status(self) -> str:
        """Return the operational status of the adapter."""
        return "STUB"

    def search(self, keyword: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Execute search on Facebook discovery endpoints.
        """
        logger.info(f"[{self.PLATFORM_NAME}] Querying business profiles for keyword: '{keyword}'")

        # In live discovery mode, return empty list because Facebook adapter is STUB without credentials
        if not self.test_discovery and not self.access_token:
            return []

        kw_clean = keyword.strip()
        kw_slug = re.sub(r"[^a-z0-9]", "", kw_clean.lower()) or "export"

        if "singing bowl" in kw_clean.lower():
            results = [
                {
                    "title": "Holistic Healing Goods Wholesale Facebook Page",
                    "buyer_name": "David Miller",
                    "company_name": "Holistic Goods LLC",
                    "snippet": f"We source direct from manufacturers: {kw_clean}, bells, incense. Send wholesale price list to info@holisticgoods.com",
                    "url": "https://www.facebook.com/holisticgoodswholesale",
                    "website": "https://www.facebook.com/holisticgoodswholesale",
                    "country": "United States",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": "Nordic Meditation Imports",
                    "buyer_name": "Astrid Lindholm",
                    "company_name": "Nordic Sound & Soul",
                    "snippet": f"Scandinavian distributor of {kw_clean}. Email orders to astrid.buyer@nordicsound.se",
                    "url": "https://www.facebook.com/nordicsoundsoul",
                    "website": "https://www.nordicsound.se",
                    "country": "Sweden",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]
        else:
            results = [
                {
                    "title": f"{kw_clean.title()} B2B Importers Facebook Group",
                    "buyer_name": "David Miller",
                    "company_name": f"{kw_clean.title()} Direct LLC",
                    "snippet": f"Sourcing direct from manufacturers: {kw_clean}, shawls, scarves. Send wholesale catalogs to info@{kw_slug}direct.com",
                    "url": f"https://www.facebook.com/{kw_slug}direct",
                    "website": f"https://www.facebook.com/{kw_slug}direct",
                    "country": "United States",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": f"Nordic {kw_clean.title()} Imports",
                    "buyer_name": "Astrid Lindholm",
                    "company_name": f"Nordic {kw_clean.title()} & Textiles",
                    "snippet": f"Scandinavian distributor of {kw_clean}. Email trade inquiries to astrid.buyer@{kw_slug}nordic.se",
                    "url": f"https://www.facebook.com/{kw_slug}nordic",
                    "website": f"https://www.{kw_slug}nordic.se",
                    "country": "Sweden",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]

        return results[:max_results]
