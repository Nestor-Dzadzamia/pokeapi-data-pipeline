import argparse

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


def parse_overrides() -> dict:
    parser = argparse.ArgumentParser(description="Load Pokémon from PokéAPI into PostgreSQL and their sprites into GCS")
    parser.add_argument("--workers", type=int, help="worker threads (default: WORKERS from .env, else 8)")
    parser.add_argument("--limit", type=int, dest="pokemon_limit", help="how many Pokémon (default: POKEMON_LIMIT, else 50)")
    return {name: value for name, value in vars(parser.parse_args()).items() if value is not None}


def main() -> None:
    settings = Settings(**parse_overrides())
    upgrade_to_head()

    database = Database(settings)
    engine = database.get_engine()
    record = RunRecord(engine)
    run_id = record.start()
    print(f"run {run_id}: {settings.pokemon_limit} Pokémon, {settings.workers} workers")

    try:
        client = PokeAPIClient(settings)
        pokemon_ids = Discoverer(client, settings).pokemon_ids()
        raw = Extractor(client, settings).run(pokemon_ids)
        print(f"extract: {client.stats()}")
        frames = Transformer(raw).run()
        print(f"load: {Loader(engine, settings).run(frames)}")
        media = Media(engine, GCS(settings), settings).run()
        print(f"media: {media}")
    except Exception as error:
        record.finish("failed", 0, 0, [repr(error)])
        raise
    else:
        status = "completed_with_errors" if media["errors"] else "succeeded"
        record.finish(status, len(frames["pokemon"]), media["uploaded"] + media["skipped"], media["errors"])
        print(f"run {run_id}: {status}")
    finally:
        database.dispose()


if __name__ == "__main__":
    main()