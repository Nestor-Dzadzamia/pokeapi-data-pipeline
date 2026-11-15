import base64
import hashlib
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from typing import Callable

import requests
from sqlalchemy import Connection, Engine, bindparam, select, update

from pokeapi_pipeline.cloud.gcs import GCS
from pokeapi_pipeline.db.tables import sprites, pokemon
from pokeapi_pipeline.util.config import Settings

class Media:
    def __init__(self, engine: Engine, gcs: GCS, settings: Settings):
        self._engine = engine
        self._gcs = gcs
        self._gcs_bucket_name = settings.gcs_bucket
        self._workers = settings.workers
        self._timeout = settings.http_timeout
        self._max_retries = settings.max_retries
        self._folders = settings.folders
        self._local = threading.local()

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _call_action_with_retries(self, action: Callable):
        last_error: Exception | None = None
        for attempt in range(0, self._max_retries + 1):
            if attempt:
                sleep(0.5 * 2 ** (attempt - 1))
            try:
                return action()
            except Exception as error:
                last_error = error
        raise last_error

    def _join_sprites_and_pokemon(self) -> list[dict]:
        query = (
            select(
                sprites.c.pokemon_id,
                sprites.c.format,
                sprites.c.source_url,
                pokemon.c.name,
            )
            .join(pokemon, pokemon.c.id == sprites.c.pokemon_id)
            .order_by(sprites.c.pokemon_id, sprites.c.format)
        )

        with self._engine.connect() as connection:
            return [dict(row) for row in connection.execute(query).mappings()]

    def _download(self, url: str) -> tuple[bytes, str]:
        response = self._session().get(url, timeout=self._timeout)
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()

        return response.content, content_type


    def _object_name(self,pokemon_sprite_table: dict, content_type: str) -> str:
        folder, extension = self._folders[content_type]

        return f"{folder}/{pokemon_sprite_table['pokemon_id']}_{pokemon_sprite_table['name']}.{extension}"

    def _upload_single_object(self, object_name: str, data: bytes, content_type: str, checksum: str) -> bool:
        bucket = self._gcs.get_bucket()
        existing = bucket.get_blob(object_name)

        if existing is not None and existing.md5_hash == checksum:
            return False

        bucket.blob(object_name).upload_from_string(data, content_type=content_type)
        return True

    def _upload(self, joined_sprites_and_pokemon: dict) -> dict:
        result = {"pokemon_id": joined_sprites_and_pokemon["pokemon_id"], "format": joined_sprites_and_pokemon["format"]}

        if joined_sprites_and_pokemon["source_url"] is None:
            return {**result, "status": "missing"}

        try:
            data, content_type = self._call_action_with_retries(
                lambda: self._download(joined_sprites_and_pokemon["source_url"])
            )

            if content_type not in self._folders:
                raise ValueError(f"unexpected content type: {content_type!r}")

            object_name = self._object_name(joined_sprites_and_pokemon, content_type)
            checksum = base64.b64encode(hashlib.md5(data).digest()).decode()
            uploaded = self._call_action_with_retries(
                lambda: self._upload_single_object(object_name, data, content_type, checksum)
            )
        except Exception as error:
            return {
                **result,
                "status": "failed",
                "error": f"{joined_sprites_and_pokemon['name']} {joined_sprites_and_pokemon['format']}: {error!r}",
            }

        return {
            **result,
            "status": "uploaded" if uploaded else "skipped",
            "gcs_uri": f"gs://{self._gcs_bucket_name}/{object_name}",
            "size_bytes": len(data),
            "checksum": checksum
        }

    @staticmethod
    def _save(connection: Connection, results: list[dict]) -> None:
        stored = [
            result for result in results if result["status"] in ("uploaded", "skipped")
        ]
        if not stored:
            return

        statement = (
            update(sprites)
            .where(sprites.c.pokemon_id == bindparam("b_pokemon_id"))
            .where(sprites.c.format == bindparam("b_format"))
            .values(
                gcs_uri=bindparam("b_gcs_uri"),
                size_bytes=bindparam("b_size_bytes"),
                checksum=bindparam("b_checksum"),
            )
        )
        connection.execute(
            statement,
            [
                {
                    "b_pokemon_id": result["pokemon_id"],
                    "b_format": result["format"],
                    "b_gcs_uri": result["gcs_uri"],
                    "b_size_bytes": result["size_bytes"],
                    "b_checksum": result["checksum"],
                }
                for result in stored
            ],
        )

    def run(self) -> dict:
        joined_sprites_and_pokemon = self._join_sprites_and_pokemon()

        with ThreadPoolExecutor(max_workers=self._workers) as t_pool:
            results = list(t_pool.map(self._upload, joined_sprites_and_pokemon))

        with self._engine.begin() as connection:
            self._save(connection, results)

        counts = Counter(result["status"] for result in results)

        return {
            "uploaded": counts["uploaded"],
            "skipped": counts["skipped"],
            "missing": counts["missing"],
            "failed": counts["failed"],
            "errors": [result["error"] for result in results if result["status"] == "failed"]
        }
