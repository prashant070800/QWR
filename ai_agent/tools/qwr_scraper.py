"""QWR website context fetcher.

Fetches and caches content from questionwhatsreal.com pages so the AI agent
can answer QWR-specific questions accurately using live website data.

The module maintains an in-memory TTL cache keyed by URL.  On a cache miss it
fetches the page with httpx, converts it to clean text, and stores it.

Usage
-----
    from ai_agent.tools.qwr_scraper import QWRScraper

    scraper = QWRScraper()
    context = await scraper.get_context("What products does QWR make?")
    # Returns: combined text from the most relevant QWR pages
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from ai_agent.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# QWR page catalogue — maps topic keywords to page URLs
# ---------------------------------------------------------------------------

QWR_PAGES: dict[str, str] = {
    "home": "https://questionwhatsreal.com/",
    "about": "https://questionwhatsreal.com/about",
    "products": "https://questionwhatsreal.com/products",
    "odm": "https://questionwhatsreal.com/odm",
    "sdk": "https://questionwhatsreal.com/sdk",
    "humbl": "https://questionwhatsreal.com/humbl",
    "defence": "https://questionwhatsreal.com/defence",
    "education": "https://questionwhatsreal.com/industry-education",
    "healthcare": "https://questionwhatsreal.com/industry-healthcare",
    "manufacturing": "https://questionwhatsreal.com/industry-manufacturing",
    "enterprise": "https://questionwhatsreal.com/enterprise",
    "technology": "https://questionwhatsreal.com/technology",
    "contact": "https://questionwhatsreal.com/contact",
    "vrone_pro": "https://questionwhatsreal.com/product-vrone-pro",
    "vrone_edu": "https://questionwhatsreal.com/product-vrone-edu",
    "vrone_4k": "https://questionwhatsreal.com/product-vrone-4k",
    "humbl_ar": "https://questionwhatsreal.com/product-humbl-ar",
}

# Keywords that trigger fetching specific pages
KEYWORD_PAGE_MAP: dict[str, list[str]] = {
    "about": ["about", "company", "founded", "suraj", "history", "pune", "headquarter"],
    "products": ["product", "vr", "ar", "headset", "glasses", "wearable", "humbl", "vrone"],
    "defence": ["defence", "defense", "military", "army", "tactical", "soldier"],
    "education": ["education", "school", "student", "learner", "nep"],
    "healthcare": ["health", "medical", "hospital", "clinical", "surgical"],
    "odm": ["odm", "oem", "manufacture", "partner", "customiz"],
    "sdk": ["sdk", "api", "developer", "software", "integrate"],
    "technology": ["optic", "waveguide", "display", "micro-oled", "technology"],
    "humbl": ["humbl", "ai glasses", "voice", "multimodal"],
    "enterprise": ["enterprise", "corporate", "business"],
    "contact": ["contact", "email", "phone", "reach", "talk"],
}


@dataclass
class _CacheEntry:
    content: str
    fetched_at: float = field(default_factory=time.monotonic)


class QWRScraper:
    """Fetches and caches QWR website content for AI context."""

    def __init__(self, cache_ttl_seconds: int = 3600) -> None:
        self._cache: dict[str, _CacheEntry] = {}
        self._ttl = cache_ttl_seconds
        self._fetch_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_context(self, query: str) -> str:
        """Return relevant QWR website text for *query*.

        Picks the most relevant pages based on keyword matching, fetches
        them (with caching), and returns combined plain text.
        """
        page_keys = self._select_pages(query)
        if not page_keys:
            # Always include home page as fallback
            page_keys = ["home", "about"]

        logger.info(
            "QWR scraper selected pages=%s for query=%r",
            page_keys,
            query[:80],
        )

        texts: list[str] = []
        for key in page_keys[:3]:  # limit to 3 pages per query
            url = QWR_PAGES.get(key, "")
            if not url:
                continue
            text = await self._get_page(url)
            if text:
                texts.append(f"=== Source: {url} ===\n{text}")

        combined = "\n\n".join(texts)
        logger.debug(
            "QWR context total_chars=%d pages=%s",
            len(combined),
            page_keys,
        )
        return combined

    async def get_page(self, url: str) -> str:
        """Fetch a specific URL directly."""
        return await self._get_page(url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _select_pages(self, query: str) -> list[str]:
        """Return ordered list of page keys relevant to *query*."""
        query_lower = query.lower()
        scores: dict[str, int] = {}

        for page_key, keywords in KEYWORD_PAGE_MAP.items():
            for kw in keywords:
                if kw in query_lower:
                    scores[page_key] = scores.get(page_key, 0) + 1

        # Sort by score desc; always prepend home for general context
        ordered = sorted(scores, key=lambda k: scores[k], reverse=True)
        if "home" not in ordered:
            ordered = ["home"] + ordered
        return ordered

    async def _get_page(self, url: str) -> str:
        """Return cached or freshly-fetched plain text for *url*."""
        cached = self._cache.get(url)
        if cached and (time.monotonic() - cached.fetched_at) < self._ttl:
            logger.debug("QWR cache hit url=%s", url)
            return cached.content

        async with self._fetch_lock:
            # Re-check after acquiring lock (another task may have fetched)
            cached = self._cache.get(url)
            if cached and (time.monotonic() - cached.fetched_at) < self._ttl:
                return cached.content

            text = await self._fetch(url)
            self._cache[url] = _CacheEntry(content=text)
            return text

    async def _fetch(self, url: str) -> str:
        """HTTP GET *url* and return clean plain text."""
        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "httpx is not installed. Run: pip install httpx"
            ) from exc

        logger.info("QWR scraper fetching url=%s", url)
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10.0,
                headers={"User-Agent": "QWR-VoiceBot/1.0 (+https://questionwhatsreal.com/)"},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                raw_html = response.text
        except Exception as exc:
            logger.error("QWR scraper fetch failed url=%s error=%s", url, exc)
            return ""

        text = self._html_to_text(raw_html)
        logger.info(
            "QWR scraper fetched url=%s text_chars=%d",
            url,
            len(text),
        )
        return text

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to plain text (no external dependency)."""
        # Remove script/style blocks
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Keep only printable ASCII + common Unicode
        return text[:1500]  # cap per page to keep context manageable (reduces input tokens for latency)


# Module-level singleton to share cache across calls and tasks
shared_scraper = QWRScraper(
    cache_ttl_seconds=settings.qwr_cache_ttl_seconds if "settings" in globals() else 3600
)

def warm_up_cache() -> None:
    """Trigger background fetching of home/about pages to warm up the cache."""
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            for page in ["home", "about"]:
                url = QWR_PAGES.get(page)
                if url:
                    loop.create_task(shared_scraper.get_page(url))
    except RuntimeError:
        # No running event loop during module load
        pass

warm_up_cache()
