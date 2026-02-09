"""Telegram channel reader service using Telethon."""

import logging
from datetime import date, timedelta
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)


class ChannelReader:
    """Reads posts from a Telegram channel via Telethon bot API."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        bot_token: str,
        channel: str,
        vault_path: Path,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.channel = channel
        self.vault_path = Path(vault_path)
        self._archive_dir = self.vault_path / "content" / "channel-archive"

    async def _create_client(self) -> TelegramClient:
        """Create and authenticate a Telethon client with bot token."""
        client = TelegramClient(StringSession(), self.api_id, self.api_hash)
        await client.start(bot_token=self.bot_token)
        return client

    async def get_recent_posts(self, limit: int = 50) -> list[dict]:
        """Fetch recent posts from the channel.

        Args:
            limit: Maximum number of posts to fetch.

        Returns:
            List of post dicts with keys: id, date, text, views, forwards.
        """
        posts: list[dict] = []
        client = await self._create_client()

        try:
            entity = await client.get_entity(self.channel)

            async for message in client.iter_messages(entity, limit=limit):
                if not message.text:
                    continue

                posts.append({
                    "id": message.id,
                    "date": message.date.strftime("%Y-%m-%d %H:%M"),
                    "text": message.text,
                    "views": message.views or 0,
                    "forwards": message.forwards or 0,
                })
        finally:
            await client.disconnect()

        logger.info("Fetched %d posts from @%s", len(posts), self.channel)
        return posts

    async def get_posts_since(self, days: int = 30) -> list[dict]:
        """Fetch posts from the last N days.

        Args:
            days: Number of days to look back.

        Returns:
            List of post dicts.
        """
        from datetime import datetime, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        posts: list[dict] = []
        client = await self._create_client()

        try:
            entity = await client.get_entity(self.channel)

            async for message in client.iter_messages(
                entity, offset_date=cutoff, reverse=True
            ):
                if not message.text:
                    continue

                posts.append({
                    "id": message.id,
                    "date": message.date.strftime("%Y-%m-%d %H:%M"),
                    "text": message.text,
                    "views": message.views or 0,
                    "forwards": message.forwards or 0,
                })
        finally:
            await client.disconnect()

        logger.info(
            "Fetched %d posts from @%s (last %d days)",
            len(posts), self.channel, days,
        )
        return posts

    async def save_to_vault(self, posts: list[dict]) -> Path:
        """Save posts to vault/content/channel-archive/ as markdown.

        Args:
            posts: List of post dicts from get_recent_posts().

        Returns:
            Path to the saved archive file.
        """
        self._archive_dir.mkdir(parents=True, exist_ok=True)

        today = date.today().isoformat()
        archive_path = self._archive_dir / f"{today}-archive.md"

        lines = [
            "---",
            f"date: {today}",
            "type: channel-archive",
            f"channel: {self.channel}",
            f"posts_count: {len(posts)}",
            "---",
            "",
            f"# Channel Archive @{self.channel} - {today}",
            "",
        ]

        for post in posts:
            lines.extend([
                f"## [{post['date']}] (views: {post['views']})",
                "",
                post["text"],
                "",
                "---",
                "",
            ])

        archive_path.write_text("\n".join(lines))
        logger.info("Channel archive saved to %s", archive_path)
        return archive_path

    def format_for_prompt(self, posts: list[dict], limit: int = 20) -> str:
        """Format posts for inclusion in Claude prompt.

        Args:
            posts: List of post dicts.
            limit: Max posts to include.

        Returns:
            Formatted string for prompt injection.
        """
        if not posts:
            return ""

        lines = []
        for post in posts[:limit]:
            lines.extend([
                f"--- POST [{post['date']}] (views: {post['views']}) ---",
                post["text"],
                "",
            ])

        return "\n".join(lines)

    async def generate_tone_examples(self, limit: int = 50) -> Path:
        """Fetch posts and save best ones as tone-of-voice examples.

        Selects posts with the most views (engagement = good writing)
        and saves them to the content-seeds references.

        Args:
            limit: Number of posts to fetch for selection.

        Returns:
            Path to the generated tone-examples.md file.
        """
        posts = await self.get_recent_posts(limit=limit)
        if not posts:
            raise ValueError(f"No posts found in @{self.channel}")

        # Sort by views (descending) — most engaging = best tone examples
        sorted_posts = sorted(posts, key=lambda p: p["views"], reverse=True)
        top_posts = sorted_posts[:15]
        # Re-sort by date for readability
        top_posts.sort(key=lambda p: p["date"])

        today = date.today().isoformat()
        lines = [
            "# Tone of Voice - примеры постов Марины",
            "",
            f"Автоматически собрано {today} из @{self.channel}.",
            "Claude должен изучить тон, ритм, структуру и писать seeds в этом стиле.",
            "",
            "## Как использовать",
            "- Изучи каждый пример: длину предложений, переходы, обращение к читателю",
            "- Обрати внимание на баланс личного и профессионального",
            "- Запомни характерные приёмы: самоирония, вопросы себе, незавершённые мысли",
            "- Пиши hooks и seeds так, будто это написала Марина",
            "",
            "---",
            "",
        ]

        for i, post in enumerate(top_posts, 1):
            lines.extend([
                f"### Пример {i}",
                f"**Дата:** {post['date']} | **Views:** {post['views']}",
                "",
                post["text"],
                "",
                "---",
                "",
            ])

        ref_path = (
            self.vault_path
            / ".claude/skills/content-seeds/references/tone-examples.md"
        )
        ref_path.write_text("\n".join(lines))
        logger.info("Tone examples saved to %s (%d posts)", ref_path, len(top_posts))
        return ref_path
