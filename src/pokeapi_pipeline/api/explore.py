import json

import requests

from pokeapi_pipeline.util.config import Settings, ROOT

OUTPUT_DIR = ROOT / "data" / "exploration"

SAMPLE_API_URLS = {
    "pokemon_list": "/pokemon?limit=5&offset=0",
    "pokemon_1_bulbasaur": "/pokemon/1",
    "pokemon_25_pikachu": "/pokemon/25",
    "pokemon_43_oddish": "/pokemon/43",
    "encounters_25_pikachu": "/pokemon/25/encounters",
    "species_25_pikachu": "/pokemon-species/25",
    "species_43_oddish": "/pokemon-species/43",
    "evolution_chain_10_pikachu": "/evolution-chain/10",
    "evolution_chain_18_oddish": "/evolution-chain/18",
    "type_12_grass": "/type/12",
    "ability_65_overgrow": "/ability/65",
}

def main() -> None:
    settings = Settings()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        for name, path in SAMPLE_API_URLS.items():
            response = session.get(
                settings.api_base_url + path, timeout=settings.http_timeout
            )
            response.raise_for_status()
            target = OUTPUT_DIR / f"{name}.json"
            target.write_text(json.dumps(response.json(), indent=2), encoding="utf-8")
            print(f"saved {target.relative_to(ROOT)}")

if __name__ == "__main__":
    main()