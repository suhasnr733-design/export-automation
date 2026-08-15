import re
from typing import List, Dict, Any, Optional
from config import Config
from app_logging.activity_logger import logger


class LinkedInSearchAdapter:
    """Adapter for LinkedIn discovery."""

    PLATFORM_NAME = "LinkedIn"

    def __init__(self, api_key: str = "", test_discovery: Optional[bool] = None):
        self.api_key = api_key
        self.test_discovery = Config.TEST_DISCOVERY if test_discovery is None else test_discovery

    def get_status(self) -> str:
        """Return the operational status of the adapter."""
        return "STUB"

    def search(self, keyword: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Execute search for procurement contacts and international buyers.
        """
        logger.info(f"[{self.PLATFORM_NAME}] Querying trade specialists for keyword: '{keyword}'")

        # In live discovery mode, return empty list because LinkedIn adapter is STUB without credentials
        if not self.test_discovery and not self.api_key:
            return []

        kw_clean = keyword.strip()
        kw_slug = re.sub(r"[^a-z0-9]", "", kw_clean.lower()) or "export"

        if "singing bowl" in kw_clean.lower():
            results = [
                {
                    "title": "Liam O'Connor - Head of Global Procurement",
                    "buyer_name": "Liam O'Connor",
                    "company_name": "Celtic Wellbeing Distribution",
                    "snippet": f"Sourcing {kw_clean} and handcrafted bells for 40+ stores across Ireland and UK. Email: liam@celticwellbeing.ie",
                    "url": "https://www.linkedin.com/in/liam-oconnor-procure",
                    "website": "https://www.celticwellbeing.ie",
                    "country": "Ireland",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": "Klaus Schmidt - Import Manager",
                    "buyer_name": "Klaus Schmidt",
                    "company_name": "Alpen Sound & Spa Imports",
                    "snippet": f"Importing high quality {kw_clean}. Contact: klaus.s@alpensound.at",
                    "url": "https://www.linkedin.com/in/klaus-schmidt-trade",
                    "website": "https://www.alpensound.at",
                    "country": "Austria",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]
        else:
            results = [
                {
                    "title": f"Liam O'Connor - Head of Procurement ({kw_clean.title()})",
                    "buyer_name": "Liam O'Connor",
                    "company_name": f"Celtic {kw_clean.title()} & Textiles",
                    "snippet": f"Sourcing {kw_clean}, artisan shawls, and fabrics for luxury stores across Ireland and UK. Email: liam@{kw_slug}celtic.ie",
                    "url": f"https://www.linkedin.com/in/liam-{kw_slug}-procure",
                    "website": f"https://www.{kw_slug}celtic.ie",
                    "country": "Ireland",
                    "source_platform": self.PLATFORM_NAME,
                },
                {
                    "title": f"Klaus Schmidt - Senior Buyer ({kw_clean.title()})",
                    "buyer_name": "Klaus Schmidt",
                    "company_name": f"Alpen {kw_clean.title()} Distribution",
                    "snippet": f"Importing handcrafted {kw_clean} and luxury accessories. Contact: klaus.s@{kw_slug}alpen.at",
                    "url": f"https://www.linkedin.com/in/klaus-{kw_slug}-trade",
                    "website": f"https://www.{kw_slug}alpen.at",
                    "country": "Austria",
                    "source_platform": self.PLATFORM_NAME,
                },
            ]

        return results[:max_results]
