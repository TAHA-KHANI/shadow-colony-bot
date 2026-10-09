from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    database_url: str = Field(alias="DATABASE_URL")
    group_id: int = Field(alias="GROUP_ID")
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")
    game_secret: str = Field(alias="GAME_SECRET", min_length=16)
    backup_secret: str = Field(alias="BACKUP_SECRET", min_length=16)
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo("Asia/Tehran")

    @property
    def admin_ids(self) -> tuple[int, ...]:
        return tuple(int(part.strip()) for part in self.admin_ids_raw.split(",") if part.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

