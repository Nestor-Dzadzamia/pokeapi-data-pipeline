import logging
import threading
from time import sleep, monotonic
from urllib.parse import urlsplit

import requests

from pokeapi_pipeline.util.errors import RetryableError, RateLimited
from pokeapi_pipeline.util.config import Settings

logger = logging.getLogger(__name__)


class PokeAPIClient:
    """fetches json from pokeapi, one client is shared by all worker threads"""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.api_base_url
        self._timeout = settings.http_timeout
        self._max_retries = settings.max_retries
        self._local = threading.local()
        self._lock = threading.Lock()
        self._requests = 0
        self._sprite_downloads = 0


        self._rate_limited: set[str] = set() # hosts that answered 429
        self._paused_until: dict[str, float] = {} # host : time when requests may go again
        self._pauses: dict[str, int] = {}
        self._pause_seconds = settings.rate_limit_pause
        self._max_pauses = settings.rate_limit_max_pauses

    def _wait_for(self, host: str, url: str) -> None:
        """every thread waits when rate limited on that host"""
        while True:
            with self._lock:
                if host in self._rate_limited:
                    raise RateLimited(f"{host} is rate limiting this run, skipped {url}")
                wait = self._paused_until.get(host, 0) - monotonic()
            if wait <= 0:
                return
            sleep(wait)

    def _pause(self, host: str, url: str) -> None:
        """a 429: pause every request to this host, twice as long as last time. give up after max_pauses"""
        with self._lock:
            if host in self._rate_limited or monotonic() < self._paused_until.get(host, 0):
                return  # already given up, or another thread already paused the host for this wave of 429s
            pauses = self._pauses.get(host, 0) + 1
            if pauses > self._max_pauses:
                self._rate_limited.add(host)
                logger.error("%s still answers 429 after %d pauses, giving up on it for this run", host, self._max_pauses)
                return
            self._pauses[host] = pauses
            seconds = self._pause_seconds * 2 ** (pauses - 1)
            self._paused_until[host] = monotonic() + seconds
        logger.warning("429 from %s: every request to %s waits %ss (pause %d/%d)", url, host, seconds, pauses, self._max_pauses)

    def _session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _request(self, url: str, params: dict | None = None) -> requests.Response:
        host = urlsplit(url).hostname
        last_error: RetryableError | None = None
        attempt = 0

        while attempt <= self._max_retries:
            self._wait_for(
                host, url
            )  # sleeps while the host is paused, raises RateLimited once we gave up
            if attempt:
                logger.warning(
                    "retry %d/%d for %s after %r",
                    attempt,
                    self._max_retries,
                    url,
                    last_error,
                )
                sleep(0.5 * 2 ** (attempt - 1))
            try:
                response = self._session().get(
                    url, params=params, timeout=self._timeout
                )
            except (requests.ConnectionError, requests.Timeout) as error:
                last_error = RetryableError(f"{url}: {error!r}")
                attempt += 1
                continue

            if response.status_code == 429:
                self._pause(
                    host, url
                )  # not a used retry: the same url goes again after the pause
                continue
            if response.status_code >= 500:
                last_error = RetryableError(f"{response.status_code} from {url}")
                attempt += 1
                continue

            response.raise_for_status()
            return response
        raise last_error

    def get(self, path: str, params: dict | None = None) -> dict | list:
        data = self._request(f"{self._base_url}/{path}", params).json()

        with self._lock:
            self._requests += 1

        return data

    def get_bytes(self, url: str) -> tuple[bytes, str]:
        """a sprite file and its content type, for example (b"...", "image/png")"""
        response = self._request(url)
        with self._lock:
            self._sprite_downloads += 1
        return response.content, response.headers.get("Content-Type", "").split(";")[0].strip()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"requests": self._requests, "sprite_downloads": self._sprite_downloads}

    @staticmethod
    def id_from_url(url: str) -> int:
        return int(url.rstrip("/").split("/")[-1])