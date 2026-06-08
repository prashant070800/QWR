import logging
import threading
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from telephony.models import Call
from telephony.notifications import dispatch_summary_notification

logger = logging.getLogger(__name__)

def run_in_background(target, *args, **kwargs):
    thread = threading.Thread(target=target, args=args, kwargs=kwargs)
    thread.daemon = True
    thread.start()

@receiver(post_save, sender=Call)
def handle_call_completed_signal(sender, instance, **kwargs):
    if instance.status == "completed":
        # Check if summary already exists before launching thread to avoid unnecessary threads
        from telephony.models import Summary
        if Summary.objects.filter(call=instance).exists():
            return

        # Ensure we only run after the database transaction has successfully committed
        transaction.on_commit(lambda: run_in_background(_generate_and_send_summary_sync, instance.id))

def _generate_and_send_summary_sync(call_id):
    from asgiref.sync import async_to_sync
    
    # Run the async summary generator synchronously inside the background thread
    try:
        async_to_sync(_generate_and_send_summary_async)(call_id)
    except Exception as exc:
        logger.exception("Error in background summary generation for call_id=%s: %s", call_id, exc)

async def _generate_and_send_summary_async(call_id):
    from telephony.models import Call, Summary, TranscriptTurn
    
    # 1. Fetch Call using call_id (PK)
    call = await Call.objects.filter(id=call_id).afirst()
    if not call:
        logger.error("[SIGNAL] Call PK %s not found", call_id)
        return
        
    # Double check unique DB constraint check
    exists = await Summary.objects.filter(call_id=call_id).aexists()
    if exists:
        logger.info("[SIGNAL] Summary already exists for call_id=%s, skipping", call_id)
        return

    # 2. Get transcript turns from DB
    turns = []
    async for turn in TranscriptTurn.objects.filter(call=call).order_by('seq_number'):
        turns.append({
            "speaker": turn.speaker,
            "text": turn.text,
            "seq_number": turn.seq_number
        })

    if not turns:
        logger.info("[SIGNAL] No transcript turns found for call_id=%s, skipping summary", call_id)
        return

    logger.info("[SIGNAL] Generating summary for call_id=%s with %d turns", call_id, len(turns))

    # 3. Instantiate QWRAgent and generate summary
    from ai_agent.agent import QWRAgent
    agent = QWRAgent(
        call_sid=call.call_sid,
        stream_sid=call.stream_sid,
        call_id=str(call.id),
    )
    summary_text, token_usage = await agent.generate_summary(turns)

    # 4. Save to DB under Unique constraint
    try:
        summary = await Summary.objects.acreate(
            call=call,
            summary_text=summary_text,
            delivery_status="pending",
            destination=call.from_number,
            token_usage=token_usage,
        )
    except Exception as exc:
        logger.warning("[SIGNAL] Unique constraint triggered or write failed for call_id=%s: %s", call_id, exc)
        return

    # 5. Trigger notification delivery
    await _send_notification_async(summary.id)

async def _send_notification_async(summary_id):
    from telephony.models import Summary

    summary = await Summary.objects.select_related('call').filter(id=summary_id).afirst()
    if not summary:
        return

    logger.info("[SIGNAL] Triggering delivery for summary_id=%s destination=%s", summary_id, summary.destination)

    try:
        success = await dispatch_summary_notification(
            summary_text=summary.summary_text,
            phone=summary.call.from_number,
            email=None,
            call_id=summary.call.id,
        )
        if success:
            summary.delivery_status = "sent"
        else:
            summary.delivery_status = "failed"
    except Exception as exc:
        logger.error("[SIGNAL] Failed to deliver notification for summary %s: %s", summary_id, exc)
        summary.delivery_status = "failed"

    await summary.asave(update_fields=["delivery_status"])
