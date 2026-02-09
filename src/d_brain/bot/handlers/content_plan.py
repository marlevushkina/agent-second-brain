"""Content plan command handler."""

import asyncio
import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.formatters import format_process_report, split_html_report
from d_brain.config import get_settings
from d_brain.services.git import VaultGit
from d_brain.services.processor import ClaudeProcessor

router = Router(name="content_plan")
logger = logging.getLogger(__name__)


@router.message(Command("plan"))
async def cmd_plan(message: Message) -> None:
    """Handle /plan command - generate weekly content plan from seeds."""
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("Content plan triggered by user %s", user_id)

    status_msg = await message.answer("⏳ Генерирую контент-план на неделю...")

    settings = get_settings()

    # Step 1: Read channel posts (if configured)
    channel_posts_text = ""
    if settings.telegram_api_id and settings.telegram_api_hash and settings.telegram_channel:
        try:
            await status_msg.edit_text("⏳ Читаю последние посты из канала...")
            from d_brain.services.channel_reader import ChannelReader

            reader = ChannelReader(
                api_id=settings.telegram_api_id,
                api_hash=settings.telegram_api_hash,
                bot_token=settings.telegram_bot_token,
                channel=settings.telegram_channel,
                vault_path=settings.vault_path,
            )
            posts = await reader.get_recent_posts(limit=20)
            channel_posts_text = reader.format_for_prompt(posts, limit=15)
            logger.info("Loaded %d channel posts for context", len(posts))
        except Exception as e:
            logger.warning("Failed to read channel: %s", e)
            channel_posts_text = ""

    # Step 2: Generate content plan
    try:
        await status_msg.edit_text("⏳ Составляю контент-план... (может занять до 5 мин)")
    except Exception:
        pass

    processor = ClaudeProcessor(
        settings.vault_path,
        settings.ticktick_client_id,
        settings.ticktick_client_secret,
        settings.ticktick_access_token,
    )
    git = VaultGit(settings.vault_path)

    async def run_with_progress() -> dict:
        task = asyncio.create_task(
            asyncio.to_thread(
                processor.generate_content_plan,
                channel_posts=channel_posts_text,
            )
        )

        elapsed = 0
        while not task.done():
            await asyncio.sleep(30)
            elapsed += 30
            if not task.done():
                try:
                    await status_msg.edit_text(
                        f"⏳ Составляю план... ({elapsed // 60}m {elapsed % 60}s)"
                    )
                except Exception:
                    pass

        return await task

    report = await run_with_progress()

    # Step 3: Commit
    if "error" not in report:
        today = date.today().isoformat()
        await asyncio.to_thread(
            git.commit_and_push, f"chore: content plan {today}"
        )

    # Step 4: Send report
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
