"""
Search Query Builder Module for API 3 - EXPORT Automation System.
Generates configurable, multi-intent search query combinations to discover export buyers.
"""

from typing import List, Optional

# Commercial-intent modifiers tuned for the exact product keyword "Singing Bowls"
DEFAULT_INTENT_MODIFIERS = [
    "supplier",
    "importer",
    "wholesaler",
    "distributor",
    "manufacturer",
    "exporter",
    "wholesale",
    "B2B",
    "business buyer",
    "bulk buyer",
    "trade buyer",
    "procurement",
    "direct supplier",
    "retail supplier",
    "wholesale catalog",
    "contact",
    "inquiry",
    "dealer",
    "buying agent",
    "international buyer",
    "commercial buyer",
    "trade supplier",
    "import",
    "wholesale inquiry",
    "B2B buyer",
    # Singing Bowl specific modifiers
    "retailer",
    "seller",
    "shop",
    "store",
    "wellness",
    "healing",
    "yoga studio",
    "meditation center",
    "wellness center",
    "gift shop",
    "handmade",
    "artisan",
    "craft business",
    "boutique",
    "health store",
    "spiritual shop",
    "online store",
    "buy",
    "order",
    "purchase",
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
            f'{kw_phrase} "health food store"',
            f'{kw_phrase} "gift retailer"',
            f'{kw_phrase} inurl:shop OR inurl:store OR inurl:buy',
        ]

    def build_category_specific_queries(self, keyword: str) -> List[str]:
        """
        Generate product-category-specific search variations for deeper discovery.
        Particularly optimized for items like singing bowls that need retail/wellness focus.
        """
        clean_kw = keyword.strip()
        kw_phrase = f'"{clean_kw}"' if not clean_kw.startswith('"') else clean_kw

        queries = []
        kw_lower = clean_kw.lower()

        # Standard patterns for any product
        queries.extend([
            f'{kw_phrase} buy online',
            f'{kw_phrase} "contact us"',
            f'{kw_phrase} "order now"',
            f'{kw_phrase} price',
            f'{kw_phrase} supplier',
        ])

        # Singing Bowl specific patterns
        if 'singing bowl' in kw_lower or 'bowl' in kw_lower:
            queries.extend([
                f'{kw_phrase} wholesale',
                f'{kw_phrase} distributor',
                f'{kw_phrase} retailer',
                f'{kw_phrase} "handmade"',
                f'{kw_phrase} meditation',
                f'{kw_phrase} yoga',
                f'{kw_phrase} healing',
                f'{kw_phrase} wellness',
                f'{kw_phrase} spiritual',
                f'{kw_phrase} "sound bath"',
                f'{kw_phrase} musician',
                f'{kw_phrase} instrument store',
                f'{kw_phrase} gift',
                f'{kw_phrase} artisan',
            ])

        return queries
