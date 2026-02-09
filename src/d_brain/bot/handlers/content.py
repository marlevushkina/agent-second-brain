"""Content seeds command handler."""

import asyncio
import logging
from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.formatters import format_process_report, split_html_report
from d_brain.config import get_settings
from d_brain.services.gdocs import GoogleDocsSync
from d_brain.services.git import VaultGit
from d_brain.services.processor import ClaudeProcessor

router = Router(name="content")
logger = logging.getLogger(__name__)


@router.message(Command("content"))
async def cmd_content(message: Message) -> None:
    """Handle /content command - generate content seeds from weekly material."""
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("Content seeds triggered by user %s", user_id)

    status_msg = await message.answer("⏳ Генерирую content seeds...")

    settings = get_settings()

    # Step 1: Sync Google Docs (if configured)
    sync_info = ""
    if settings.google_docs_folder_id:
        try:
            await status_msg.edit_text("⏳ Синхронизирую транскрипты встреч...")
            gdocs = GoogleDocsSync(
                settings.vault_path,
                settings.google_docs_folder_id,
                settings.google_credentials_path,
            )
            sync_result = await asyncio.to_thread(gdocs.sync)
            synced = sync_result.get("synced", 0)
            if synced > 0:
                sync_info = f"\n📥 Синхронизировано встреч: {synced}"
            logger.info("Google Docs sync result: %s", sync_result)
        except Exception as e:
            logger.warning("Google Docs sync failed: %s", e)
            sync_info = "\n⚠️ Синхронизация Google Docs не удалась"

    # Step 2: Generate content seeds
    try:
        await status_msg.edit_text("⏳ Генерирую content seeds... (может занять до 5 мин)")
    except Exception:
        pass

    processor = ClaudeProcessor(settings.vault_path, settings.todoist_api_key)
    git = VaultGit(settings.vault_path)

    async def run_with_progress() -> dict:
        task = asyncio.create_task(
            asyncio.to_thread(processor.generate_content_seeds)
        )

        elapsed = 0
        while not task.done():
            await asyncio.sleep(30)
            elapsed += 30
            if not task.done():
                try:
                    await status_msg.edit_text(
                        f"⏳ Генерирую seeds... ({elapsed // 60}m {elapsed % 60}s)"
                    )
                except Exception:
                    pass

        return await task

    report = await run_with_progress()

    # Step 3: Commit changes
    if "error" not in report:
        today = date.today().isoformat()
        await asyncio.to_thread(
            git.commit_and_push, f"chore: content seeds {today}"
        )

    # Step 4: Send report (handle long messages)
    formatted = format_process_report(report)

    if sync_info and "error" not in report:
        formatted = sync_info + "\n\n" + formatted

    parts = split_html_report(formatted)

    try:
        await status_msg.edit_text(parts[0])
    except Exception:
        await status_msg.edit_text(parts[0], parse_mode=None)

    # Send remaining parts as new messages
    for part in parts[1:]:
        try:
            await message.answer(part)
        except Exception:
            await message.answer(part, parse_mode=None)
