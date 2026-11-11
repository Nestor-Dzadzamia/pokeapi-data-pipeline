from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, FilePath, SecretStr

ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    db_host: str = "localhost"
    db_host_port: int = Field(default=5433, ge=1, le=65535)

    google_cloud_credentials: FilePath
    gcs_bucket: str

    pokemon_limit: int = Field(default=50, ge=1)
    workers: int = Field(default=8, ge=1, le=16)
    api_base_url: str = "https://pokeapi.co/api/v2"
    cache_dir: Path = ROOT / "data" / "cache"
    http_timeout: int = Field(default=10, gt=0)
    max_retries: int = Field(default=3, ge=0)