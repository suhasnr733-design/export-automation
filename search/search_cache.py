"""
Search Results Cache Module.
Provides thread-safe caching of search engine responses keyed strictly by:
- Search Keyword (e.g. 'Handmade Pashmina')
- Exact Query String (e.g. '"Handmade Pashmina" importer')
- Search Source / Adapter Name (e.g. 'Google Search')

Ensures that results cached for one product keyword can never leak into another.
"""

from typing import Dict, List, Any, Optional, Tuple
import threading
import time


class SearchCache:
    """Isolated in-memory cache for search adapter queries."""

    _instance: Optional["SearchCache"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "SearchCache":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
            return cls._instance

    @staticmethod
    def _make_key(keyword: str, query: str, source: str) -> Tuple[str, str, str]:
        return (
            str(keyword).strip().lower(),
            str(query).strip().lower(),
            str(source).strip().lower(),
        )

    def get(self, keyword: str, query: str, source: str, max_age_seconds: float = 3600.0) -> Optional[List[Dict[str, Any]]]:
        """Retrieve cached search results if keyword, query, and source match exactly."""
        key = self._make_key(keyword, query, source)
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                timestamp = entry.get("timestamp", 0)
                if (time.time() - timestamp) <= max_age_seconds:
                    return list(entry.get("results", []))
                else:
                    # Expired
                    del self._cache[key]
        return None

    def set(self, keyword: str, query: str, source: str, results: List[Dict[str, Any]]) -> None:
        """Store results associated strictly with the target keyword, query, and source."""
        key = self._make_key(keyword, query, source)
        with self._lock:
            self._cache[key] = {
                "timestamp": time.time(),
                "results": [dict(r) for r in results],
            }

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._cache)
