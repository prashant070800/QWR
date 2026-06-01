import os
import sqlite3
import json
import time
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Locate database in the project root directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "vector_store.sqlite3")

class SQLiteVectorDB:
    """Lightweight, multi-tenant SQLite vector database with pure-Python cosine similarity."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Table to track crawling status per domain/business
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS businesses (
                    domain TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # Table to store text chunks and embeddings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    url TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_domain ON chunks(domain)")
            conn.commit()

    def get_business_status(self, domain: str) -> Optional[str]:
        """Get the indexing status for a domain (e.g. 'indexing', 'completed', 'failed')."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM businesses WHERE domain = ?", (domain,))
            row = cursor.fetchone()
            return row[0] if row else None

    def set_business_status(self, domain: str, status: str) -> None:
        """Set the indexing status for a domain."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO businesses (domain, status, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(domain) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at
            """, (domain, status, time.time()))
            conn.commit()

    def save_chunks(self, domain: str, chunks: list[dict[str, Any]]) -> None:
        """Save a list of chunks with their embeddings for a domain, replacing existing ones."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Clear existing chunks for this domain first
            cursor.execute("DELETE FROM chunks WHERE domain = ?", (domain,))
            
            # Batch insert new chunks
            insert_data = [
                (domain, chunk["url"], chunk["text"], json.dumps(chunk["embedding"]))
                for chunk in chunks
            ]
            cursor.executemany("""
                INSERT INTO chunks (domain, url, chunk_text, embedding)
                VALUES (?, ?, ?, ?)
            """, insert_data)
            
            conn.commit()
            logger.info("Saved %d chunks for domain=%s in SQLiteVectorDB", len(chunks), domain)

    def search(self, domain: str, query_embedding: list[float], top_k: int = 3) -> list[dict[str, Any]]:
        """Search the database for similar chunks belonging to a specific domain."""
        t0 = time.monotonic()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url, chunk_text, embedding FROM chunks WHERE domain = ?", (domain,))
            rows = cursor.fetchall()

        if not rows:
            return []

        # Pure-python cosine similarity
        results = []
        for url, chunk_text, emb_str in rows:
            try:
                emb = json.loads(emb_str)
                sim = self._cosine_similarity(query_embedding, emb)
                results.append({
                    "url": url,
                    "text": chunk_text,
                    "similarity": sim
                })
            except Exception as exc:
                logger.error("Failed parsing embedding for URL %s: %s", url, exc)

        # Sort by similarity desc
        results.sort(key=lambda x: x["similarity"], reverse=True)
        top_results = results[:top_k]
        
        latency_ms = (time.monotonic() - t0) * 1000
        logger.debug(
            "Vector search domain=%s results=%d time=%.2fms",
            domain,
            len(top_results),
            latency_ms
        )
        return top_results

    @staticmethod
    def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Compute cosine similarity between two float vectors."""
        dot_product = sum(x * y for x, y in zip(v1, v2))
        mag1 = sum(x * x for x in v1) ** 0.5
        mag2 = sum(x * x for x in v2) ** 0.5
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot_product / (mag1 * mag2)

    def get_first_chunks(self, domain: str, count: int = 3) -> list[str]:
        """Retrieve the first few chunks of text for a domain as a default fallback."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chunk_text FROM chunks WHERE domain = ? LIMIT ?", (domain, count))
            rows = cursor.fetchall()
            return [r[0] for r in rows]
