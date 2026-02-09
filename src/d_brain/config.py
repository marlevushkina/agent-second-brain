"""Application configuration using Pydantic Settings."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(description="Telegram Bot API token")
    deepgram_api_key: str = Field(description="Deepgram API key for transcription")
    ticktick_client_id: str = Field(default="", description="TickTick OAuth Client ID")
    ticktick_client_secret: str = Field(default="", description="TickTick OAuth Client Secret")
    ticktick_access_token: str = Field(default="", description="TickTick OAuth Access Token")
    google_docs_folder_id: str = Field(
        default="",
        description="Google Drive folder ID with Fireflies transcripts",
    )
    google_credentials_path: Path = Field(
        default=Path(""),
        description="Path to Google service account JSON key",
    )
    vault_path: Path = Field(
        default=Path("./vault"),
        description="Path to Obsidian vault directory",
    )
    allowed_user_ids: list[int] = Field(
        default_factory=list,
        description="List of Telegram user IDs allowed to use the bot",
    )
    allow_all_users: bool = Field(
        default=False,
        description="Whether to allow access to all users (security risk!)",
    )
    telegram_api_id: int = Field(
        default=0,
        description="Telegram API ID from my.telegram.org (for channel reading)",
    )
    telegram_api_hash: str = Field(
        default="",
        description="Telegram API Hash from my.telegram.org (for channel reading)",
    )
    telegram_channel: str = Field(
        default="",
        description="Telegram channel username to read posts from (e.g. letsboss)",
    )

    @property
    def daily_path(self) -> Path:
        """Path to daily notes directory."""
        return self.vault_path / "daily"

    @property
    def attachments_path(self) -> Path:
        """Path to attachments directory."""
        return self.vault_path / "attachments"

    @property
    def thoughts_path(self) -> Path:
        """Path to thoughts directory."""
        return self.vault_path / "thoughts"

    @property
    def content_path(self) -> Path:
        """Path to content directory."""
        return self.vault_path / "content"


def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
