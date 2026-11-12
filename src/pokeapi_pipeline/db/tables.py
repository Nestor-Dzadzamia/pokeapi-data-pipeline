from sqlalchemy import MetaData, Boolean, Column, DateTime, ForeignKey, Identity, Integer, Table, Text

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(column_0_label)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

generations = Table(
    "generations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
)

habitats = Table(
    "habitats",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
)

evolution_chains = Table(
    "evolution_chains",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
)

types = Table(
    "types",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
)

abilities = Table(
    "abilities",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
    Column("short_effect", Text),
)

stats = Table(
    "stats",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
)

location_areas = Table(
    "location_areas",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
)

versions = Table(
    "versions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
)


species = Table(
    "species",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
    Column("is_legendary", Boolean, nullable=False),
    Column("is_mythical", Boolean, nullable=False),
    Column("is_baby", Boolean, nullable=False),
    Column("generation_id", ForeignKey("generations.id"), nullable=False),
    Column("habitat_id", ForeignKey("habitats.id")),
    Column("evolution_chain_id", ForeignKey("evolution_chains.id"), nullable=False),
    Column("evolves_from_species_id", ForeignKey("species.id")),
)

pokemon = Table(
    "pokemon",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
    Column("height", Integer, nullable=False),
    Column("weight", Integer, nullable=False),
    Column("base_experience", Integer, nullable=False),
    Column("is_default", Boolean, nullable=False),
    Column("species_id", ForeignKey("species.id"), nullable=False),
)

pokemon_types = Table(
    "pokemon_types",
    metadata,
    Column("pokemon_id", ForeignKey("pokemon.id"), primary_key=True),
    Column("type_id", ForeignKey("types.id"), primary_key=True),
    Column("slot", Integer, nullable=False),
)

pokemon_abilities = Table(
    "pokemon_abilities",
    metadata,
    Column("pokemon_id", ForeignKey("pokemon.id"), primary_key=True),
    Column("ability_id", ForeignKey("abilities.id"), primary_key=True),
    Column("slot", Integer, nullable=False),
    Column("is_hidden", Boolean, nullable=False),
)

pokemon_stats = Table(
    "pokemon_stats",
    metadata,
    Column("pokemon_id", ForeignKey("pokemon.id"), primary_key=True),
    Column("stat_id", ForeignKey("stats.id"), primary_key=True),
    Column("base_stat", Integer, nullable=False),
    Column("effort", Integer, nullable=False),
)

encounters = Table(
    "encounters",
    metadata,
    Column("pokemon_id", ForeignKey("pokemon.id"), primary_key=True),
    Column("location_area_id", ForeignKey("location_areas.id"), primary_key=True),
    Column("version_id", ForeignKey("versions.id"), primary_key=True),
    Column("max_chance", Integer, nullable=False),
)


sprites = Table(
    "sprites",
    metadata,
    Column("pokemon_id", ForeignKey("pokemon.id"), primary_key=True),
    Column("format", Text, primary_key=True),
    Column("source_url", Text),
    Column("gcs_uri", Text),
    Column("size_bytes", Integer),
    Column("checksum", Text),
)

pipeline_runs = Table(
    "pipeline_runs",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", Text, nullable=False),
    Column("pokemon_count", Integer, nullable=False),
    Column("sprite_count", Integer, nullable=False),
)

run_errors = Table(
    "run_errors",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("run_id", ForeignKey("pipeline_runs.id"), nullable=False),
    Column("message", Text, nullable=False),
)