"""
Search Query Builder Module for API 3 - EXPORT Automation System.
Generates configurable, multi-intent search query combinations to discover export buyers.
"""

from typing import List, Optional

# Standard commercial intent modifiers for B2B export discovery
DEFAULT_INTENT_MODIFIERS = [
    "importer",
    "distributor",
    "wholesaler",
    "wholesale",
    "retailer",
    "supplier",
    "buyer",
    "direct import",
    "procurement",
    "wholesale catalog",
    '"contact"',
    '"email"',
    '"import"',
]


class SearchQueryBuilder:
    """Constructs focused search queries targeting international buyers and importers."""

    def __init__(self, modifiers: Optional[List[str]] = None):
        self.modifiers = modifiers or list(DEFAULT_INTENT_MODIFIERS)

    def build_queries(
        self,
        keyword: str,
        modifiers: Optional[List[str]] = None,
        max_queries: Optional[int] = None,
    ) -> List[str]:
        """
        Generate search query strings combining keyword with trade intent modifiers.
        Ensures proper quoting of the root keyword.
        """
        clean_kw = keyword.strip()
        if not clean_kw:
            return []

        kw_phrase = f'"{clean_kw}"' if not clean_kw.startswith('"') else clean_kw
        mods = modifiers if modifiers is not None else self.modifiers

        queries = []
        for mod in mods:
            mod_clean = mod.strip()
            if mod_clean:
                queries.append(f"{kw_phrase} {mod_clean}")

        if max_queries and max_queries > 0:
            return queries[:max_queries]
        return queries

    @classmethod
    def build_discovery_queries(cls, keyword: str, max_queries: Optional[int] = None) -> List[str]:
        """Class method convenience helper to generate default discovery queries."""
        builder = cls()
        return builder.build_queries(keyword, max_queries=max_queries)

    def build_targeted_dorks(self, keyword: str) -> List[str]:
        """
        Generate search engine operators targeting contact and wholesale catalog pages.
        """
        clean_kw = keyword.strip()
        kw_phrase = f'"{clean_kw}"' if not clean_kw.startswith('"') else clean_kw

        return [
            f'{kw_phrase} inurl:contact',
            f'{kw_phrase} inurl:wholesale',
            f'{kw_phrase} inurl:about-us',
            f'{kw_phrase} "wholesale inquiry"',
            f'{kw_phrase} "procurement manager"',
        ]
