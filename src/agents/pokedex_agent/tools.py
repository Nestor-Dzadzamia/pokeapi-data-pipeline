import re
from functools import cache

from sqlalchemy import Engine, text

from pokeapi_pipeline.db.database import Database
from pokeapi_pipeline.util.config import Settings

MAX_VERSIONS = 6
SPRITE_KEYS = {"png": "front_default", "gif": "other/showdown/front_default"}

@cache
def _engine() -> Engine:
    return Database(Settings()).get_engine()


def _rows(sql: str, **params) -> list[dict]:
    with _engine().connect() as connection:
        return [dict(row) for row in connection.execute(text(sql), params).mappings()]

def normalize_name(name: str) -> str:
    cleaned = name.strip().lower().replace("♀", "-f").replace("♂", "-m")
    cleaned = re.sub(r"[.'’:]", "", cleaned)
    cleaned = re.sub(r"[\s_]+", "-", cleaned)
    return re.sub(r"-+", "-", cleaned).strip("-")

def _not_found(name: str) -> dict:
    return {"found": False, "message": f"{name} is not in the loaded data."}

def _pokemon(name: str) -> dict | None:
    rows = _rows(
        """
        select p.id, p.name, p.height, p.weight
        from pokemon p
        join species s on s.id = p.species_id
        where p.name = :name or (s.name = :name and p.is_default)
        """,
        name=normalize_name(name),
    )

    return rows[0] if rows else None

def _species(name: str) -> dict | None:
    rows = _rows(
        """
        select s.id, s.name, s.evolution_chain_id
        from species s
        where s.name = :name or s.id = (select species_id from pokemon where name = :name)
        """,
        name=normalize_name(name),
    )

    return rows[0] if rows else None

def get_pokemon_profile(name: str) -> dict:
    """Get a Pokémon's types, abilities, base stats, height and weight.

    Args:
        name: the Pokémon's name in any spelling or case, for example "Charizard" or "Mr. Mime".

    Returns:
        found=False when the Pokémon is not in the loaded data. Otherwise its types in slot order,
        its abilities (hidden=True marks the hidden ability), its base stats, height in metres and weight in kilograms.
    """

    pokemon = _pokemon(name)
    if pokemon is None:
        return _not_found(name)

    types = _rows(
        """
        select t.name from pokemon_types pt join types t on t.id = pt.type_id
        where pt.pokemon_id = :id order by pt.slot
        """,
        id=pokemon["id"],
    )
    abilities = _rows(
        """
        select a.name, pa.is_hidden from pokemon_abilities pa join abilities a on a.id = pa.ability_id
        where pa.pokemon_id = :id order by pa.slot
        """,
        id=pokemon["id"],
    )
    stats = _rows(
        """
        select s.name, ps.base_stat from pokemon_stats ps join stats s on s.id = ps.stat_id
        where ps.pokemon_id = :id order by s.id
        """,
        id=pokemon["id"],
    )

    return {
        "found": True,
        "name": pokemon["name"],
        "types": [row["name"] for row in types],
        "abilities": [{"name": row["name"], "hidden": row["is_hidden"]} for row in abilities],
        "base_stats": {row["name"]: row["base_stat"] for row in stats},
        "height_m": pokemon["height"] / 10,
        "weight_kg": pokemon["weight"] / 10,
    }

def get_pokemon_habitat(name: str) -> dict:
    """Get the habitat, generation and legendary/mythical flags of a Pokémon species.

    Args:
        name: the Pokémon's name in any spelling or case, for example "Pikachu".

    Returns:
        found=False when the species is not in the loaded data. Otherwise its habitat, generation,
        is_legendary and is_mythical.
    """
    rows = _rows(
        """
        select s.name, h.name as habitat, g.name as generation, s.is_legendary, s.is_mythical
        from species s
        join generations g on g.id = s.generation_id
        left join habitats h on h.id = s.habitat_id
        where s.name = :name or s.id = (select species_id from pokemon where name = :name)
        """,
        name=normalize_name(name),
    )
    if not rows:
        return _not_found(name)
    return {"found": True, **rows[0]}


