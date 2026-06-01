import os
import asyncio
import unittest
import sqlite3
from ai_agent.storage import CallStorage

TEST_DB_PATH = "test_voicebot_temp.sqlite3"

class StorageTests(unittest.TestCase):
    def setUp(self):
        # Always start with a clean test database
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
        self.storage = CallStorage(db_path=TEST_DB_PATH)

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except OSError:
                pass

    def test_profile_creation_and_update(self):
        async def run_test():
            phone = "+919876543210"
            # 1. Get or create
            profile = await self.storage.get_or_create_profile(phone)
            self.assertEqual(profile["phone"], phone)
            self.assertIsNotNone(profile["id"])

            # 2. Get existing
            profile_again = await self.storage.get_or_create_profile(phone)
            self.assertEqual(profile["id"], profile_again["id"])

            # 3. Update profile
            updated = await self.storage.update_profile(phone, {
                "name": "Prashant Kumar",
                "company": "QWR",
                "role": "Lead Engineer"
            })
            self.assertIsNotNone(updated)
            self.assertEqual(updated["name"], "Prashant Kumar")
            self.assertEqual(updated["company"], "QWR")
            self.assertEqual(updated["role"], "Lead Engineer")

        asyncio.run(run_test())

    def test_call_lifecycle_and_turns(self):
        async def run_test():
            call_sid = "test-call-12345"
            stream_sid = "test-stream-12345"
            phone = "+919999999999"

            # 1. Create call
            call = await self.storage.create_call(call_sid, stream_sid, phone)
            self.assertEqual(call["call_sid"], call_sid)
            self.assertEqual(call["status"], "initiated")
            self.assertIsNotNone(call["profile_id"])

            # 2. Insert transcript turns
            turn1 = await self.storage.insert_transcript_turn(call_sid, "user", "Hello there!")
            self.assertEqual(turn1["seq_number"], 1)
            self.assertEqual(turn1["speaker"], "user")
            self.assertEqual(turn1["text"], "Hello there!")

            turn2 = await self.storage.insert_transcript_turn(call_sid, "assistant", "Hi, how can I help you today?", latency_ms=150)
            self.assertEqual(turn2["seq_number"], 2)
            self.assertEqual(turn2["speaker"], "assistant")
            self.assertEqual(turn2["latency_ms"], 150)

            # 3. Update call status
            updated_call = await self.storage.update_call(call_sid, {
                "status": "completed",
                "duration": 45
            })
            self.assertEqual(updated_call["status"], "completed")
            self.assertEqual(updated_call["duration"], 45)

            # 4. Save call summary
            summary = await self.storage.save_summary(call_sid, "The user checked in and said Hello.", "sent", "email@example.com")
            self.assertEqual(summary["summary_text"], "The user checked in and said Hello.")
            self.assertEqual(summary["delivery_status"], "sent")
            self.assertEqual(summary["destination"], "email@example.com")

        asyncio.run(run_test())
