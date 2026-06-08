import logging
import httpx
from ai_agent.config import settings

logger = logging.getLogger(__name__)


async def send_telegram_notification(text: str) -> bool:
    """Send summary message via Telegram Bot API."""
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        logger.warning("[NOTIFICATION][TELEGRAM] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                logger.info("[NOTIFICATION][TELEGRAM] Message sent successfully!")
                return True
            else:
                logger.error("[NOTIFICATION][TELEGRAM] Failed to send message. status=%d body=%s", resp.status_code, resp.text)
                return False
    except Exception as exc:
        logger.error("[NOTIFICATION][TELEGRAM] Exception sending telegram message: %s", exc)
        return False


async def mock_deliver_notification(summary_text: str, phone: str | None = None, email: str | None = None) -> bool:
    """Mock notification delivery function. Logs the delivery details."""
    logger.info(
        "📞 [MOCK NOTIFICATION] Deliver summary: %r | Phone: %s | Email: %s",
        summary_text,
        phone,
        email,
    )
    return True


async def dispatch_summary_notification(summary_text: str, phone: str | None = None, email: str | None = None, call_id: int | None = None) -> bool:
    """
    Dispatch call summary notification.
    Tries Telegram first, and falls back to mock email/SMS delivery if Telegram is not configured or fails.
    """
    # 1. Prepare message formatting
    import html
    import re
    
    # Escape HTML first to prevent injection
    escaped_summary = html.escape(summary_text)
    
    # Convert markdown bold to HTML bold
    escaped_summary = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', escaped_summary)
    
    # Convert markdown bullets to unicode bullets
    escaped_summary = re.sub(r'^\*\s+', '• ', escaped_summary, flags=re.MULTILINE)
    escaped_summary = re.sub(r'^\-\s+', '• ', escaped_summary, flags=re.MULTILINE)

    # Use localhost if QWR_WEBSITE_URL is the default questionwhatsreal.com
    dashboard_link = f"{settings.qwr_website_url.rstrip('/')}/dashboard/call/{call_id}/" if call_id and settings.qwr_website_url else ""
    link_html = f"\n\n🔗 <a href='{dashboard_link}'>View Full Call Detail & Transcript</a>" if dashboard_link else ""

    formatted_msg = (
        f"<b>QWR Call Summary</b>\n"
        f"<b>From:</b> {phone or 'Unknown'}\n\n"
        f"{escaped_summary}{link_html}"
    )

    # 2. Try Telegram first
    if settings.telegram_bot_token and settings.telegram_chat_id:
        logger.info("[NOTIFICATION] Dispatcher: Attempting Telegram delivery...")
        success = await send_telegram_notification(formatted_msg)
        if success:
            return True
        logger.warning("[NOTIFICATION] Dispatcher: Telegram delivery failed, falling back...")

    # 3. Fallback to mock delivery (or email/SMS in the future)
    logger.info("[NOTIFICATION] Dispatcher: Falling back to Email/SMS delivery...")
    return await mock_deliver_notification(summary_text, phone, email)
