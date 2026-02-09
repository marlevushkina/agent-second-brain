"""Google Docs sync service for Fireflies meeting transcripts."""

import io
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported MIME types
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER_MIME = "application/vnd.google-apps.folder"


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

    def _list_files_recursive(self, drive, folder_id: str) -> list[dict]:
        """List all document files in folder and subfolders."""
        all_files: list[dict] = []

        # Get everything in this folder
        query = f"'{folder_id}' in parents and trashed=false"
        results = drive.files().list(
            q=query,
            fields="files(id, name, mimeType, createdTime)",
            orderBy="createdTime desc",
            pageSize=100,
        ).execute()

        for item in results.get("files", []):
            mime = item.get("mimeType", "")
            if mime == FOLDER_MIME:
                # Recurse into subfolder
                sub_files = self._list_files_recursive(drive, item["id"])
                all_files.extend(sub_files)
            elif mime in (GOOGLE_DOC_MIME, DOCX_MIME):
                all_files.append(item)

        return all_files

    def _extract_docx_text(self, drive, file_id: str) -> str:
        """Download and extract text from a .docx file."""
        try:
            from docx import Document
        except ImportError:
            # Fallback: download as plain text via Google Drive export
            logger.warning("python-docx not installed, trying Drive export")
            request = drive.files().export_media(
                fileId=file_id, mimeType="text/plain"
            )
            content = request.execute()
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return str(content)

        # Download .docx binary
        request = drive.files().get_media(fileId=file_id)
        file_bytes = request.execute()

        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

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
            files = self._list_files_recursive(drive, self.folder_id)
            logger.info("Found %d docs in Google Drive folder (recursive)", len(files))

            for file_info in files:
                gdoc_id = file_info["id"]
                mime = file_info.get("mimeType", "")

                if gdoc_id in existing_ids:
                    skipped += 1
                    continue

                try:
                    # Extract text based on file type
                    if mime == GOOGLE_DOC_MIME:
                        doc = docs.documents().get(documentId=gdoc_id).execute()
                        text = self._extract_text(doc)
                    elif mime == DOCX_MIME:
                        text = self._extract_docx_text(drive, gdoc_id)
                    else:
                        skipped += 1
                        continue

                    if not text.strip():
                        skipped += 1
                        continue

                    # Parse date from createdTime or filename
                    created = file_info["createdTime"][:10]
                    title = file_info["name"]
                    # Try to extract date from filename (Fireflies format)
                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", title)
                    if date_match:
                        created = date_match.group(1)

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
