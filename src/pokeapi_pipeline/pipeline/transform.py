import pandas as pd

from pokeapi_pipeline.api.client import PokeAPIClient


class Transformer:
    def __init__(self, raw: dict[str, dict[int, dict | list]]):
        self._pokemon = list(raw["pokemon"].values())
        self._species = list(raw["species"].values())
        self._chains = list(raw["evolution_chains"].values())
        self._types = list(raw["types"].values())
        self._abilities = list(raw["abilities"].values())
        self._encounters = raw["encounters"]

    @staticmethod
    def _ref_id(reference: dict | None) -> int | None:
        return PokeAPIClient.id_from_url(reference["url"]) if reference else None

    @staticmethod
    def _lookup(references: list[dict | None]) -> pd.DataFrame:
        rows = [{"id": Transformer._ref_id(ref), "name": ref["name"]} for ref in references if ref]
        frame = pd.DataFrame(rows, columns=["id", "name"])
        return frame.drop_duplicates("id").sort_values("id").reset_index(drop=True)

    def _nested(self, list_name: str) -> pd.DataFrame:
        frame = pd.json_normalize(self._pokemon, record_path=list_name, meta=["id"])
        return frame.rename(columns={"id": "pokemon_id"})

    def _evolutions(self) -> pd.DataFrame:
        rows = []
        for chain in self._chains:
            nodes = [chain["chain"]]
            while nodes:
                node = nodes.pop()
                nodes.extend(node["evolves_to"])
                if node["evolution_details"]:
                    detail = node["evolution_details"][0]
                    rows.append({
                        "id": self._ref_id(node["species"]),
                        "evolution_trigger_id": self._ref_id(detail["trigger"]),
                        "trigger_name": detail["trigger"]["name"],
                        "min_level": detail["min_level"],
                    })
        return pd.DataFrame(rows, columns=["id", "evolution_trigger_id", "trigger_name", "min_level"])

    def _species_frame(self, evolutions: pd.DataFrame) -> pd.DataFrame:
        frame = pd.DataFrame([{
            "id": species["id"],
            "name": species["name"],
            "is_legendary": species["is_legendary"],
            "is_mythical": species["is_mythical"],
            "is_baby": species["is_baby"],
            "generation_id": self._ref_id(species["generation"]),
            "habitat_id": self._ref_id(species["habitat"]),
            "evolution_chain_id": self._ref_id(species["evolution_chain"]),
            "evolves_from_species_id": self._ref_id(species["evolves_from_species"]),
        } for species in self._species])
        frame = frame.merge(evolutions.drop(columns="trigger_name"), on="id", how="left")
        nullable = ["habitat_id", "evolves_from_species_id", "evolution_trigger_id", "min_level"]
        frame[nullable] = frame[nullable].astype("Int64")
        return frame.sort_values("id").reset_index(drop=True)

    def _pokemon_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame([{
            "id": pokemon["id"],
            "name": pokemon["name"],
            "height": pokemon["height"],
            "weight": pokemon["weight"],
            "base_experience": pokemon["base_experience"],
            "is_default": pokemon["is_default"],
            "species_id": self._ref_id(pokemon["species"]),
        } for pokemon in self._pokemon])
        return frame.sort_values("id").reset_index(drop=True)

    def _abilities_frame(self) -> pd.DataFrame:
        frame = pd.DataFrame([{
            "id": ability["id"],
            "name": ability["name"],
            "short_effect": next(
                (entry["short_effect"] for entry in ability["effect_entries"] if entry["language"]["name"] == "en"),
                None,
            ),
        } for ability in self._abilities])
        return frame.sort_values("id").reset_index(drop=True)

    def _link(self, list_name: str, reference: str, id_column: str, value_columns: list[str]) -> pd.DataFrame:
        frame = self._nested(list_name)
        frame[id_column] = frame[f"{reference}.url"].map(PokeAPIClient.id_from_url)
        frame = frame[["pokemon_id", id_column, *value_columns]]
        return frame.drop_duplicates(["pokemon_id", id_column]).reset_index(drop=True)

    def _encounters_frame(self) -> pd.DataFrame:
        records = [
            {"pokemon_id": pokemon_id, **area}
            for pokemon_id, areas in self._encounters.items()
            for area in areas
        ]
        frame = pd.json_normalize(
            records,
            record_path="version_details",
            meta=["pokemon_id", ["location_area", "name"], ["location_area", "url"]],
        )
        frame["location_area_id"] = frame["location_area.url"].map(PokeAPIClient.id_from_url)
        frame["version_id"] = frame["version.url"].map(PokeAPIClient.id_from_url)
        frame["pokemon_id"] = frame["pokemon_id"].astype(int)
        return frame.drop_duplicates(["pokemon_id", "location_area_id", "version_id"]).reset_index(drop=True)

    def _sprites_frame(self) -> pd.DataFrame:
        rows = []
        for pokemon in self._pokemon:
            sprites = pokemon["sprites"]
            rows.append({"pokemon_id": pokemon["id"], "format": "png", "source_url": sprites["front_default"]})
            rows.append({
                "pokemon_id": pokemon["id"],
                "format": "gif",
                "source_url": sprites["other"]["showdown"]["front_default"],
            })
        return pd.DataFrame(rows, columns=["pokemon_id", "format", "source_url"])

    def run(self) -> dict[str, pd.DataFrame]:
        evolutions = self._evolutions()
        encounters = self._encounters_frame()
        areas = [area for areas in self._encounters.values() for area in areas]

        return {
            "generations": self._lookup([species["generation"] for species in self._species]),
            "habitats": self._lookup([species["habitat"] for species in self._species]),
            "evolution_chains": pd.DataFrame({"id": sorted(chain["id"] for chain in self._chains)}),
            "evolution_triggers": evolutions[["evolution_trigger_id", "trigger_name"]]
            .rename(columns={"evolution_trigger_id": "id", "trigger_name": "name"})
            .drop_duplicates("id")
            .sort_values("id")
            .reset_index(drop=True),
            "types": pd.DataFrame([{"id": item["id"], "name": item["name"]} for item in self._types])
            .sort_values("id")
            .reset_index(drop=True),
            "abilities": self._abilities_frame(),
            "stats": self._lookup([entry["stat"] for pokemon in self._pokemon for entry in pokemon["stats"]]),
            "location_areas": self._lookup([area["location_area"] for area in areas]),
            "versions": self._lookup([detail["version"] for area in areas for detail in area["version_details"]]),
            "species": self._species_frame(evolutions),
            "pokemon": self._pokemon_frame(),
            "pokemon_types": self._link("types", "type", "type_id", ["slot"]),
            "pokemon_abilities": self._link("abilities", "ability", "ability_id", ["slot", "is_hidden"]),
            "pokemon_stats": self._link("stats", "stat", "stat_id", ["base_stat", "effort"]),
            "encounters": encounters[["pokemon_id", "location_area_id", "version_id", "max_chance"]],
            "sprites": self._sprites_frame(),
        }