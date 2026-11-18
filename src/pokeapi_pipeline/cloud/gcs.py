import requests
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage
from google.oauth2 import service_account

from pokeapi_pipeline.util.config import Settings

class GCS:
    """
    one storage client shared by all upload threads
    """

    def __init__(self, settings: Settings):
        credentials = service_account.Credentials.from_service_account_file(
            str(settings.google_cloud_credentials), scopes=storage.Client.SCOPE
        )
        session = AuthorizedSession(credentials)
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=settings.sprite_workers,
            pool_maxsize=settings.sprite_workers,
        )
        session.mount("https://", adapter)

        client = storage.Client(
            project=credentials.project_id, credentials=credentials, _http=session
        )
        self._bucket = client.bucket(settings.gcs_bucket)

    def get_bucket(self) -> storage.Bucket:
        return self._bucket