def get_pokemon_locations(name: str, version: str | None = None) -> dict:
    """Get the location areas where a Pokémon can be caught, grouped by game version.

    Args:
        name: the Pokémon's name in any spelling or case, for example "Pikachu".
        version: optional game version such as "red", "blue" or "yellow". Leave it out to list all versions.

    Returns:
        found=False when the Pokémon is not in the loaded data. Otherwise locations as
        {version: [location areas]}. Without a version only the first versions are listed;
        other_versions names the rest, and calling again with one of them returns its areas.
    """
    pokemon = _pokemon(name)
    if pokemon is None:
        return _not_found(name)

    rows = _rows(
        """
        select v.name as version, l.name as area
        from encounters e
        join versions v on v.id = e.version_id
        join location_areas l on l.id = e.location_area_id
        where e.pokemon_id = :id and (:version is null or v.name = :version)
        order by v.id, l.name
        """,
        id=pokemon["id"],
        version=normalize_name(version) if version else None,
    )
    by_version: dict[str, list[str]] = {}
    for row in rows:
        by_version.setdefault(row["version"], []).append(row["area"])

    if not by_version:
        where = f" in {version}" if version else ""
        return {"found": True, "name": pokemon["name"], "locations": {}, "message": f"No catch locations{where} in the data."}

    result = {"found": True, "name": pokemon["name"], "locations": dict(list(by_version.items())[:MAX_VERSIONS])}
    if len(by_version) > MAX_VERSIONS:
        result["other_versions"] = list(by_version)[MAX_VERSIONS:]
    return result


def get_evolution_chain(name: str) -> dict:
    """Get every member of a Pokémon's evolution chain, with how and at what level each one evolves.

    Args:
        name: the name of any Pokémon in the chain, in any spelling or case, for example "Oddish".

    Returns:
        found=False when the species is not in the loaded data. Otherwise the chain from the first
        stage on. Each member has evolves_from, trigger (level-up, use-item, trade, ...) and min_level.
        Two members with the same evolves_from are a branch.
    """
    species = _species(name)
    if species is None:
        return _not_found(name)

    members = _rows(
        """
        select s.id, s.name, parent.name as evolves_from, t.name as trigger, s.min_level
        from species s
        left join species parent on parent.id = s.evolves_from_species_id
        left join evolution_triggers t on t.id = s.evolution_trigger_id
        where s.evolution_chain_id = :chain_id
        """,
        chain_id=species["evolution_chain_id"],
    )
    parents = {member["name"]: member["evolves_from"] for member in members}

    def depth(member_name: str) -> int:
        steps = 0
        while parents.get(member_name):
            member_name = parents[member_name]
            steps += 1
        return steps

    members.sort(key=lambda member: (depth(member["name"]), member["id"]))
    return {"found": True, "chain": [{key: value for key, value in member.items() if key != "id"} for member in members]}


def get_sprite_uri(name: str, animated: bool = False) -> dict:
    """Get the Google Cloud Storage URI of a Pokémon's sprite.

    Args:
        name: the Pokémon's name in any spelling or case, for example "Bulbasaur".
        animated: True for the animated GIF, False (default) for the static PNG.

    Returns:
        found=False when the Pokémon is not in the loaded data. Otherwise the format (png or gif)
        and gcs_uri. gcs_uri is null when the sprite is missing.
    """
    pokemon = _pokemon(name)
    if pokemon is None:
        return _not_found(name)

    sprite_format = "gif" if animated else "png"
    rows = _rows(
        "select gcs_uri from sprites where pokemon_id = :id and sprite_key = :sprite_key",
        id=pokemon["id"],
        sprite_key=SPRITE_KEYS[sprite_format],
    )

    return {
        "found": True,
        "name": pokemon["name"],
        "format": sprite_format,
        "gcs_uri": rows[0]["gcs_uri"] if rows else None,
    }