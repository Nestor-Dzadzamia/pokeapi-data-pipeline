from datetime import datetime, timezone

from sqlalchemy import Engine, insert, update

from pokeapi_pipeline.db.tables import pipeline_runs, run_errors


class RunRecord:
    def __init__(self, engine: Engine):
        self._engine = engine
        self._run_id: int | None = None

    def start(self) -> int:
        statement = (
            insert(pipeline_runs)
            .values(started_at=datetime.now(timezone.utc), status="running", pokemon_count=0, sprite_count=0)
            .returning(pipeline_runs.c.id)
        )

        with self._engine.begin() as connection:
            self._run_id = connection.execute(statement).scalar_one()

        return self._run_id

    def finish(self, status: str, pokemon_count: int, sprite_count: int, errors: list[str]) -> None:
        with self._engine.begin() as connection:
            if errors:
                connection.execute(
                    insert(run_errors),
                    [{"run_id": self._run_id, "message": message} for message in errors]
                )

            connection.execute(
                update(pipeline_runs)
                .where(pipeline_runs.c.id == self._run_id)
                .values(
                    finished_at=datetime.now(timezone.utc),
                    status=status,
                    pokemon_count=pokemon_count,
                    sprite_count=sprite_count,
                )
            )