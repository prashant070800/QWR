import asyncio
import logging
import re
import time
from urllib.parse import urlparse, urljoin
import httpx
import google.generativeai as genai

from ai_agent.config import settings
from ai_agent.tools.vector_db import SQLiteVectorDB

logger = logging.getLogger(__name__)

# Max pages to crawl per business domain to keep limits reasonable
MAX_PAGES_TO_CRAWL = 6
# Chunking settings
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

class BusinessCrawler:
    """Asynchronous crawler that crawls a business domain, chunks content, generates embeddings, and saves to SQLiteVectorDB."""

    def __init__(self, api_key: str | None = None) -> None:
        self.db = SQLiteVectorDB()
        self.api_key = api_key or settings.gemini_api_key
        # Configure Gemini SDK
        genai.configure(api_key=self.api_key)

    async def crawl_and_index(self, base_url: str) -> None:
        """Crawl the website, generate embeddings, and store them in SQLiteVectorDB."""
        parsed_base = urlparse(base_url)
        domain = parsed_base.netloc.lower()
        if not domain:
            logger.error("Invalid business URL: %s", base_url)
            return

        # Check if already completed or currently indexing
        status = self.db.get_business_status(domain)
        if status in ("indexing", "completed"):
            logger.info("Business domain=%s indexing status is already: %s", domain, status)
            return

        logger.info("Starting background crawl and index for domain=%s url=%s", domain, base_url)
        self.db.set_business_status(domain, "indexing")

        try:
            pages_to_crawl = [base_url.rstrip("/")]
            crawled_urls = set()
            all_chunks = []

            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10.0,
                headers={"User-Agent": "QWR-VoiceBot/1.0 (+https://questionwhatsreal.com/)"},
            ) as client:
                while pages_to_crawl and len(crawled_urls) < MAX_PAGES_TO_CRAWL:
                    url = pages_to_crawl.pop(0)
                    if url in crawled_urls:
                        continue

                    logger.info("Crawler fetching url=%s", url)
                    try:
                        response = await client.get(url)
                        if response.status_code != 200:
                            logger.warning("Crawler failed to fetch url=%s status=%d", url, response.status_code)
                            crawled_urls.add(url)
                            continue

                        html = response.text
                        crawled_urls.add(url)

                        # Extract text content
                        text = self._clean_html_to_text(html)
                        
                        # Chunk the text content
                        chunks = self._chunk_text(text)
                        for chunk in chunks:
                            all_chunks.append({
                                "url": url,
                                "text": chunk
                            })

                        # Extract internal links for further crawling
                        links = self._extract_internal_links(html, url, domain)
                        for link in links:
                            if link not in crawled_urls and link not in pages_to_crawl:
                                pages_to_crawl.append(link)

                    except Exception as e:
                        logger.error("Error crawling url=%s: %s", url, e)
                        crawled_urls.add(url)

            if not all_chunks:
                logger.warning("No content found/crawled for domain=%s", domain)
                self.db.set_business_status(domain, "failed")
                return

            # Batch generate embeddings using Gemini
            logger.info("Generating embeddings for %d chunks on domain=%s", len(all_chunks), domain)
            chunks_with_embeddings = await self._generate_embeddings_batch(all_chunks)

            # Store in SQLite
            self.db.save_chunks(domain, chunks_with_embeddings)
            self.db.set_business_status(domain, "completed")
            logger.info("Successfully completed indexing for domain=%s", domain)

        except Exception as exc:
            logger.exception("Crawler failed for domain=%s", domain)
            self.db.set_business_status(domain, "failed")

    def _extract_internal_links(self, html: str, current_url: str, domain: str) -> list[str]:
        """Extract links from the page that belong to the same domain."""
        links = set()
        pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        for match in pattern.finditer(html):
            link = match.group(1).strip()
            if not link or link.startswith("#") or link.startswith("javascript:") or link.startswith("tel:") or link.startswith("mailto:"):
                continue

            absolute_url = urljoin(current_url, link)
            parsed_abs = urlparse(absolute_url)

            # Keep only HTTP(S) links on the same domain
            if parsed_abs.netloc.lower() == domain and parsed_abs.scheme in ("http", "https"):
                # Clean URL (remove query params & trailing slash)
                clean_url = absolute_url.split("?")[0].split("#")[0].rstrip("/")
                links.add(clean_url)
        return list(links)

    def _clean_html_to_text(self, html: str) -> str:
        """Strip HTML tags and scripts to get clean text."""
        html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _chunk_text(self, text: str) -> list[str]:
        """Split text into smaller overlapping chunks."""
        chunks = []
        if len(text) <= CHUNK_SIZE:
            return [text]

        start = 0
        while start < len(text):
            end = start + CHUNK_SIZE
            chunks.append(text[start:end])
            start += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

    async def _generate_embeddings_batch(self, chunks: list[dict]) -> list[dict]:
        """Generate 768-dimensional embeddings for all chunks in batches using Gemini API."""
        # Batch size limits for Generative AI embedding calls
        batch_size = 30
        results = []
        
        loop = asyncio.get_running_loop()

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c["text"] for c in batch]
            
            try:
                # Wrap the synchronous google-generativeai call in an executor
                def _call_api():
                    return genai.embed_content(
                        model="models/gemini-embedding-001",
                        content=texts,
                        task_type="retrieval_document"
                    )

                response = await loop.run_in_executor(None, _call_api)
                
                # Check response structure
                embeddings = response.get("embedding", [])
                for chunk, embedding in zip(batch, embeddings):
                    chunk["embedding"] = embedding
                    results.append(chunk)
            except Exception as exc:
                logger.error("Failed generating embeddings for batch starting at %d: %s", i, exc)
                # Retry individually as fallback
                for c in batch:
                    try:
                        def _call_api_single():
                            return genai.embed_content(
                                model="models/gemini-embedding-001",
                                content=c["text"],
                                task_type="retrieval_document"
                            )
                        resp = await loop.run_in_executor(None, _call_api_single)
                        c["embedding"] = resp.get("embedding", [])
                        results.append(c)
                    except Exception as inner_exc:
                        logger.error("Failed individual embedding fallback: %s", inner_exc)
                        
        return results

# Helper function to trigger background crawl tasks
def trigger_crawl(business_url: str) -> None:
    """Schedule crawl in the background if domain is not indexed."""
    parsed = urlparse(business_url)
    domain = parsed.netloc.lower()
    if not domain:
        return

    db = SQLiteVectorDB()
    status = db.get_business_status(domain)
    if status is None:
        # Not indexed at all: start background task
        crawler = BusinessCrawler()
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(crawler.crawl_and_index(business_url))
        except RuntimeError:
            # Event loop not running yet (e.g. during wsgi import)
            pass
