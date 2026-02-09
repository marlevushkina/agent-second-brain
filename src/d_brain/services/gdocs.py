"""Google Docs sync service for Fireflies meeting transcripts."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class GoogleDocsSync:
    """Sync meeting transcripts from Google Drive folder to vault."""

    def __init__(
        self,
        vault_path: Path,
        folder_id: str,
        credentials_path: Path,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.folder_id = folder_id
        self.credentials_path = credentials_path
        self.meetings_path = self.vault_path / "content" / "meetings"

    def _get_existing_gdoc_ids(self) -> set[str]:
        """Scan existing meeting files for gdoc_id in frontmatter."""
        ids: set[str] = set()
        if not self.meetings_path.exists():
            return ids
        for md_file in self.meetings_path.glob("*.md"):
            content = md_file.read_text()
            match = re.search(r"^gdoc_id:\s*(.+)$", content, re.MULTILINE)
            if match:
                ids.add(match.group(1).strip())
        return ids

    @staticmethod
    def _slugify(title: str) -> str:
        """Convert title to filesystem-safe slug."""
        slug = title.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "-", slug)
        slug = re.sub(r"-+", "-", slug)
        return slug[:80].strip("-")

    def sync(self) -> dict:
        """Sync Google Docs from folder to vault.

        Returns:
            Dict with sync results: synced count, skipped, errors.
        """
        if not self.folder_id:
            return {"synced": 0, "skipped": "not_configured"}

        if not self.credentials_path or not self.credentials_path.exists():
            logger.warning("Google credentials file not found: %s", self.credentials_path)
            return {"synced": 0, "skipped": "no_credentials"}

        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError:
            logger.error("Google API libraries not installed. Run: uv sync")
            return {"synced": 0, "skipped": "libs_not_installed"}

        try:
            creds = Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=[
                    "https://www.googleapis.com/auth/drive.readonly",
                    "https://www.googleapis.com/auth/documents.readonly",
                ],
            )
            drive = build("drive", "v3", credentials=creds)
            docs = build("docs", "v1", credentials=creds)
        except Exception as e:
            logger.error("Failed to initialize Google API: %s", e)
            return {"synced": 0, "error": str(e)}

        existing_ids = self._get_existing_gdoc_ids()
        self.meetings_path.mkdir(parents=True, exist_ok=True)

        synced = 0
        skipped = 0

        try:
            query = (
                f"'{self.folder_id}' in parents"
                " and mimeType='application/vnd.google-apps.document'"
                " and trashed=false"
            )
            results = drive.files().list(
                q=query,
                fields="files(id, name, createdTime)",
                orderBy="createdTime desc",
                pageSize=50,
            ).execute()

            files = results.get("files", [])
            logger.info("Found %d docs in Google Drive folder", len(files))

            for file_info in files:
                gdoc_id = file_info["id"]

                if gdoc_id in existing_ids:
                    skipped += 1
                    continue

                try:
                    doc = docs.documents().get(documentId=gdoc_id).execute()
                    text = self._extract_text(doc)

                    if not text.strip():
                        skipped += 1
                        continue

                    # Parse date from createdTime (2024-01-15T10:30:00.000Z)
                    created = file_info["createdTime"][:10]
                    title = file_info["name"]
                    slug = self._slugify(title)
                    filename = f"{created}-{slug}.md"

                    frontmatter = (
                        f"---\n"
                        f"gdoc_id: {gdoc_id}\n"
                        f"title: {title}\n"
                        f"date: {created}\n"
                        f"type: meeting-transcript\n"
                        f"---\n\n"
                    )

                    filepath = self.meetings_path / filename
                    filepath.write_text(frontmatter + text)
                    synced += 1
                    logger.info("Synced: %s", filename)

                except Exception as e:
                    logger.error("Failed to sync doc %s: %s", gdoc_id, e)

        except Exception as e:
            logger.error("Failed to list Google Drive files: %s", e)
            return {"synced": synced, "skipped": skipped, "error": str(e)}

        return {"synced": synced, "skipped": skipped}

    @staticmethod
    def _extract_text(doc: dict) -> str:
        """Extract plain text from Google Docs document JSON."""
        text_parts: list[str] = []
        body = doc.get("body", {})
        content = body.get("content", [])

        for element in content:
            paragraph = element.get("paragraph")
            if not paragraph:
                continue
            for elem in paragraph.get("elements", []):
                text_run = elem.get("textRun")
                if text_run:
                    text_parts.append(text_run.get("content", ""))

        return "".join(text_parts)
