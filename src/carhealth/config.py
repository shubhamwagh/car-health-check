from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    zyfy_api_key: str | None = None
    mot_client_id: str | None = None
    mot_client_secret: str | None = None
    mot_api_key: str | None = None
    mot_token_url: str | None = None
    mot_scope_url: str | None = None

    # Self-hosted ntfy - low-quota warning for the Zyfy free tier. All optional;
    # notify.send() just logs and skips the push if any of the three are unset.
    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
