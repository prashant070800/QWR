import os
import time
import uuid
import json
import asyncio
import logging
from typing import Optional, Any, Dict, List
import httpx
from asgiref.sync import sync_to_async
from django.db import models

from ai_agent.config import settings

logger = logging.getLogger(__name__)

class CallStorage:
    """Storage adapter to persist profiles, calls, turns, and summaries.
    
    Supports Django models for local fallback or Supabase REST backend depending on environment config.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
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
            logger.info("CallStorage initialized with LOCAL DJANGO MODELS fallback backend")

    def _model_to_dict(self, instance) -> Dict[str, Any]:
        """Convert a Django model instance to a JSON-serializable dictionary."""
        if not instance:
            return {}
        data = {}
        for field in instance._meta.fields:
            key_name = field.name
            val = getattr(instance, field.name)
            if isinstance(field, models.ForeignKey):
                key_name = f"{field.name}_id"
                val = getattr(instance, f"{field.name}_id")
            
            if isinstance(val, uuid.UUID):
                data[key_name] = str(val)
            elif hasattr(val, 'isoformat'): # DateTimeField
                data[key_name] = val.isoformat()
            else:
                data[key_name] = val
        return data

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
                
                return payload
        else:
            from telephony.models import Profile
            def _db_op():
                profile, created = Profile.objects.get_or_create(phone=phone)
                return self._model_to_dict(profile)
            return await sync_to_async(_db_op)()

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
            from telephony.models import Profile
            def _db_op():
                Profile.objects.filter(phone=phone).update(**updates)
                profile = Profile.objects.filter(phone=phone).first()
                return self._model_to_dict(profile) if profile else None
            return await sync_to_async(_db_op)()

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
            from telephony.models import Profile, Call
            def _db_op():
                prof = Profile.objects.get(id=profile_id)
                call = Call.objects.create(
                    call_sid=call_sid,
                    stream_sid=stream_sid,
                    caller_number=caller_number,
                    status="initiated",
                    profile=prof
                )
                return self._model_to_dict(call)
            return await sync_to_async(_db_op)()

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
            from telephony.models import Call
            def _db_op():
                Call.objects.filter(call_sid=call_sid).update(**updates)
                call = Call.objects.filter(call_sid=call_sid).first()
                return self._model_to_dict(call) if call else None
            return await sync_to_async(_db_op)()

    # ------------------------------------------------------------------
    # Transcript Turns API
    # ------------------------------------------------------------------

    async def insert_transcript_turn(self, call_sid: str, speaker: str, text: str, latency_ms: Optional[int] = None) -> Dict[str, Any]:
        """Insert a speaker-labeled turn linked to the call session."""
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
            from telephony.models import Call, TranscriptTurn
            def _db_op():
                call = Call.objects.filter(call_sid=call_sid).first()
                if not call:
                    logger.error("Call ID not found for call_sid=%s when inserting turn in Django", call_sid)
                    return {}
                seq_number = call.turns.count() + 1
                turn = TranscriptTurn.objects.create(
                    call=call,
                    seq_number=seq_number,
                    speaker=speaker,
                    text=text,
                    latency_ms=latency_ms
                )
                return self._model_to_dict(turn)
            return await sync_to_async(_db_op)()

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
            from telephony.models import Call, Summary
            def _db_op():
                call = Call.objects.filter(call_sid=call_sid).first()
                if not call:
                    logger.error("Call ID not found for call_sid=%s when saving summary in Django", call_sid)
                    return {}
                summary = Summary.objects.create(
                    call=call,
                    summary_text=summary_text,
                    delivery_status=delivery_status,
                    destination=destination
                )
                return self._model_to_dict(summary)
            return await sync_to_async(_db_op)()
