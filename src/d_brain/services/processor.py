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
    ) -> None:
        self.vault_path = Path(vault_path)
        self.ticktick_client_id = ticktick_client_id
        self.ticktick_client_secret = ticktick_client_secret
        self.ticktick_access_token = ticktick_access_token
        self._mcp_config_path = (self.vault_path.parent / "mcp-config.json").resolve()

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

ПЕРВЫМ ДЕЛОМ: вызови mcp__ticktick__get_user_projects чтобы убедиться что MCP работает.

CRITICAL MCP RULE:
- ТЫ ИМЕЕШЬ ДОСТУП к mcp__ticktick__* tools — ВЫЗЫВАЙ ИХ НАПРЯМУЮ
- НИКОГДА не пиши "MCP недоступен" или "добавь вручную"
- Для задач: вызови mcp__ticktick__create_task tool
- Если tool вернул ошибку — покажи ТОЧНУЮ ошибку в отчёте

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ## , no ```, no tables
- Start directly with 📊 <b>Обработка за {day}</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- If entries already processed, return status report in same HTML format"""

        try:
            # Pass TickTick credentials to Claude subprocess
            env = os.environ.copy()
            if self.ticktick_client_id:
                env["TICKTICK_CLIENT_ID"] = self.ticktick_client_id
            if self.ticktick_client_secret:
                env["TICKTICK_CLIENT_SECRET"] = self.ticktick_client_secret
            if self.ticktick_access_token:
                env["TICKTICK_ACCESS_TOKEN"] = self.ticktick_access_token

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                    "-p",
                    prompt,
                ],
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
        session_context = self._get_session_context(user_id)

        prompt = f"""Ты - персональный ассистент d-brain.

CONTEXT:
- Текущая дата: {today}
- Vault path: {self.vault_path}

{session_context}=== TICKTICK REFERENCE ===
{ticktick_ref}
=== END REFERENCE ===

ПЕРВЫМ ДЕЛОМ: вызови mcp__ticktick__get_user_projects чтобы убедиться что MCP работает.

CRITICAL MCP RULE:
- ТЫ ИМЕЕШЬ ДОСТУП к mcp__ticktick__* tools — ВЫЗЫВАЙ ИХ НАПРЯМУЮ
- НИКОГДА не пиши "MCP недоступен" или "добавь вручную"
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
2. Call MCP tools directly (mcp__ticktick__*, read/write files)
3. Return HTML status report with results"""

        try:
            env = os.environ.copy()
            if self.ticktick_client_id:
                env["TICKTICK_CLIENT_ID"] = self.ticktick_client_id
            if self.ticktick_client_secret:
                env["TICKTICK_CLIENT_SECRET"] = self.ticktick_client_secret
            if self.ticktick_access_token:
                env["TICKTICK_ACCESS_TOKEN"] = self.ticktick_access_token

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                    "-p",
                    prompt,
                ],
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
- ТЫ ИМЕЕШЬ ДОСТУП к mcp__ticktick__* tools — ВЫЗЫВАЙ ИХ НАПРЯМУЮ
- НИКОГДА не пиши "MCP недоступен" или "добавь вручную"
- Для задач в проекте: вызови mcp__ticktick__get_project_with_data tool
- Если tool вернул ошибку — покажи ТОЧНУЮ ошибку в отчёте

WORKFLOW:
1. Собери данные за неделю (daily файлы в vault/daily/, completed tasks через MCP)
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
            env = os.environ.copy()
            if self.ticktick_client_id:
                env["TICKTICK_CLIENT_ID"] = self.ticktick_client_id
            if self.ticktick_client_secret:
                env["TICKTICK_CLIENT_SECRET"] = self.ticktick_client_secret
            if self.ticktick_access_token:
                env["TICKTICK_ACCESS_TOKEN"] = self.ticktick_access_token

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "--mcp-config",
                    str(self._mcp_config_path),
                    "-p",
                    prompt,
                ],
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

        # Collect meeting transcripts
        meetings_dir = self.vault_path / "content" / "meetings"
        if meetings_dir.exists():
            cutoff = today - timedelta(days=days)
            for md_file in sorted(meetings_dir.glob("*.md"), reverse=True):
                # Filename starts with YYYY-MM-DD
                try:
                    file_date = date.fromisoformat(md_file.name[:10])
                    if file_date >= cutoff:
                        content = md_file.read_text()
                        if content.strip():
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
        humanizer_content = self._load_humanizer_reference()
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
        if humanizer_content:
            references += f"\n=== HUMANIZER REFERENCE ===\n{humanizer_content}\n=== END HUMANIZER ===\n"
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

CRITICAL STYLE RULE:
- Применяй ВСЕ правила из HUMANIZER REFERENCE
- Каждый hook проверяй на AI-паттерны перед выдачей
- Пиши как живой человек, не как ChatGPT"""

        try:
            env = os.environ.copy()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "-p",
                    prompt,
                ],
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

    def generate_content_plan(self, channel_posts: str = "") -> dict[str, Any]:
        """Generate weekly content plan from seeds and channel history.

        Args:
            channel_posts: Formatted recent channel posts for context.

        Returns:
            Content plan report as dict.
        """
        today = date.today()

        # Load skill and context
        skill_content = self._load_content_planner_skill()
        humanizer_content = self._load_humanizer_reference()
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

        prompt = f"""Сегодня {today}. Составь контент-план на неделю.

=== SKILL INSTRUCTIONS ===
{skill_content}
=== END SKILL ===

=== HUMANIZER REFERENCE ===
{humanizer_content}
=== END HUMANIZER ===

=== CONTENT SEEDS ===
{seeds_content}
=== END CONTENT SEEDS ===

{extra_context}

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Follow the output format from SKILL INSTRUCTIONS exactly

CRITICAL STYLE RULE:
- Все hooks пиши живым языком по правилам HUMANIZER REFERENCE
- Никакого AI-стиля, канцелярита, шаблонных переходов"""

        try:
            env = os.environ.copy()

            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--dangerously-skip-permissions",
                    "-p",
                    prompt,
                ],
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
