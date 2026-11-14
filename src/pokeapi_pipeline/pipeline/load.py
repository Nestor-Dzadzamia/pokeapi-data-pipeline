import pandas as pd
from sqlalchemy import Connection, Engine, Table
from sqlalchemy.dialects.postgresql import insert


from pokeapi_pipeline.db.tables import metadata
from pokeapi_pipeline.util.config import Settings


class Loader:
    def __init__(self, engine: Engine, settings: Settings):
        self._engine = engine
        self._batch_size = settings.batch_size

    @staticmethod
    def _dataframe_to_dict_converter(frame: pd.DataFrame) -> list[dict]:
        return frame.astype(object).where(frame.notna(), None).to_dict(orient="records") # turns each pandas dataframe row into a dict

    @staticmethod
    def _loading_parents_species_first(species: pd.DataFrame) -> pd.DataFrame:
        parents_species = dict(zip(species["id"], species["evolves_from_species_id"]))

        def depth(species_id: int) -> int:
            specie_depth = 0
            while pd.notna(parents_species.get(species_id)):
                species_id = parents_species[species_id]
                specie_depth += 1
            return specie_depth

        return species.assign(depth=species["id"].map(depth)).sort_values(["depth", "id"]).drop(columns="depth") # return sorted frame by deepest species first


    def _upsert(self, connection: Connection, table: Table ,frame: pd.DataFrame) -> int:
        records = self._dataframe_to_dict_converter(frame)
        if not records:
            return 0

        keys = [column.name for column in table.primary_key.columns]
        statement = insert(table)

        changes = {name: statement.excluded[name] for name in frame.columns if name not in keys}
        if changes:
            statement = statement.on_conflict_do_update(index_elements=keys, set_=changes)
        else:
            statement = statement.on_conflict_do_nothing(index_elements=keys)

        for start in range(0, len(records), self._batch_size):
            connection.execute(statement, records[start:start+self._batch_size])

        return len(records)

    def load(self, connection: Connection, frames: dict[str, pd.DataFrame]) -> dict[str, int]:
        frames = {**frames, "species": self._loading_parents_species_first(frames["species"])}

        return {name: self._upsert(connection, metadata.tables[name], frame) for name, frame in frames.items()}

    def run(self, frames: dict[str, pd.DataFrame]) -> dict[str, int]:
        with self._engine.begin() as connection:
            return self.load(connection, frames)