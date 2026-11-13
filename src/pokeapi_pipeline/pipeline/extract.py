import threading
from concurrent.futures import ThreadPoolExecutor

from pokeapi_pipeline.api.client import PokeAPIClient
from pokeapi_pipeline.util.config import Settings


class Extractor:
    def __init__(self, client: PokeAPIClient, settings: Settings):
        self._client = client
        self._workers = settings.workers
        self._settings = settings
        self._lock = threading.Lock()
        self._seen_set: set[tuple[str, int]] = set()
        self._raw: dict[str, dict[int, dict | list]] = {resource_kind: {} for resource_kind in settings.paths}


    def _can_claim(self, resource_kind: str, item_id: int) -> bool:
        with self._lock:
            if (resource_kind, item_id) in self._seen_set:
                return False
            self._seen_set.add((resource_kind, item_id))
            return True

    def _fetch(self, resource_kind: str, resource_id: int) -> dict | list | None:
        if not self._can_claim(resource_kind, resource_id):
            return None

        data = self._client.get(self._settings.paths[resource_kind].format(resource_id))
        with self._lock:
            self._raw[resource_kind][resource_id] = data
        return data

    def _extract_pokemon(self, pokemon_id: int) -> None:
        pokemon = self._fetch("pokemon", pokemon_id)
        self._fetch("encounters", pokemon_id)

        for entry in pokemon["types"]:
            self._fetch("types", self._client.id_from_url(entry["type"]["url"]))

        for entry in pokemon["abilities"]:
            self._fetch("abilities", self._client.id_from_url(entry["ability"]["url"]))

        self._extract_species(self._client.id_from_url(pokemon["species"]["url"]))

    def _extract_species(self, species_id: int) -> None:
        species = self._fetch("species", species_id)
        if species is not None:
            self._fetch("evolution_chains", self._client.id_from_url(species["evolution_chain"]["url"]))

    def _chain_species_ids(self) -> set[int]:
        species_ids = set()
        for chain in self._raw["evolution_chains"].values():
            nodes = [chain["chain"]]
            while nodes:
                node = nodes.pop()
                species_ids.add(self._client.id_from_url(node["species"]["url"]))
                nodes.extend(node["evolves_to"])
        return species_ids

    def run(self, pokemon_ids: list[int]) -> dict[str, dict[int, dict | list]]:
        with ThreadPoolExecutor(max_workers=self._settings.workers) as t_pool:
            list(t_pool.map(self._extract_pokemon, pokemon_ids))
            list(t_pool.map(self._extract_species, self._chain_species_ids()))

        return self._raw