from pathlib import Path
from typing import Literal

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

    pokemon_limit: int = Field(default=1351, ge=1)
    api_workers: int = Field(default=64, ge=1, le=128)
    sprite_workers: int = Field(default=64, ge=1, le=128)
    api_base_url: str = "https://pokeapi.co/api/v2"
    http_timeout: int = Field(default=10, gt=0)
    max_retries: int = Field(default=3, ge=0)

    batch_size: int = Field(default=500, ge=1)

    sprites_dir: Path = ROOT / "data" / "sprites"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: Path = ROOT / "logs" / "pipeline.log"

    paths: dict[str, str] = {
        "pokemon": "pokemon/{}",
        "encounters": "pokemon/{}/encounters",
        "species": "pokemon-species/{}",
        "evolution_chains": "evolution-chain/{}",
        "types": "type/{}",
        "abilities": "ability/{}",
    }

    rate_limit_pause: int = Field(default=30, ge=1)
    rate_limit_max_pauses:int = Field(default=0, ge=0)