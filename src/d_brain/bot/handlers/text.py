"""Text message handler."""

import asyncio
import logging
from datetime import date, datetime

from aiogram import Router
from aiogram.types import Message

from d_brain.bot.formatters import format_process_report, split_html_report
from d_brain.config import get_settings
from d_brain.services.git import VaultGit
from d_brain.services.processor import ClaudeProcessor
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


def _is_reply_to_plan(message: Message) -> bool:
    """Check if user is replying to a plan message from the bot."""
    if not _is_reply_to_bot(message):
        return False
    original = message.reply_to_message.text or ""
    plan_markers = [
        "контент-план", "Контент-план", "Content Plan",
        "Якорный пост", "якорный пост",
        "TELEGRAM:", "LINKEDIN:",
        "Пн:", "Вт:", "Ср:", "Чт:", "Пт:",
    ]
    return any(marker in original for marker in plan_markers)


async def _handle_plan_edit(message: Message) -> None:
    """Handle reply to a plan message - edit the plan via Claude."""
    status_msg = await message.answer("⏳ Редактирую план...")

    settings = get_settings()
    processor = ClaudeProcessor(
        settings.vault_path,
        settings.ticktick_client_id,
        settings.ticktick_client_secret,
        settings.ticktick_access_token,
        settings.planfix_account,
        settings.planfix_token,
    )
    git = VaultGit(settings.vault_path)

    async def run_with_progress() -> dict:
        task = asyncio.create_task(
            asyncio.to_thread(processor.edit_plan, message.text),
        )

        elapsed = 0
        while not task.done():
            await asyncio.sleep(30)
            elapsed += 30
            if not task.done():
                try:
                    await status_msg.edit_text(
                        f"⏳ Редактирую план... ({elapsed // 60}m {elapsed % 60}s)",
                    )
                except Exception:
                    pass

        return await task

    report = await run_with_progress()

    if "error" not in report:
        await asyncio.to_thread(
            git.commit_and_push,
            f"chore: edit plan {date.today().isoformat()}",
        )

    formatted = format_process_report(report)
    parts = split_html_report(formatted)

    try:
        await status_msg.edit_text(parts[0])
    except Exception:
        await status_msg.edit_text(parts[0], parse_mode=None)

    for part in parts[1:]:
        try:
            await message.answer(part)
        except Exception:
            await message.answer(part, parse_mode=None)


@router.message(lambda m: m.text is not None and not m.text.startswith("/"))
async def handle_text(message: Message) -> None:
    """Handle text messages (excluding commands).

    - Reply to plan message → edit plan via Claude
    - Reply to bot message → dialogue with Claude (with context of original message)
    - Plain text → save as thought to daily file
    """
    if not message.text or not message.from_user:
        return

    # If replying to a plan message — edit the plan
    if _is_reply_to_plan(message):
        logger.info("Reply to plan from user %s, editing plan", message.from_user.id)
        await _handle_plan_edit(message)
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
