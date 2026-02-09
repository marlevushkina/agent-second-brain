"""Text message handler."""

import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import Message

from d_brain.config import get_settings
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage

router = Router(name="text")
logger = logging.getLogger(__name__)


def _is_reply_to_bot(message: Message) -> bool:
    """Check if user is replying to a bot message."""
    if not message.reply_to_message:
        return False
    reply = message.reply_to_message
    return reply.from_user is not None and reply.from_user.is_bot


@router.message(lambda m: m.text is not None and not m.text.startswith("/"))
async def handle_text(message: Message) -> None:
    """Handle text messages (excluding commands).

    - Reply to bot message → dialogue with Claude (with context of original message)
    - Plain text → save as thought to daily file
    """
    if not message.text or not message.from_user:
        return

    # If replying to a bot message — treat as dialogue with context
    if _is_reply_to_bot(message):
        from d_brain.bot.handlers.do import process_request

        user_id = message.from_user.id

        # Build prompt with context of the original bot message
        original_text = message.reply_to_message.text or ""
        # Trim long messages to avoid prompt bloat
        if len(original_text) > 2000:
            original_text = original_text[:2000] + "...(обрезано)"

        prompt = (
            f"Пользователь отвечает на предыдущее сообщение бота.\n\n"
            f"=== ПРЕДЫДУЩЕЕ СООБЩЕНИЕ БОТА ===\n{original_text}\n"
            f"=== КОНЕЦ ===\n\n"
            f"Ответ пользователя: {message.text}"
        )

        logger.info("Reply to bot from user %s, processing as dialogue", user_id)
        await process_request(message, prompt, user_id)
        return

    # Otherwise — save as thought
    settings = get_settings()
    storage = VaultStorage(settings.vault_path)

    timestamp = datetime.fromtimestamp(message.date.timestamp())
    storage.append_to_daily(message.text, timestamp, "[text]")

    # Log to session
    session = SessionStore(settings.vault_path)
    session.append(
        message.from_user.id,
        "text",
        text=message.text,
        msg_id=message.message_id,
    )

    await message.answer("✓ Сохранено")
    logger.info("Text message saved: %d chars", len(message.text))
