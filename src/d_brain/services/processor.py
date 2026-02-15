"""Claude processing service."""

import logging
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from d_brain.services.session import SessionStore

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1200  # 20 minutes


class ClaudeProcessor:
    """Service for triggering Claude Code processing."""

    def __init__(
        self,
        vault_path: Path,
        ticktick_client_id: str = "",
        ticktick_client_secret: str = "",
        ticktick_access_token: str = "",
        planfix_account: str = "",
        planfix_token: str = "",
    ) -> None:
        self.vault_path = Path(vault_path)
        self.ticktick_client_id = ticktick_client_id
        self.ticktick_client_secret = ticktick_client_secret
        self.ticktick_access_token = ticktick_access_token
        self.planfix_account = planfix_account
        self.planfix_token = planfix_token
        self._mcp_config_path = (self.vault_path.parent / "mcp-config.json").resolve()

    def _build_subprocess_env(self) -> dict[str, str]:
        """Build environment for Claude subprocess.

        Ensures PATH, HOME, and MCP-related vars are set correctly,
        especially when running from systemd where env is minimal.
        """
        env = os.environ.copy()
        # Ensure critical paths are available (systemd may have minimal PATH)
        path = env.get("PATH", "/usr/bin:/bin")
        for extra in ["/usr/local/bin", os.path.expanduser("~/.local/bin")]:
            if extra not in path:
                path = f"{extra}:{path}"
        env["PATH"] = path
        # HOME is needed by many tools
        if "HOME" not in env:
            env["HOME"] = os.path.expanduser("~")
        # MCP server startup settings
        env["MCP_TIMEOUT"] = "30000"
        env["MAX_MCP_OUTPUT_TOKENS"] = "50000"
        # TickTick credentials
        if self.ticktick_client_id:
            env["TICKTICK_CLIENT_ID"] = self.ticktick_client_id
        if self.ticktick_client_secret:
            env["TICKTICK_CLIENT_SECRET"] = self.ticktick_client_secret
        if self.ticktick_access_token:
            env["TICKTICK_ACCESS_TOKEN"] = self.ticktick_access_token
        # Planfix credentials
        if self.planfix_account:
            env["PLANFIX_ACCOUNT"] = self.planfix_account
        if self.planfix_token:
            env["PLANFIX_TOKEN"] = self.planfix_token
        return env

    def _load_skill_content(self) -> str:
        """Load dbrain-processor skill content for inclusion in prompt.

        NOTE: @vault/ references don't work in --print mode,
        so we must include skill content directly in the prompt.
        """
        skill_path = self.vault_path / ".claude/skills/dbrain-processor/SKILL.md"
        if skill_path.exists():
            return skill_path.read_text()
        return ""

    def _load_ticktick_reference(self) -> str:
        """Load TickTick reference for inclusion in prompt."""
        ref_path = self.vault_path / ".claude/skills/dbrain-processor/references/ticktick.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def _load_planfix_reference(self) -> str:
        """Load Planfix reference for inclusion in prompt."""
        ref_path = self.vault_path / ".claude/skills/dbrain-processor/references/planfix.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def _get_session_context(self, user_id: int) -> str:
        """Get today's session context for Claude.

        Args:
            user_id: Telegram user ID

        Returns:
            Recent session entries formatted for inclusion in prompt.
        """
        if user_id == 0:
            return ""

        session = SessionStore(self.vault_path)
        today_entries = session.get_today(user_id)
        if not today_entries:
            return ""

        lines = ["=== TODAY'S SESSION ==="]
        for entry in today_entries[-10:]:
            ts = entry.get("ts", "")[11:16]  # HH:MM from ISO
            entry_type = entry.get("type", "unknown")
            text = entry.get("text", "")[:80]
            if text:
                lines.append(f"{ts} [{entry_type}] {text}")
        lines.append("=== END SESSION ===\n")
        return "\n".join(lines)

    def _html_to_markdown(self, html: str) -> str:
        """Convert Telegram HTML to Obsidian Markdown."""
        import re

        text = html
        # <b>text</b> → **text**
        text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
        # <i>text</i> → *text*
        text = re.sub(r"<i>(.*?)</i>", r"*\1*", text)
        # <code>text</code> → `text`
        text = re.sub(r"<code>(.*?)</code>", r"`\1`", text)
        # <s>text</s> → ~~text~~
        text = re.sub(r"<s>(.*?)</s>", r"~~\1~~", text)
        # Remove <u> (no Markdown equivalent, just keep text)
        text = re.sub(r"</?u>", "", text)
        # <a href="url">text</a> → [text](url)
        text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", text)

        return text

    def _markdown_to_html(self, md: str) -> str:
        """Convert Obsidian Markdown back to Telegram HTML."""
        import re

        text = md
        # **text** → <b>text</b>
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        # *text* → <i>text</i> (but not inside already-converted bold)
        text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", text)
        # `text` → <code>text</code>
        text = re.sub(r"`([^`]+?)`", r"<code>\1</code>", text)
        # ~~text~~ → <s>text</s>
        text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
        # [text](url) → <a href="url">text</a>
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

        return text

    def _save_weekly_summary(self, report_html: str, week_date: date) -> Path:
        """Save weekly summary to vault/summaries/YYYY-WXX-summary.md."""
        # Calculate ISO week number
        year, week, _ = week_date.isocalendar()
        filename = f"{year}-W{week:02d}-summary.md"
        summary_path = self.vault_path / "summaries" / filename

        # Convert HTML to Markdown for Obsidian
        content = self._html_to_markdown(report_html)

        # Add frontmatter
        frontmatter = f"""---
date: {week_date.isoformat()}
type: weekly-summary
week: {year}-W{week:02d}
---

"""
        summary_path.write_text(frontmatter + content)
        logger.info("Weekly summary saved to %s", summary_path)
        return summary_path

    def _update_weekly_moc(self, summary_path: Path) -> None:
        """Add link to new summary in MOC-weekly.md."""
        moc_path = self.vault_path / "MOC" / "MOC-weekly.md"
        if moc_path.exists():
            content = moc_path.read_text()
            link = f"- [[summaries/{summary_path.name}|{summary_path.stem}]]"
            # Insert after "## Previous Weeks" if not already there
            if summary_path.stem not in content:
                content = content.replace(
                    "## Previous Weeks\n",
                    f"## Previous Weeks\n\n{link}\n",
                )
                moc_path.write_text(content)
                logger.info("Updated MOC-weekly.md with link to %s", summary_path.stem)

    def process_daily(self, day: date | None = None) -> dict[str, Any]:
        """Process daily file with Claude.

        Args:
            day: Date to process (default: today)

        Returns:
            Processing report as dict
        """
        if day is None:
            day = date.today()

        daily_file = self.vault_path / "daily" / f"{day.isoformat()}.md"

        if not daily_file.exists():
            logger.warning("No daily file for %s", day)
            return {
                "error": f"No daily file for {day}",
                "processed_entries": 0,
            }

        # Load skill content directly (@ references don't work in --print mode)
        skill_content = self._load_skill_content()

        prompt = f"""Сегодня {day}. Выполни ежедневную обработку.

=== SKILL INSTRUCTIONS ===
{skill_content}
=== END SKILL ===

ПЕРВЫМ ДЕЛОМ: вызови mcp__ticktick__get_user_projects чтобы убедиться что TickTick MCP работает.

CRITICAL MCP RULE:
- ТЫ ИМЕЕШЬ ДОСТУП к mcp__ticktick__* tools И mcp__planfix__* tools — ВЫЗЫВАЙ ИХ НАПРЯМУЮ
- НИКОГДА не пиши "MCP недоступен" или "добавь вручную"
- Для ЛИЧНЫХ задач и менторства: mcp__ticktick__create_task
- Для КОМАНДНЫХ задач (SMMEKALKA, C-GROWTH, KLEVERS): mcp__planfix__createTask
- Если tool вернул ошибку — покажи ТОЧНУЮ ошибку в отчёте
- См. references/planfix.md для правил маршрутизации задач

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ## , no ```, no tables
- Start directly with 📊 <b>Обработка за {day}</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- If entries already processed, return status report in same HTML format"""

        try:
            # Pass TickTick credentials + robust env to Claude subprocess
            env = self._build_subprocess_env()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                ],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                logger.error("Claude processing failed: %s", result.stderr)
                return {
                    "error": result.stderr or "Claude processing failed",
                    "processed_entries": 0,
                }

            # Return human-readable output
            output = result.stdout.strip()
            return {
                "report": output,
                "processed_entries": 1,  # успешно обработано
            }

        except subprocess.TimeoutExpired:
            logger.error("Claude processing timed out")
            return {
                "error": "Processing timed out",
                "processed_entries": 0,
            }
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return {
                "error": "Claude CLI not installed",
                "processed_entries": 0,
            }
        except Exception as e:
            logger.exception("Unexpected error during processing")
            return {
                "error": str(e),
                "processed_entries": 0,
            }

    def execute_prompt(self, user_prompt: str, user_id: int = 0) -> dict[str, Any]:
        """Execute arbitrary prompt with Claude.

        Args:
            user_prompt: User's natural language request
            user_id: Telegram user ID for session context

        Returns:
            Execution report as dict
        """
        today = date.today()

        # Load context
        ticktick_ref = self._load_ticktick_reference()
        planfix_ref = self._load_planfix_reference()
        session_context = self._get_session_context(user_id)

        prompt = f"""Ты - персональный ассистент d-brain.

CONTEXT:
- Текущая дата: {today}
- Vault path: {self.vault_path}

{session_context}=== TICKTICK REFERENCE ===
{ticktick_ref}
=== END REFERENCE ===

=== PLANFIX REFERENCE ===
{planfix_ref}
=== END REFERENCE ===

ПЕРВЫМ ДЕЛОМ: вызови mcp__ticktick__get_user_projects чтобы убедиться что MCP работает.

CRITICAL MCP RULE:
- ТЫ ИМЕЕШЬ ДОСТУП к mcp__ticktick__* tools И mcp__planfix__* tools — ВЫЗЫВАЙ ИХ НАПРЯМУЮ
- НИКОГДА не пиши "MCP недоступен" или "добавь вручную"
- Для ЛИЧНЫХ задач и менторства: mcp__ticktick__*
- Для КОМАНДНЫХ задач (SMMEKALKA, C-GROWTH, KLEVERS): mcp__planfix__*
- Если tool вернул ошибку — покажи ТОЧНУЮ ошибку в отчёте

USER REQUEST:
{user_prompt}

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables, no -
- Start with emoji and <b>header</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit

EXECUTION:
1. Analyze the request
2. Call MCP tools directly (mcp__ticktick__*, mcp__planfix__*, read/write files)
3. Return HTML status report with results"""

        try:
            env = self._build_subprocess_env()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                ],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                logger.error("Claude execution failed: %s", result.stderr)
                return {
                    "error": result.stderr or "Claude execution failed",
                    "processed_entries": 0,
                }

            return {
                "report": result.stdout.strip(),
                "processed_entries": 1,
            }

        except subprocess.TimeoutExpired:
            logger.error("Claude execution timed out")
            return {"error": "Execution timed out", "processed_entries": 0}
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return {"error": "Claude CLI not installed", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during execution")
            return {"error": str(e), "processed_entries": 0}

    def generate_weekly(self) -> dict[str, Any]:
        """Generate weekly digest with Claude.

        Returns:
            Weekly digest report as dict
        """
        today = date.today()

        prompt = f"""Сегодня {today}. Сгенерируй недельный дайджест.

ПЕРВЫМ ДЕЛОМ: вызови mcp__ticktick__get_user_projects чтобы убедиться что MCP работает.

CRITICAL MCP RULE:
- ТЫ ИМЕЕШЬ ДОСТУП к mcp__ticktick__* tools И mcp__planfix__* tools — ВЫЗЫВАЙ ИХ НАПРЯМУЮ
- НИКОГДА не пиши "MCP недоступен" или "добавь вручную"
- Для задач в проекте: вызови mcp__ticktick__get_project_with_data tool
- Для командных задач: вызови mcp__planfix__searchPlanfixTask tool
- Если tool вернул ошибку — покажи ТОЧНУЮ ошибку в отчёте

WORKFLOW:
1. Собери данные за неделю (daily файлы в vault/daily/, completed tasks через MCP — и TickTick, и Planfix)
2. Проанализируй прогресс по целям (goals/3-weekly.md)
3. Определи победы и вызовы
4. Сгенерируй HTML отчёт

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Start with 📅 <b>Недельный дайджест</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit"""

        try:
            env = self._build_subprocess_env()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                ],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                logger.error("Weekly digest failed: %s", result.stderr)
                return {
                    "error": result.stderr or "Weekly digest failed",
                    "processed_entries": 0,
                }

            output = result.stdout.strip()

            # Save to summaries/ and update MOC
            try:
                summary_path = self._save_weekly_summary(output, today)
                self._update_weekly_moc(summary_path)
            except Exception as e:
                logger.warning("Failed to save weekly summary: %s", e)

            return {
                "report": output,
                "processed_entries": 1,
            }

        except subprocess.TimeoutExpired:
            logger.error("Weekly digest timed out")
            return {"error": "Weekly digest timed out", "processed_entries": 0}
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return {"error": "Claude CLI not installed", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during weekly digest")
            return {"error": str(e), "processed_entries": 0}

    def _summarize_meeting(self, name: str, text: str, cache_dir: Path | None = None) -> str:
        """Summarize a long meeting transcript via Claude.

        Caches the summary next to the original file so repeated
        /content runs don't re-summarize the same meetings.

        Returns a concise summary with key insights, decisions, and
        interesting thoughts — so nothing important is lost.
        """
        # Check cache first
        if cache_dir:
            cache_file = cache_dir / f"{name}.summary.md"
            if cache_file.exists():
                cached = cache_file.read_text()
                if cached.strip():
                    logger.info("Using cached summary for %s", name)
                    return f"[SUMMARY]\n{cached}"

        prompt = (
            "Ты суммаризатор встреч. Извлеки из транскрипта ВСЕ ключевые мысли, "
            "решения, инсайты, интересные идеи и цитаты. Ничего важного не пропускай.\n\n"
            "Формат ответа — краткий конспект (bullet points), до 2000 слов. "
            "Пиши на том же языке, что и транскрипт.\n\n"
            f"=== TRANSCRIPT: {name} ===\n{text}"
        )
        try:
            result = subprocess.run(
                ["claude", "--print", "--dangerously-skip-permissions"],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                summary = result.stdout.strip()
                logger.info("Summarized meeting %s: %d → %d chars", name, len(text), len(summary))
                # Save to cache
                if cache_dir:
                    try:
                        cache_file = cache_dir / f"{name}.summary.md"
                        cache_file.write_text(summary)
                    except Exception as e:
                        logger.warning("Failed to cache summary for %s: %s", name, e)
                return f"[SUMMARY]\n{summary}"
        except Exception as e:
            logger.warning("Failed to summarize meeting %s: %s", name, e)
        # Fallback: return original text (stdin handles large prompts)
        return text

    def _collect_raw_material(self, days: int = 7) -> str:
        """Collect raw material from vault for content seed generation.

        Gathers daily files, meeting transcripts, and thoughts
        from the last N days.

        Args:
            days: Number of days to look back.

        Returns:
            Combined text of all raw material.
        """
        today = date.today()
        parts: list[str] = []

        # Collect daily files
        daily_dir = self.vault_path / "daily"
        if daily_dir.exists():
            for i in range(days):
                day = today - timedelta(days=i)
                daily_file = daily_dir / f"{day.isoformat()}.md"
                if daily_file.exists():
                    content = daily_file.read_text()
                    if content.strip():
                        parts.append(f"=== DAILY {day.isoformat()} ===\n{content}")

        # Collect meeting transcripts — summarize large ones (with cache)
        meetings_dir = self.vault_path / "content" / "meetings"
        if meetings_dir.exists():
            cutoff = today - timedelta(days=days)
            for md_file in sorted(meetings_dir.glob("*.md"), reverse=True):
                if md_file.name.endswith(".summary.md"):
                    continue  # skip cached summaries
                try:
                    file_date = date.fromisoformat(md_file.name[:10])
                    if file_date >= cutoff:
                        content = md_file.read_text()
                        if content.strip():
                            if len(content) > 5000:
                                content = self._summarize_meeting(
                                    md_file.stem, content, cache_dir=meetings_dir,
                                )
                            parts.append(
                                f"=== MEETING {md_file.stem} ===\n{content}"
                            )
                except ValueError:
                    continue

        # Collect thoughts
        thoughts_dir = self.vault_path / "thoughts"
        if thoughts_dir.exists():
            cutoff = today - timedelta(days=days)
            for md_file in sorted(thoughts_dir.glob("*.md"), reverse=True):
                try:
                    file_date = date.fromisoformat(md_file.name[:10])
                    if file_date >= cutoff:
                        content = md_file.read_text()
                        if content.strip():
                            parts.append(
                                f"=== THOUGHT {md_file.stem} ===\n{content}"
                            )
                except ValueError:
                    continue

        if not parts:
            return ""

        return "\n\n".join(parts)

    def _save_content_seeds(self, html: str, seeds_date: date) -> Path:
        """Save content seeds to vault/content/seeds/YYYY-WXX-seeds.md."""
        year, week, _ = seeds_date.isocalendar()
        filename = f"{year}-W{week:02d}-seeds.md"
        seeds_dir = self.vault_path / "content" / "seeds"
        seeds_dir.mkdir(parents=True, exist_ok=True)
        seeds_path = seeds_dir / filename

        content = self._html_to_markdown(html)
        frontmatter = f"""---
date: {seeds_date.isoformat()}
type: content-seeds
week: {year}-W{week:02d}
---

"""
        seeds_path.write_text(frontmatter + content)
        logger.info("Content seeds saved to %s", seeds_path)
        return seeds_path

    def _load_content_seeds_skill(self) -> str:
        """Load content-seeds skill content."""
        skill_path = self.vault_path / ".claude/skills/content-seeds/SKILL.md"
        if skill_path.exists():
            return skill_path.read_text()
        return ""

    def _load_humanizer_reference(self) -> str:
        """Load humanizer reference for content quality."""
        ref_path = self.vault_path / ".claude/skills/content-seeds/references/humanizer.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def _load_tone_of_voice(self) -> str:
        """Load combined tone of voice + humanizer reference."""
        ref_path = self.vault_path / ".claude/skills/content-seeds/references/tone-of-voice.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def _load_strategy(self) -> str:
        """Load content strategy reference."""
        ref_path = self.vault_path / ".claude/skills/content-seeds/references/strategy.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def _load_icp(self) -> str:
        """Load ICP & positioning reference."""
        ref_path = self.vault_path / ".claude/skills/content-seeds/references/icp.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def _load_tone_examples(self) -> str:
        """Load tone of voice examples from real channel posts."""
        ref_path = self.vault_path / ".claude/skills/content-seeds/references/tone-examples.md"
        if ref_path.exists():
            return ref_path.read_text()
        return ""

    def generate_content_seeds(self) -> dict[str, Any]:
        """Generate content seeds from weekly raw material.

        Returns:
            Content seeds report as dict.
        """
        today = date.today()

        # Load skill and references
        skill_content = self._load_content_seeds_skill()
        tone_of_voice = self._load_tone_of_voice()
        strategy = self._load_strategy()
        icp = self._load_icp()
        tone_examples = self._load_tone_examples()

        # Collect raw material in Python (more reliable than asking Claude to read files)
        raw_material = self._collect_raw_material(days=7)
        if not raw_material:
            return {
                "error": "Нет записей за последние 7 дней для генерации seeds",
                "processed_entries": 0,
            }

        # Build references section
        references = ""
        if tone_of_voice:
            references += f"\n=== TONE OF VOICE & HUMANIZER ===\n{tone_of_voice}\n=== END TONE OF VOICE ===\n"
        if strategy:
            references += f"\n=== CONTENT STRATEGY ===\n{strategy}\n=== END STRATEGY ===\n"
        if icp:
            references += f"\n=== ICP & POSITIONING ===\n{icp}\n=== END ICP ===\n"
        if tone_examples:
            references += f"\n=== TONE OF VOICE EXAMPLES ===\n{tone_examples}\n=== END TONE EXAMPLES ===\n"

        prompt = f"""Сегодня {today}. Сгенерируй content seeds из сырого материала.

=== SKILL INSTRUCTIONS ===
{skill_content}
=== END SKILL ===
{references}
=== RAW MATERIAL (last 7 days) ===
{raw_material}
=== END RAW MATERIAL ===

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Follow the output format from SKILL INSTRUCTIONS exactly

CRITICAL RULES:
- Оценивай seeds по матрице из CONTENT STRATEGY (арка, функция, тон)
- Каждый seed ОБЯЗАН принадлежать одной из 3 нарративных арок
- Целься в конкретный сегмент ICP - кто прочтёт и кивнёт?
- Применяй ВСЕ правила из TONE OF VOICE (голос Марины + анти-AI фильтр)
- Каждый hook проверяй на AI-паттерны перед выдачей
- Пиши как живой человек, не как ChatGPT"""

        try:
            env = self._build_subprocess_env()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                ],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                logger.error("Content seeds generation failed: %s", result.stderr)
                return {
                    "error": result.stderr or "Content seeds generation failed",
                    "processed_entries": 0,
                }

            output = result.stdout.strip()

            # Save to vault
            try:
                self._save_content_seeds(output, today)
            except Exception as e:
                logger.warning("Failed to save content seeds: %s", e)

            return {
                "report": output,
                "processed_entries": 1,
            }

        except subprocess.TimeoutExpired:
            logger.error("Content seeds generation timed out")
            return {"error": "Content seeds generation timed out", "processed_entries": 0}
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return {"error": "Claude CLI not installed", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during content seeds generation")
            return {"error": str(e), "processed_entries": 0}

    def _load_all_seeds(self, max_weeks: int = 8) -> str:
        """Load accumulated content seeds from recent weeks.

        Reads up to max_weeks of seed files so unused seeds
        carry over and can be selected in future plans.
        """
        seeds_dir = self.vault_path / "content" / "seeds"
        if not seeds_dir.exists():
            return ""
        seed_files = sorted(seeds_dir.glob("*.md"), reverse=True)[:max_weeks]
        if not seed_files:
            return ""
        parts = []
        for f in seed_files:
            parts.append(f"=== {f.stem} ===\n{f.read_text()}")
        return "\n\n".join(parts)

    def _load_content_planner_skill(self) -> str:
        """Load content-planner skill content."""
        skill_path = self.vault_path / ".claude/skills/content-planner/SKILL.md"
        if skill_path.exists():
            return skill_path.read_text()
        return ""

    def _load_monthly_goals(self) -> str:
        """Load current monthly goals for content alignment."""
        goals_path = self.vault_path / "goals" / "2-monthly.md"
        if goals_path.exists():
            return goals_path.read_text()
        return ""

    def _save_content_plan(self, html: str, plan_date: date) -> Path:
        """Save content plan to vault/content/plans/YYYY-WXX-plan.md."""
        year, week, _ = plan_date.isocalendar()
        filename = f"{year}-W{week:02d}-plan.md"
        plans_dir = self.vault_path / "content" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / filename

        content = self._html_to_markdown(html)
        frontmatter = f"""---
date: {plan_date.isoformat()}
type: content-plan
week: {year}-W{week:02d}
---

"""
        plan_path.write_text(frontmatter + content)
        logger.info("Content plan saved to %s", plan_path)
        return plan_path

    def generate_content_plan(
        self, channel_posts: str = "", target_date: date | None = None,
    ) -> dict[str, Any]:
        """Generate weekly content plan from seeds and channel history.

        Args:
            channel_posts: Formatted recent channel posts for context.
            target_date: Date to generate plan for (default: today).

        Returns:
            Content plan report as dict.
        """
        today = target_date or date.today()

        # Load skill and context
        skill_content = self._load_content_planner_skill()
        tone_of_voice = self._load_tone_of_voice()
        strategy = self._load_strategy()
        icp = self._load_icp()
        seeds_content = self._load_all_seeds()
        monthly_goals = self._load_monthly_goals()

        if not seeds_content:
            return {
                "error": "Нет content seeds. Сначала запусти /content",
                "processed_entries": 0,
            }

        # Build context sections
        context_parts = []
        if channel_posts:
            context_parts.append(
                f"=== RECENT CHANNEL POSTS ===\n{channel_posts}\n=== END CHANNEL POSTS ==="
            )
        if monthly_goals:
            context_parts.append(
                f"=== MONTHLY GOALS ===\n{monthly_goals}\n=== END MONTHLY GOALS ==="
            )
        extra_context = "\n\n".join(context_parts)

        # Build references
        references = ""
        if tone_of_voice:
            references += f"\n=== TONE OF VOICE & HUMANIZER ===\n{tone_of_voice}\n=== END TONE OF VOICE ===\n"
        if strategy:
            references += f"\n=== CONTENT STRATEGY ===\n{strategy}\n=== END STRATEGY ===\n"
        if icp:
            references += f"\n=== ICP & POSITIONING ===\n{icp}\n=== END ICP ===\n"

        prompt = f"""Сегодня {today}. Составь контент-план на неделю.

=== SKILL INSTRUCTIONS ===
{skill_content}
=== END SKILL ===
{references}
=== CONTENT SEEDS ===
{seeds_content}
=== END CONTENT SEEDS ===

{extra_context}

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Follow the output format from SKILL INSTRUCTIONS exactly

CRITICAL RULES:
- Чередуй нарративные арки по правилам CONTENT STRATEGY
- Проверяй последние посты канала - не повторять тему
- Каждый пост целься в конкретный сегмент ICP
- Все hooks пиши живым языком по правилам TONE OF VOICE
- Никакого AI-стиля, канцелярита, шаблонных переходов"""

        try:
            env = self._build_subprocess_env()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                ],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
                env=env,
            )

            if result.returncode != 0:
                logger.error("Content plan generation failed: %s", result.stderr)
                return {
                    "error": result.stderr or "Content plan generation failed",
                    "processed_entries": 0,
                }

            output = result.stdout.strip()

            # Save to vault
            try:
                self._save_content_plan(output, today)
            except Exception as e:
                logger.warning("Failed to save content plan: %s", e)

            return {
                "report": output,
                "processed_entries": 1,
            }

        except subprocess.TimeoutExpired:
            logger.error("Content plan generation timed out")
            return {"error": "Content plan generation timed out", "processed_entries": 0}
        except FileNotFoundError:
            logger.error("Claude CLI not found")
            return {"error": "Claude CLI not installed", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during content plan generation")
            return {"error": str(e), "processed_entries": 0}

    # --- Content viewing & plan management methods ---

    def _extract_seed_titles(self) -> list[dict]:
        """Extract seed titles from all seed files.

        Returns:
            List of dicts: {"week", "num", "title", "full_text"}.
        """
        import re

        seeds_dir = self.vault_path / "content" / "seeds"
        if not seeds_dir.exists():
            return []

        seed_files = sorted(seeds_dir.glob("*.md"), reverse=True)[:8]
        results: list[dict] = []

        for f in seed_files:
            if f.name == ".gitkeep":
                continue
            content = f.read_text()
            # Extract week from frontmatter or filename
            week = ""
            week_match = re.search(r"week:\s*(\S+)", content)
            if week_match:
                week = week_match.group(1)
            else:
                # Try filename: 2026-W07-seeds.md
                fname_match = re.match(r"(\d{4}-W\d{2})", f.name)
                if fname_match:
                    week = fname_match.group(1)

            # Strip frontmatter for content parsing
            body = content
            if body.startswith("---"):
                end = body.find("---", 3)
                if end != -1:
                    body = body[end + 3:].strip()

            # Find all seeds: "Seed #N: title" or "**Seed #N: title**"
            seed_pattern = re.compile(
                r"\*{0,2}Seed\s*#(\d+)[:\s]+(.+?)\*{0,2}\s*$", re.MULTILINE,
            )
            # Split body into seed blocks
            seed_starts = list(seed_pattern.finditer(body))
            for i, m in enumerate(seed_starts):
                num = int(m.group(1))
                title = m.group(2).strip().rstrip("*")
                # Full text = from this match to next seed or end
                start = m.start()
                end_pos = seed_starts[i + 1].start() if i + 1 < len(seed_starts) else len(body)
                full_text = body[start:end_pos].strip()
                results.append({
                    "week": week,
                    "num": num,
                    "title": title,
                    "full_text": full_text,
                })

        return results

    def get_current_plan(self, week_offset: int = 0) -> dict[str, Any]:
        """Read plan file for current (or offset) week.

        Args:
            week_offset: 0 = current week, 1 = next week.

        Returns:
            Dict with 'plan' content, 'week' id, 'path', or 'error'.
        """
        target = date.today() + timedelta(weeks=week_offset)
        year, week, _ = target.isocalendar()
        week_id = f"{year}-W{week:02d}"
        filename = f"{week_id}-plan.md"
        plan_path = self.vault_path / "content" / "plans" / filename

        if not plan_path.exists():
            return {"error": f"План на {week_id} не найден"}

        content = plan_path.read_text()
        # Strip frontmatter
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].strip()

        return {"plan": content, "week": week_id, "path": str(plan_path)}

    def plan_exists_for_week(self, week_offset: int = 0) -> bool:
        """Check if a plan file exists for the given week."""
        target = date.today() + timedelta(weeks=week_offset)
        year, week, _ = target.isocalendar()
        filename = f"{year}-W{week:02d}-plan.md"
        return (self.vault_path / "content" / "plans" / filename).exists()

    @property
    def _dismissed_path(self) -> Path:
        return self.vault_path / "content" / "seeds" / ".dismissed.json"

    def _load_dismissed(self) -> set[str]:
        """Load set of dismissed seed keys like '2026-W07:3'."""
        import json

        if not self._dismissed_path.exists():
            return set()
        try:
            data = json.loads(self._dismissed_path.read_text())
            return set(data.get("dismissed", []))
        except Exception:
            return set()

    def _save_dismissed(self, dismissed: set[str]) -> None:
        """Save dismissed seed keys."""
        import json

        self._dismissed_path.parent.mkdir(parents=True, exist_ok=True)
        self._dismissed_path.write_text(
            json.dumps({"dismissed": sorted(dismissed)}, ensure_ascii=False, indent=2),
        )

    def dismiss_seeds(self, seeds_to_dismiss: list[dict]) -> int:
        """Mark seeds as dismissed. Returns count of newly dismissed."""
        dismissed = self._load_dismissed()
        count = 0
        for s in seeds_to_dismiss:
            key = f"{s['week']}:{s['num']}"
            if key not in dismissed:
                dismissed.add(key)
                count += 1
        self._save_dismissed(dismissed)
        return count

    def list_unpublished_seeds(self, channel_posts: str) -> dict[str, Any]:
        """List all seeds, marking which have been published.

        Uses a lightweight Claude call to match seed titles with channel posts.
        Also filters out manually dismissed seeds.

        Args:
            channel_posts: Formatted recent channel posts text.

        Returns:
            Dict with 'seeds' list and 'published_indices'.
        """
        all_seeds = self._extract_seed_titles()
        if not all_seeds:
            return {"error": "Нет seeds. Запусти /content для генерации."}

        # Filter out dismissed seeds
        dismissed = self._load_dismissed()
        active_seeds = [
            s for s in all_seeds
            if f"{s['week']}:{s['num']}" not in dismissed
        ]
        dismissed_count = len(all_seeds) - len(active_seeds)

        if not active_seeds:
            return {"error": "Все seeds удалены или опубликованы. Запусти /content для новых."}

        # Build compact title list for Claude (only active seeds)
        titles_text = "\n".join(
            f"{i + 1}. [{s['week']}] Seed #{s['num']}: {s['title']}"
            for i, s in enumerate(active_seeds)
        )

        prompt = f"""Ты определяешь, какие content seeds УЖЕ были опубликованы как посты в TG-канале.

ПРАВИЛА МАТЧИНГА (СТРОГО):
- Seed считается опубликованным ТОЛЬКО если в канале есть пост, который ЯВНО раскрывает ТУ ЖЕ КОНКРЕТНУЮ историю или кейс
- Тематическое сходство НЕ считается совпадением. Пример: seed про "страх вложить 50К" и пост про "бюджетирование" - это НЕ совпадение
- Если сомневаешься - seed НЕ опубликован
- Большинство seeds скорее всего НЕ опубликованы - это нормально

=== СПИСОК SEEDS ===
{titles_text}
=== END SEEDS ===

=== ПОСТЫ КАНАЛА ===
{channel_posts}
=== END POSTS ===

Верни ТОЛЬКО номера опубликованных seeds через запятую (пример: 1,3,7).
Если ни один не опубликован, верни слово "none".
Ничего больше не пиши."""

        try:
            result = subprocess.run(
                ["claude", "--print", "--dangerously-skip-permissions"],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            published_indices: set[int] = set()
            if result.returncode == 0 and result.stdout.strip().lower() != "none":
                import re
                numbers = re.findall(r"\d+", result.stdout.strip())
                published_indices = {int(n) for n in numbers if 1 <= int(n) <= len(active_seeds)}

            # Build result: only unpublished
            unpublished = []
            for i, s in enumerate(active_seeds):
                s["published"] = (i + 1) in published_indices
                if not s["published"]:
                    unpublished.append(s)

            return {
                "seeds": active_seeds,
                "unpublished": unpublished,
                "total": len(all_seeds),
                "published_count": len(published_indices),
                "dismissed_count": dismissed_count,
            }

        except Exception as e:
            logger.warning("Failed to match seeds with channel: %s", e)
            # Fallback: return active seeds as unpublished
            return {
                "seeds": active_seeds,
                "unpublished": active_seeds,
                "total": len(all_seeds),
                "published_count": 0,
                "dismissed_count": dismissed_count,
            }

    def reconcile_plan_with_channel(self, channel_posts: str) -> dict[str, Any]:
        """Compare plan with published posts, suggest adjustments.

        Args:
            channel_posts: Formatted recent channel posts text.

        Returns:
            Updated plan report as dict.
        """
        plan_data = self.get_current_plan()
        if "error" in plan_data:
            return plan_data

        tone_of_voice = self._load_tone_of_voice()
        strategy = self._load_strategy()

        prompt = f"""Сравни контент-план с опубликованными постами канала.

=== КОНТЕНТ-ПЛАН ({plan_data['week']}) ===
{plan_data['plan']}
=== END PLAN ===

=== ПОСТЫ КАНАЛА ===
{channel_posts}
=== END POSTS ===

=== TONE OF VOICE & HUMANIZER ===
{tone_of_voice}
=== END TONE OF VOICE ===

=== CONTENT STRATEGY ===
{strategy}
=== END STRATEGY ===

ЗАДАЧА:
1. Определи какие посты из плана уже опубликованы - отметь их ✅
2. Для неопубликованных - оставь как есть или скорректируй если нужно
3. Проверь чередование арок по правилам CONTENT STRATEGY
4. Верни полный обновлённый план

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Все hooks пиши живым языком по правилам TONE OF VOICE"""

        try:
            result = subprocess.run(
                ["claude", "--print", "--dangerously-skip-permissions"],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
            )

            if result.returncode != 0:
                return {
                    "error": result.stderr or "Reconciliation failed",
                    "processed_entries": 0,
                }

            output = result.stdout.strip()

            # Save updated plan
            try:
                self._save_content_plan(output, date.today())
            except Exception as e:
                logger.warning("Failed to save reconciled plan: %s", e)

            return {"report": output, "processed_entries": 1}

        except subprocess.TimeoutExpired:
            return {"error": "Reconciliation timed out", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during reconciliation")
            return {"error": str(e), "processed_entries": 0}

    def edit_plan(self, user_request: str) -> dict[str, Any]:
        """Edit current plan based on user request.

        Args:
            user_request: Natural language edit instruction.

        Returns:
            Updated plan report as dict.
        """
        plan_data = self.get_current_plan()
        if "error" in plan_data:
            return plan_data

        seeds_content = self._load_all_seeds(max_weeks=4)
        tone_of_voice = self._load_tone_of_voice()
        strategy = self._load_strategy()
        icp = self._load_icp()

        # Build references
        references = ""
        if tone_of_voice:
            references += f"\n=== TONE OF VOICE & HUMANIZER ===\n{tone_of_voice}\n=== END TONE OF VOICE ===\n"
        if strategy:
            references += f"\n=== CONTENT STRATEGY ===\n{strategy}\n=== END STRATEGY ===\n"
        if icp:
            references += f"\n=== ICP & POSITIONING ===\n{icp}\n=== END ICP ===\n"

        prompt = f"""Отредактируй контент-план по запросу пользователя.

=== ТЕКУЩИЙ ПЛАН ({plan_data['week']}) ===
{plan_data['plan']}
=== END PLAN ===

=== ДОСТУПНЫЕ SEEDS ===
{seeds_content}
=== END SEEDS ===
{references}
ЗАПРОС ПОЛЬЗОВАТЕЛЯ: {user_request}

ЗАДАЧА:
- Внеси запрошенные изменения в план
- Сохрани общую структуру плана (дни, форматы, LinkedIn)
- Используй seeds из списка если нужно заменить/добавить контент
- Чередуй арки по правилам CONTENT STRATEGY
- Все hooks пиши живым языком по правилам TONE OF VOICE

CRITICAL OUTPUT FORMAT:
- Return the FULL updated plan in raw HTML for Telegram
- NO markdown: no **, no ##, no ```, no tables
- Allowed tags: <b>, <i>, <code>, <s>, <u>"""

        try:
            result = subprocess.run(
                ["claude", "--print", "--dangerously-skip-permissions"],
                input=prompt,
                cwd=self.vault_path.parent,
                capture_output=True,
                text=True,
                timeout=DEFAULT_TIMEOUT,
                check=False,
            )

            if result.returncode != 0:
                return {
                    "error": result.stderr or "Plan edit failed",
                    "processed_entries": 0,
                }

            output = result.stdout.strip()

            # Save updated plan
            try:
                self._save_content_plan(output, date.today())
            except Exception as e:
                logger.warning("Failed to save edited plan: %s", e)

            return {"report": output, "processed_entries": 1}

        except subprocess.TimeoutExpired:
            return {"error": "Plan edit timed out", "processed_entries": 0}
        except Exception as e:
            logger.exception("Unexpected error during plan edit")
            return {"error": str(e), "processed_entries": 0}
