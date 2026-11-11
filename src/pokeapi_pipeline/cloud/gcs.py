import threading

from google.cloud import storage

from pokeapi_pipeline.util.config import Settings

# The storage client is not guaranteed to be thread-safe: give each worker thread its
# own client (for example with threading.local()).
_local = threading.local()

def get_bucket(settings: Settings) -> storage.Bucket:
    if not hasattr(_local, "bucket"):
        client = storage.Client.from_service_account_json(
            str(settings.google_cloud_credentials)
        )

        _local.bucket = client.bucket(settings.gcs_bucket)
    return _local.bucket

