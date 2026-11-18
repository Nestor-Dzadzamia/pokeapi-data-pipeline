import logging
from time import monotonic

from pokeapi_pipeline.api.client import PokeAPIClient
from pokeapi_pipeline.cloud.gcs import GCS
from pokeapi_pipeline.db.database import Database
from pokeapi_pipeline.db.migrate import upgrade_to_head
from pokeapi_pipeline.pipeline.discover import Discoverer
from pokeapi_pipeline.pipeline.extract import Extractor
from pokeapi_pipeline.pipeline.load import Loader
from pokeapi_pipeline.pipeline.media import Media
from pokeapi_pipeline.pipeline.run_record import RunRecord
from pokeapi_pipeline.pipeline.transform import Transformer
from pokeapi_pipeline.util.config import Settings
from pokeapi_pipeline.util.log import setup_logging

logger = logging.getLogger("pokeapi_pipeline")


class PipelineRunner:
    """runs the whole pipeline once, recorded in pipeline_runs:

    Discover -> Extract + Media (at the same time) -> Transform -> Load
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    @staticmethod
    def _duration(seconds: float) -> str:
        minutes, seconds = divmod(seconds, 60)
        return f"{int(minutes)}m {seconds:.1f}s" if minutes else f"{seconds:.1f}s"

    def run(self) -> None:
        start_time = monotonic()

        settings = self._settings
        setup_logging(settings)
        upgrade_to_head()

        database = Database(settings)
        engine = database.get_engine()
        record = RunRecord(engine)
        run_id = record.start()
        logger.info(
            "run %d started: %d Pokémon, %d api workers, %d sprite workers",
            run_id, settings.pokemon_limit, settings.api_workers, settings.sprite_workers,
        )

        try:
            client = PokeAPIClient(settings)
            pokemon_ids = Discoverer(client, settings).pokemon_ids()

            with Media(client, GCS(settings), settings) as media:
                raw = Extractor(client, media, settings).run(pokemon_ids)
                logger.info("extract done, waiting for the sprites")
                sprite_results = media.results()

            summary = Media.summary(sprite_results)
            logger.info("extract: %s", client.stats())
            logger.info("media: %s", {key: value for key, value in summary.items() if key != "errors"})

            frames = Transformer(raw, settings.sprites_dir, sprite_results).run()
            logger.info("load: %s", Loader(engine, settings).run(frames))
        except Exception as error:
            logger.error("run %d failed after %s", run_id, self._duration(monotonic() - start_time))
            record.finish("failed", 0, 0, [repr(error)])
            raise
        else:
            status = "completed_with_errors" if summary["errors"] else "succeeded"
            record.finish(status, len(frames["pokemon"]), summary["uploaded"] + summary["skipped"], summary["errors"])
            logger.info("run %d finished: %s in %s", run_id, status, self._duration(monotonic() - start_time))
        finally:
            database.dispose()