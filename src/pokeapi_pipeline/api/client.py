import json
import threading
from pathlib import Path
from time import sleep

import requests

from pokeapi_pipeline.util.config import Settings

class PokeAPIClient:
    """fetches json from pokeapi, one client is shared by all worker threads"""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.api_base_url
        self._timeout = settings.http_timeout
        self._max_retries = settings.max_retries
        self._cache_dir = settings.cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._requests = 0
        self._cache_hits = 0

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _cache_file(self, url: str) -> Path:
        name = url.removeprefix(self._base_url).strip("/")
        for character in "/?&":
            name = name.replace(character, "_")
        return self._cache_dir / f"{name}.json"

    def _download(self, url: str) -> dict | list:
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            if attempt:
                sleep(0.5 * 2 ** (attempt - 1)) # only in second+ attempts make thread wait
            try:
                response = self._session().get(
                    url,
                    timeout=self._timeout
                )
            except (requests.ConnectionError, requests.Timeout) as error:
                last_error = error
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = requests.HTTPError(f"{response.status_code} from {url}")
                continue

            response.raise_for_status()
            return response.json()
        raise last_error

    def get(self, path: str) -> dict | list:
        url = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"
        cache_file = self._cache_file(url)

        if cache_file.exists():
            with self._lock:
                self._cache_hits += 1
            return json.loads(cache_file.read_text())

        data = self._download(url)
        with self._lock:
            self._requests += 1


        # here I renamed cache file, for each thread it becomes cache_file.unique_thread_identifier_number.tmp
        # so other threads can't read or access the file when current thread is writing it.
        # in this case we write it as unique name and then rename it.
        temp_file = cache_file.with_suffix(f".{threading.get_ident()}.tmp")
        temp_file.write_text(json.dumps(data))
        temp_file.replace(cache_file)
        return data

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"requests": self._requests, "cache_hits": self._cache_hits}

    @staticmethod
    def id_from_url(url: str) -> int:
        return int(url.rstrip("/").split("/")[-1])