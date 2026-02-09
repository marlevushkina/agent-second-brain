"""Telegram channel reader service via public web page."""

import logging
import re
from datetime import date
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

TG_CHANNEL_URL = "https://t.me/s/{channel}"


class ChannelReader:
    """Reads posts from a public Telegram channel via t.me/s/ web page."""

    def __init__(self, channel: str, vault_path: Path) -> None:
        self.channel = channel
        self.vault_path = Path(vault_path)
        self._archive_dir = self.vault_path / "content" / "channel-archive"

    async def get_recent_posts(self, limit: int = 50) -> list[dict]:
        """Fetch recent posts from the channel web page.

        Args:
            limit: Maximum number of posts to return.

        Returns:
            List of post dicts with keys: id, date, text, views.
        """
        url = TG_CHANNEL_URL.format(channel=self.channel)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        html = resp.text
        return self._parse_posts(html, limit)

    def _parse_posts(self, html: str, limit: int) -> list[dict]:
        """Parse posts from Telegram channel web page HTML."""
        # Extract post IDs
        post_ids = re.findall(
            rf'data-post="{re.escape(self.channel)}/(\d+)"', html
        )

        # Extract texts (HTML content inside message_text divs)
        raw_texts = re.findall(
            r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )

        # Extract views
        raw_views = re.findall(
            r'class="tgme_widget_message_views">([^<]+)<', html
        )

        # Extract dates
        raw_dates = re.findall(r'datetime="([^"]+)"', html)

        posts: list[dict] = []
        count = min(len(post_ids), len(raw_texts))

        for i in range(count):
            # Strip HTML tags from text
            clean_text = re.sub(r"<br\s*/?>", "\n", raw_texts[i])
            clean_text = re.sub(r"<[^>]+>", "", clean_text).strip()

            if not clean_text:
                continue

            # Parse views (handle K/M suffixes)
            views = 0
            if i < len(raw_views):
                views = self._parse_views(raw_views[i].strip())

            # Parse date
            post_date = ""
            if i < len(raw_dates):
                post_date = raw_dates[i][:10]  # YYYY-MM-DD

            posts.append({
                "id": int(post_ids[i]),
                "date": post_date,
                "text": clean_text,
                "views": views,
            })

        # Return most recent first, limited
        posts.reverse()
        posts = posts[:limit]

        logger.info("Fetched %d posts from @%s", len(posts), self.channel)
        return posts

    @staticmethod
    def _parse_views(views_str: str) -> int:
        """Parse view count string like '1.2K' or '15' into int."""
        views_str = views_str.strip().upper()
        if views_str.endswith("K"):
            return int(float(views_str[:-1]) * 1000)
        if views_str.endswith("M"):
            return int(float(views_str[:-1]) * 1_000_000)
        try:
            return int(views_str)
        except ValueError:
            return 0

    async def save_to_vault(self, posts: list[dict]) -> Path:
        """Save posts to vault/content/channel-archive/ as markdown."""
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
        """Format posts for inclusion in Claude prompt."""
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

        Selects posts with the most views (engagement = best writing).
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
