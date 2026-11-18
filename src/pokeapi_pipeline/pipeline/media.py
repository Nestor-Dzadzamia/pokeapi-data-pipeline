import base64
import hashlib
import logging
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import requests
from google.api_core.exceptions import GoogleAPIError

from pokeapi_pipeline.api.client import PokeAPIClient
from pokeapi_pipeline.cloud.gcs import GCS
from pokeapi_pipeline.pipeline.sprites import FORMATS, SpriteParser
from pokeapi_pipeline.util.config import Settings
from pokeapi_pipeline.util.errors import PipelineError, UnexpectedContentType, RateLimited

logger = logging.getLogger(__name__)

class Media:
    """
    downloads every sprite to disk and uploads it to GCS, both at the same time.
    extract hands over each pokemon as soon as its json arrives. Its sprite goes to the download pool,
    each finished download hands its file to the upload pool. so while some threads are still downloading, others
    are already uploading.

    extract threads - add() -> download pool - submit() -> upload pool -> result
    """

    def __init__(self, client: PokeAPIClient, gcs: GCS, settings: Settings):
        self._client = client
        self._bucket = gcs.get_bucket()
        self._gcs_bucket_name = settings.gcs_bucket
        self._sprites_dir = settings.sprites_dir
        self._threads = settings.sprite_workers
        self._lock = threading.Lock()
        self._downloads: list[Future] = []
        self._existing: dict[str, str] = {}
        self._parser = SpriteParser(settings.sprites_dir)


    def __enter__(self) -> "Media":
        blobs = self._bucket.list_blobs(fields="items(name, md5Hash), nextPageToken")
        self._existing = {blob.name: blob.md5_hash for blob in blobs}

        logger.info("bucket already has %d files", len(self._existing))

        self._download_pool = ThreadPoolExecutor(max_workers=self._threads, thread_name_prefix="download")
        self._upload_pool = ThreadPoolExecutor(max_workers=self._threads, thread_name_prefix="upload")
        return self


    def __exit__(self, *exec_info) -> None:
        self._download_pool.shutdown(wait=True, cancel_futures=exec_info[0] is not None)
        self._upload_pool.shutdown(wait=True, cancel_futures=exec_info[0] is not None)

    @staticmethod
    def _gcs_md5(data: bytes) -> str:
        return base64.b64encode(hashlib.md5(data).digest()).decode()

    def add(self, pokemon_dict: dict) -> None:
        futures = [self._download_pool.submit(self._download, file) for file in self._parser.sprite_files(pokemon_dict)]

        with self._lock:
            self._downloads.extend(futures)

    def _download(self, file: dict) -> Future | dict:
        """
        saves one file to disk, then hands it to the upload pool. returns the upload's future, or a failed result
        """
        target = Path(file["local_path"])


        if target.exists(): # earlier run downloaded it
            checksum = self._existing.get(file["object_name"])
            if checksum: # on disk and in GCS already
                return {
                    "pokemon_id": file["pokemon_id"],
                    "sprite_key": file["sprite_key"],
                    "status": "skipped",
                    "gcs_uri": f"gs://{self._gcs_bucket_name}/{file['object_name']}",
                    "size_bytes": target.stat().st_size,
                    "checksum": checksum,
                }
            return self._upload_pool.submit(self._upload, file)  # on disk and missing in GCS

        try:
            data, content_type = self._client.get_bytes(file["source_url"])
            if content_type != FORMATS[file["format"]][1]:
                raise UnexpectedContentType(f"{file['source_url']} is {content_type!r}")
        except (PipelineError, requests.RequestException) as error:
            return self._failed(file, "download", error)

        # a crash mid-write must not leave half a file: write a temp file, then rename it,
        # so the real file only appears once it is complete

        target.parent.mkdir(parents=True, exist_ok=True)
        temp_file = target.with_suffix(f".{threading.get_ident()}.tmp")
        temp_file.write_bytes(data)
        temp_file.replace(target)

        return self._upload_pool.submit(self._upload, file)


    def _upload(self, file: dict) -> dict:
        """
        uploads one file from disk unless the bucket already has the same bytes
        """

        data = Path(file["local_path"]).read_bytes()
        checksum = self._gcs_md5(data)

        if self._existing.get(file["object_name"]) == checksum:
            status = "skipped"
        else:
            try:
                self._bucket.blob(file["object_name"]).upload_from_string(data, content_type=FORMATS[file["format"]][1])
            except (GoogleAPIError, requests.RequestException) as error:
                return self._failed(file, "upload", error)
            status = "uploaded"

        return {
            "pokemon_id": file["pokemon_id"],
            "sprite_key": file["sprite_key"],
            "status": status,
            "gcs_uri": f"gs://{self._gcs_bucket_name}/{file['object_name']}",
            "size_bytes": len(data),
            "checksum": checksum,
        }

    @staticmethod
    def _failed(file: dict, step: str, error: Exception) -> dict:
        """one bad file must not stop the run: its error is returned and recorded in run_errors"""
        message = f"{step} {file['pokemon_id']} {file['sprite_key']}: {error!r}"
        logger.error("sprite failed: %s", message)
        return {
            "pokemon_id": file["pokemon_id"],
            "sprite_key": file["sprite_key"],
            "status": "failed",
            "error": message,
        }

    def results(self) -> list[dict]:
        """waits for every download and upload, call it after Extract has finished adding Pokémon"""
        results = []
        for download in self._downloads:
            outcome = download.result()
            results.append(outcome.result() if isinstance(outcome, Future) else outcome)
        return results

    @staticmethod
    def summary(results: list[dict]) -> dict:
        counts = Counter(result["status"] for result in results)
        return {
            "uploaded": counts["uploaded"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "errors": [result["error"] for result in results if result["status"] == "failed"],
        }