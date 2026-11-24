from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import secrets
from pathlib import Path

class Settings(BaseSettings):
    app_secret_key: str = "unsafe-development-key-change-me"
    database_url: str = "sqlite:///./data/autonomiq.db"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    allow_self_registration: bool = True
    require_invite_code: bool = True
    bas_adapter: str = "simulated"
    bacnet_local_ip: str = ""
    bacnet_subnet_mask: int = 24
    upload_max_mb: int = 30
    cors_origins: str = "*"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

def ensure_secret():
    env_path = Path(".env")
    settings = Settings()
    if settings.app_secret_key == "unsafe-development-key-change-me" or settings.app_secret_key.startswith("REPLACE"):
        new_secret = secrets.token_urlsafe(48)
        lines = []
        if env_path.exists():
            lines = env_path.read_text().splitlines()
            updated = False
            for i, line in enumerate(lines):
                if line.startswith("APP_SECRET_KEY="):
                    lines[i] = f"APP_SECRET_KEY={new_secret}"
                    updated = True
            if not updated:
                lines.append(f"APP_SECRET_KEY={new_secret}")
        else:
            lines = [f"APP_SECRET_KEY={new_secret}", "DATABASE_URL=sqlite:///./data/autonomiq.db"]
        env_path.write_text("\n".join(lines) + "\n")
        get_settings.cache_clear()
    return get_settings()

@lru_cache
def get_settings():
    return Settings()
