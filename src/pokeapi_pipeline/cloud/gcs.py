import threading

from google.cloud import storage

from pokeapi_pipeline.util.config import Settings

# The storage client is not guaranteed to be thread-safe: give each worker thread its
# own client (for example with threading.local()).

class GCS:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._local = threading.local()

    def get_bucket(self) -> storage.Bucket:
        if not hasattr(self._local, "bucket"):
            client = storage.Client.from_service_account_json(
                str(self._settings.google_cloud_credentials)
            )

            self._local.bucket = client.bucket(self._settings.gcs_bucket)
        return self._local.bucket
