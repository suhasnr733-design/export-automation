"""
Search Adapters Package for API 3 - EXPORT Automation System.
Provides interchangeable adapter interfaces for discovering export buyers across various channels.
"""

from .query_builder import SearchQueryBuilder, DEFAULT_INTENT_MODIFIERS
from .google_search import GoogleSearchAdapter
from .facebook_search import FacebookSearchAdapter
from .linkedin_search import LinkedInSearchAdapter
from .directory_search import DirectorySearchAdapter
from .website_search import WebsiteSearchAdapter
from .search_cache import SearchCache
from .relevance_filter import RelevanceAudit, evaluate_result_relevance

__all__ = [
    "SearchQueryBuilder",
    "DEFAULT_INTENT_MODIFIERS",
    "GoogleSearchAdapter",
    "FacebookSearchAdapter",
    "LinkedInSearchAdapter",
    "DirectorySearchAdapter",
    "WebsiteSearchAdapter",
    "SearchCache",
    "RelevanceAudit",
    "evaluate_result_relevance",
]
