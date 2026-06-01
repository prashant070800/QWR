import os
import time
import uuid
import json
import sqlite3
import asyncio
import logging
from typing import Optional, Any, Dict, List
import httpx

from ai_agent.config import settings

logger = logging.getLogger(__name__)

# Reuse the vector store sqlite file for local storage to keep workspace clean
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_DB_PATH = os.path.join(BASE_DIR, "vector_store.sqlite3")

class CallStorage:
    """Storage adapter to persist profiles, calls, turns, and summaries.
    
    Supports local SQLite fallback or Supabase REST backend depending on environment config.
    """

    def __init__(self, db_path: str = LOCAL_DB_PATH) -> None:
        self.db_path = db_path
        self.supabase_url = settings.supabase_url.rstrip("/")
        self.supabase_key = settings.supabase_key
        self.use_supabase = bool(self.supabase_url and self.supabase_key)
        
        if self.use_supabase:
            logger.info("CallStorage initialized with SUPABASE REST backend at %s", self.supabase_url)
            self.headers = {
                "apikey": self.supabase_key,
                "Authorization": f"Bearer {self.supabase_key}",
                "Content-Type": "application/json"
            }
        else:
            logger.info("CallStorage initialized with LOCAL SQLITE fallback backend at %s", self.db_path)
            self._init_local_db()

    def _init_local_db(self) -> None:
        """Create tables for local sqlite store if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    phone TEXT UNIQUE NOT NULL,
                    name TEXT,
                    company TEXT,
                    role TEXT,
                    city TEXT,
                    email TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS calls (
                    id TEXT PRIMARY KEY,
                    call_sid TEXT UNIQUE NOT NULL,
                    stream_sid TEXT,
                    caller_number TEXT NOT NULL,
                    selected_mode TEXT,
                    duration INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    profile_id TEXT REFERENCES profiles(id) ON DELETE SET NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transcript_turns (
                    id TEXT PRIMARY KEY,
                    call_id TEXT REFERENCES calls(id) ON DELETE CASCADE NOT NULL,
                    seq_number INTEGER NOT NULL,
                    speaker TEXT NOT NULL,
                    text TEXT NOT NULL,
                    latency_ms INTEGER,
                    created_at REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    id TEXT PRIMARY KEY,
                    call_id TEXT REFERENCES calls(id) ON DELETE CASCADE NOT NULL,
                    summary_text TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    destination TEXT,
                    created_at REAL NOT NULL
                )
            """)
            conn.commit()

    # ------------------------------------------------------------------
    # Profiles API
    # ------------------------------------------------------------------

    async def get_or_create_profile(self, phone: str) -> Dict[str, Any]:
        """Fetch a profile by phone number or create it if not found."""
        phone = phone.strip()
        if self.use_supabase:
            url = f"{self.supabase_url}/rest/v1/profiles?phone=eq.{phone}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    profiles = resp.json()
                    if profiles:
                        return profiles[0]
                
                # Create profile since it doesn't exist
                new_id = str(uuid.uuid4())
                payload = {
                    "id": new_id,
                    "phone": phone,
                    "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    "updated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                }
                headers_prefer = {**self.headers, "Prefer": "return=representation"}
                resp_create = await client.post(
                    f"{self.supabase_url}/rest/v1/profiles",
                    headers=headers_prefer,
                    json=payload
                )
                if resp_create.status_code == 201:
                    created_list = resp_create.json()
                    if created_list:
                        return created_list[0]
                
                # Fallback return payload if representation fail
                return payload
        else:
            return await asyncio.to_thread(self._get_or_create_profile_sqlite, phone)

    def _get_or_create_profile_sqlite(self, phone: str) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM profiles WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            
            new_id = str(uuid.uuid4())
            now = time.time()
            cursor.execute("""
                INSERT INTO profiles (id, phone, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (new_id, phone, now, now))
            conn.commit()
            
            cursor.execute("SELECT * FROM profiles WHERE id = ?", (new_id,))
            return dict(cursor.fetchone())

    async def update_profile(self, phone: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update fields in a profile."""
        phone = phone.strip()
        if not updates:
            return await self.get_or_create_profile(phone)
            
        if self.use_supabase:
            url = f"{self.supabase_url}/rest/v1/profiles?phone=eq.{phone}"
            updates["updated_at"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            headers_prefer = {**self.headers, "Prefer": "return=representation"}
            async with httpx.AsyncClient() as client:
                resp = await client.patch(url, headers=headers_prefer, json=updates)
                if resp.status_code == 200:
                    res = resp.json()
                    if res:
                        return res[0]
            return None
        else:
            return await asyncio.to_thread(self._update_profile_sqlite, phone, updates)

    def _update_profile_sqlite(self, phone: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            fields = []
            values = []
            for k, v in updates.items():
                fields.append(f"{k} = ?")
                values.append(v)
            
            values.append(time.time())
            values.append(phone)
            
            cursor.execute(f"""
                UPDATE profiles 
                SET {", ".join(fields)}, updated_at = ?
                WHERE phone = ?
            """, values)
            conn.commit()
            
            cursor.execute("SELECT * FROM profiles WHERE phone = ?", (phone,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Calls API
    # ------------------------------------------------------------------

    async def create_call(self, call_sid: str, stream_sid: str, caller_number: str) -> Dict[str, Any]:
        """Create a new call entry linked to the caller's profile."""
        profile = await self.get_or_create_profile(caller_number)
        profile_id = profile["id"]
        
        if self.use_supabase:
            new_id = str(uuid.uuid4())
            payload = {
                "id": new_id,
                "call_sid": call_sid,
                "stream_sid": stream_sid,
                "caller_number": caller_number,
                "status": "initiated",
                "profile_id": profile_id,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                "updated_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            headers_prefer = {**self.headers, "Prefer": "return=representation"}
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self.supabase_url}/rest/v1/calls",
                    headers=headers_prefer,
                    json=payload
                )
                if resp.status_code == 201:
                    created = resp.json()
                    if created:
                        return created[0]
            return payload
        else:
            return await asyncio.to_thread(self._create_call_sqlite, call_sid, stream_sid, caller_number, profile_id)

    def _create_call_sqlite(self, call_sid: str, stream_sid: str, caller_number: str, profile_id: str) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            new_id = str(uuid.uuid4())
            now = time.time()
            cursor.execute("""
                INSERT INTO calls (id, call_sid, stream_sid, caller_number, status, profile_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (new_id, call_sid, stream_sid, caller_number, "initiated", profile_id, now, now))
            conn.commit()
            
            cursor.execute("SELECT * FROM calls WHERE id = ?", (new_id,))
            return dict(cursor.fetchone())

    async def update_call(self, call_sid: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update call properties."""
        if self.use_supabase:
            url = f"{self.supabase_url}/rest/v1/calls?call_sid=eq.{call_sid}"
            updates["updated_at"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            headers_prefer = {**self.headers, "Prefer": "return=representation"}
            async with httpx.AsyncClient() as client:
                resp = await client.patch(url, headers=headers_prefer, json=updates)
                if resp.status_code == 200:
                    res = resp.json()
                    if res:
                        return res[0]
            return None
        else:
            return await asyncio.to_thread(self._update_call_sqlite, call_sid, updates)

    def _update_call_sqlite(self, call_sid: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            fields = []
            values = []
            for k, v in updates.items():
                fields.append(f"{k} = ?")
                values.append(v)
            
            values.append(time.time())
            values.append(call_sid)
            
            cursor.execute(f"""
                UPDATE calls 
                SET {", ".join(fields)}, updated_at = ?
                WHERE call_sid = ?
            """, values)
            conn.commit()
            
            cursor.execute("SELECT * FROM calls WHERE call_sid = ?", (call_sid,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Transcript Turns API
    # ------------------------------------------------------------------

    async def insert_transcript_turn(self, call_sid: str, speaker: str, text: str, latency_ms: Optional[int] = None) -> Dict[str, Any]:
        """Insert a speaker-labeled turn linked to the call session."""
        # Find internal call_id
        call_id = None
        if self.use_supabase:
            url = f"{self.supabase_url}/rest/v1/calls?call_sid=eq.{call_sid}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    calls = resp.json()
                    if calls:
                        call_id = calls[0]["id"]
            
            if not call_id:
                logger.error("Call ID not found for call_sid=%s when inserting turn", call_sid)
                return {}
                
            # Count existing turns to determine sequence number
            seq_number = 1
            url_turns = f"{self.supabase_url}/rest/v1/transcript_turns?call_id=eq.{call_id}&select=count"
            resp_turns = await client.get(url_turns, headers={**self.headers, "Prefer": "count=exact"})
            if resp_turns.status_code == 200 or resp_turns.status_code == 206:
                content_range = resp_turns.headers.get("Content-Range", "")
                if "/" in content_range:
                    try:
                        seq_number = int(content_range.split("/")[-1]) + 1
                    except ValueError:
                        pass
            
            new_id = str(uuid.uuid4())
            payload = {
                "id": new_id,
                "call_id": call_id,
                "seq_number": seq_number,
                "speaker": speaker,
                "text": text,
                "latency_ms": latency_ms,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            headers_prefer = {**self.headers, "Prefer": "return=representation"}
            resp_insert = await client.post(
                f"{self.supabase_url}/rest/v1/transcript_turns",
                headers=headers_prefer,
                json=payload
            )
            if resp_insert.status_code == 201:
                created = resp_insert.json()
                if created:
                    return created[0]
            return payload
        else:
            return await asyncio.to_thread(self._insert_transcript_turn_sqlite, call_sid, speaker, text, latency_ms)

    def _insert_transcript_turn_sqlite(self, call_sid: str, speaker: str, text: str, latency_ms: Optional[int] = None) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM calls WHERE call_sid = ?", (call_sid,))
            row = cursor.fetchone()
            if not row:
                logger.error("Call ID not found for call_sid=%s when inserting turn in SQLite", call_sid)
                return {}
            call_id = row[0]
            
            cursor.execute("SELECT COUNT(*) FROM transcript_turns WHERE call_id = ?", (call_id,))
            cnt = cursor.fetchone()[0]
            seq_number = cnt + 1
            
            new_id = str(uuid.uuid4())
            now = time.time()
            cursor.execute("""
                INSERT INTO transcript_turns (id, call_id, seq_number, speaker, text, latency_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (new_id, call_id, seq_number, speaker, text, latency_ms, now))
            conn.commit()
            
            cursor.execute("SELECT * FROM transcript_turns WHERE id = ?", (new_id,))
            return dict(cursor.fetchone())

    # ------------------------------------------------------------------
    # Summaries API
    # ------------------------------------------------------------------

    async def save_summary(self, call_sid: str, summary_text: str, delivery_status: str = "none", destination: Optional[str] = None) -> Dict[str, Any]:
        """Save a call summary record."""
        call_id = None
        if self.use_supabase:
            url = f"{self.supabase_url}/rest/v1/calls?call_sid=eq.{call_sid}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self.headers)
                if resp.status_code == 200:
                    calls = resp.json()
                    if calls:
                        call_id = calls[0]["id"]
            
            if not call_id:
                logger.error("Call ID not found for call_sid=%s when saving summary", call_sid)
                return {}
                
            new_id = str(uuid.uuid4())
            payload = {
                "id": new_id,
                "call_id": call_id,
                "summary_text": summary_text,
                "delivery_status": delivery_status,
                "destination": destination,
                "created_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            headers_prefer = {**self.headers, "Prefer": "return=representation"}
            resp_insert = await client.post(
                f"{self.supabase_url}/rest/v1/summaries",
                headers=headers_prefer,
                json=payload
            )
            if resp_insert.status_code == 201:
                created = resp_insert.json()
                if created:
                    return created[0]
            return payload
        else:
            return await asyncio.to_thread(self._save_summary_sqlite, call_sid, summary_text, delivery_status, destination)

    def _save_summary_sqlite(self, call_sid: str, summary_text: str, delivery_status: str, destination: Optional[str]) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT id FROM calls WHERE call_sid = ?", (call_sid,))
            row = cursor.fetchone()
            if not row:
                logger.error("Call ID not found for call_sid=%s when saving summary in SQLite", call_sid)
                return {}
            call_id = row[0]
            
            new_id = str(uuid.uuid4())
            now = time.time()
            cursor.execute("""
                INSERT INTO summaries (id, call_id, summary_text, delivery_status, destination, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (new_id, call_id, summary_text, delivery_status, destination, now))
            conn.commit()
            
            cursor.execute("SELECT * FROM summaries WHERE id = ?", (new_id,))
            return dict(cursor.fetchone())
