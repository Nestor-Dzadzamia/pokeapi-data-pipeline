from sqlalchemy import URL, Engine, create_engine

from pokeapi_pipeline.util.config import Settings

class Database:
    def __init__(self, settings: Settings):
        url = URL.create(
            drivername="postgresql+psycopg2",
            username=settings.postgres_user,
            password=settings.postgres_password.get_secret_value(),
            host=settings.db_host,
            port=settings.db_host_port,
            database=settings.postgres_db,
        )

        self._engine = create_engine(
            url,
            pool_size=settings.workers,
            max_overflow=2,
            pool_pre_ping=True,
        )

    def get_engine(self) -> Engine:
        return self._engine

    def dispose(self) -> None:
        self._engine.dispose()
