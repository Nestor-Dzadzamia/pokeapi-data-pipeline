import pytest
from sqlalchemy import text

from pokeapi_pipeline.cloud.gcs import GCS
from pokeapi_pipeline.db.database import Database
from pokeapi_pipeline.util.config import Settings

pytestmark = pytest.mark.integration

@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings()

def test_database_connection(settings: Settings) -> None:
    engine = Database(settings).get_engine()
    try:
        with engine.connect() as connection:
            user, database = connection.execute(
                text("SELECT current_user, current_database()")
            ).one()
    finally:
        engine.dispose()

    assert user == settings.postgres_user
    assert database == settings.postgres_db


def test_bucket_round_trip(settings: Settings) -> None:
    bucket = GCS(settings).get_bucket()
    blob = bucket.blob("-random-text/tmp.txt")
    blob.upload_from_string(b"ok", content_type="text/plain")

    try:
        stored = bucket.get_blob(blob.name)
        assert stored is not None
        assert stored.size == 2
        assert stored.content_type == "text/plain"
    finally:
        blob.delete()