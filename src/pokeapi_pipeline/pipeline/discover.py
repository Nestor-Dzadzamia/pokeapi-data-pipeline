import logging

from pokeapi_pipeline.api.client import PokeAPIClient
from pokeapi_pipeline.util.config import Settings

logger = logging.getLogger(__name__)


class Discoverer:
    def __init__(self, client: PokeAPIClient, settings: Settings):
        self._client = client
        self._limit = settings.pokemon_limit

    def pokemon_ids(self) -> list[int]:
        pokemon_list = self._client.get(f"pokemon?limit={self._limit}&offset=0")
        pokemon_ids = [self._client.id_from_url(item["url"]) for item in pokemon_list["results"]]
        logger.info("discovered %d Pokémon ids", len(pokemon_ids))
        return pokemon_ids