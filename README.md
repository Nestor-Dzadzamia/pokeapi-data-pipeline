# PokéAPI Data Pipeline

Downloads the first 50 Pokémon from [PokéAPI](https://pokeapi.co), stores them in PostgreSQL, and copies two sprites per Pokémon (a PNG and an animated GIF) to Google Cloud Storage. All concurrency uses threads.

A Pokédex agent built with Google ADK answers questions about the loaded data. It runs on a local Qwen 2.5 model through Ollama: see [Pokédex agent](#pokédex-agent).

The data model and the answers to the design review questions are in [docs/design_review.md](docs/design_review.md).

## Setup

1. Create the virtual environment and install the packages:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   pip install -e .
   ```
2. Copy `.env.example` to `.env` and fill it in. Put the service account key in `secrets/` and set `GOOGLE_CLOUD_CREDENTIALS` to its path. `secrets/` and `.env` are git-ignored, so the key is never committed.
3. Start PostgreSQL:
   ```bash
   docker compose up -d db
   ```

## Run

```bash
python -m pokeapi_pipeline
python -m pokeapi_pipeline --workers 8 --limit 151
```

The pipeline creates or updates the schema itself (Alembic migrations in `src/migrations`) before it loads anything. You can also apply the migrations from Docker with `docker compose run --rm migrate`.

| Setting | Default | Meaning |
|---|---|---|
| `WORKERS` or `--workers` | 8 (max 16) | number of worker threads |
| `POKEMON_LIMIT` or `--limit` | 50 | how many Pokémon to load |
| `BATCH_SIZE` | 500 | rows per INSERT |
| `MAX_RETRIES` | 3 | retries for API calls, downloads and uploads |
| `LOG_LEVEL` | INFO | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `LOG_FILE` | `logs/pipeline.log` | where the log is written |

Everything the pipeline does is logged to the terminal and appended to `logs/pipeline.log`. Each line shows the thread that wrote it, for example `[extract_3]` or `[media_7]`.

### All 151 Generation I Pokémon

`--limit 151` loads 151 Pokémon, 188 species, 78 evolution chains, 15,604 encounters and 302 sprites, with no code changes.

Upserts add and update rows but never delete them. To go back to 50, reset the database with `docker compose down -v`, then `docker compose up -d db`, and run the pipeline again.

## Stages

| Stage | File | What it does |
|---|---|---|
| Discover | `pipeline/discover.py` | reads `/pokemon?limit=50&offset=0` to get the Pokémon ids |
| Extract | `pipeline/extract.py` | threads fetch each Pokémon, its encounters, types, abilities, species and evolution chain. Species in a chain that are outside the 50 (like Pichu) are fetched too. Every response is cached as JSON in `data/cache/` |
| Transform | `pipeline/transform.py` | pandas turns the JSON into one DataFrame per table |
| Load | `pipeline/load.py` | upserts every DataFrame in the order below, in one transaction |
| Media | `pipeline/media.py` | threads download the sprites, upload them to GCS, and save the URI, size and checksum |

Each run adds one row to `pipeline_runs` (start, end, status, counts) and one `run_errors` row per failure.

## Load order

A row can only be inserted after the rows it points to, otherwise its foreign key fails. So tables are loaded in this order:

1. **Lookups:** `generations`, `habitats`, `evolution_chains`, `evolution_triggers`, `types`, `abilities`, `stats`, `location_areas`, `versions`. They point at nothing.
2. **`species`:** points at the lookups and at itself (`evolves_from_species_id`). Rows are sorted **parents first**: Pichu (172) goes in before Pikachu (25), and Pikachu before Raichu (26). Sorting by id would put Pikachu first, and its parent would not exist yet.
3. **`pokemon`:** points at `species`.
4. **Link tables:** `pokemon_types`, `pokemon_abilities`, `pokemon_stats`, `encounters`. They point at `pokemon` and the lookups.
5. **`sprites`:** points at `pokemon`. Media fills in its GCS columns after the load.

Everything is loaded in one transaction: if one table fails, nothing is saved.

## Re-running

Running the pipeline again does not create duplicates:

- Every insert is `INSERT ... ON CONFLICT (primary key) DO UPDATE`. A row that already exists is updated, not copied. Two runs in a row leave every table with the same row count.
- The sprites upsert only updates `source_url`, so the GCS columns saved by Media are kept.
- A sprite is not uploaded again if GCS already has a file with the same MD5 checksum.
- Cached API responses are reused, so a second run makes 0 API requests.
- `pipeline_runs` gets a new row on every run on purpose: each run is a new event.

## Threads and locks

Only `threading` and `concurrent.futures.ThreadPoolExecutor` are used, with no asyncio.

Each thread gets its own `requests.Session` and its own GCS client (`threading.local()`), because neither is guaranteed to be safe to share.

Shared state is protected by a lock:

| Shared state | Where | Race without the lock |
|---|---|---|
| request and cache-hit counters | `PokeAPIClient` | `+= 1` is read, add, write. Two threads both read 5 and both write 6, so one count is lost |
| set of already-claimed resources (types, abilities, species, chains) | `Extractor` | two threads both see type 12 as "not fetched yet" and both download it |
| collected responses (`_raw`) | `Extractor` | many threads write into the same dict |

The cache files need no lock: each thread writes to its own temporary file and then renames it, so a cache file only exists once it is complete.

Media needs no lock either: each thread returns its result instead of changing shared variables. The main thread counts the results and writes them to the database.

The database is reached through SQLAlchemy's connection pool, which is thread-safe.

## Sprites in GCS

```
gs://<bucket>/
├── pngs/1_bulbasaur.png ...
└── gifs/1_bulbasaur.gif ...
```

- The folder is chosen from the response `Content-Type`, and the file is uploaded with that `content_type`.
- A failed download or upload is retried 3 times with backoff (0.5s, 1s, 2s), then logged in `run_errors`. The rest of the run continues.
- A sprite whose URL is null is counted as missing: its row keeps an empty `gcs_uri`.

## Tests

```bash
pytest -m integration
```

Checks the database and GCS connections. Needs the database running and the key in place.

## Pokédex agent

`src/agents/pokedex_agent` is a Google ADK agent that answers questions about the Pokémon in the database. It runs on `qwen2.5:7b`, served locally by Ollama, so no API key is needed.

### Setup

1. Load the data first with the pipeline (see [Run](#run)). The agent only reads the database.
2. Install Ollama and download the model:
   ```bash
   brew install ollama
   brew services start ollama
   ollama pull qwen2.5:7b
   ```
3. Set the model in `.env` (already in `.env.example`):

   | Setting | Example | Meaning |
   |---|---|---|
   | `AGENT_MODEL` | `ollama_chat/qwen2.5:7b` | the LiteLLM model name the agent uses |
   | `OLLAMA_API_BASE` | `http://localhost:11434` | where Ollama is listening |

   The agent reaches the database with the same `POSTGRES_*` and `DB_*` settings as the pipeline. ADK reads `.env` from the repo root.

### Run

```bash
adk web src/agents
```

Open http://localhost:8000 and pick `pokedex_agent`. To chat in the terminal instead, run `adk run src/agents/pokedex_agent`.

### Tools

Each tool is a plain Python function with type hints and a docstring. ADK turns these into the tool description the model sees. Every query uses SQLAlchemy bind parameters (`:name`), so user text is never pasted into the SQL.

| Tool | Example question | Returns |
|---|---|---|
| `get_pokemon_profile(name)` | What type is Charizard? | types in slot order, abilities (with the hidden one marked), base stats, height in m, weight in kg |
| `get_pokemon_habitat(name)` | Where does Pikachu live? | habitat, generation, legendary and mythical flags |
| `get_pokemon_locations(name, version=None)` | Where does Pikachu live? | location areas grouped by game version |
| `get_evolution_chain(name)` | What does Oddish evolve into? | the chain from its first stage, each member with `evolves_from`, trigger and minimum level |
| `get_sprite_uri(name, animated=False)` | Show me Bulbasaur's animated sprite | the `gs://` URI of the PNG, or of the GIF when `animated=True` |

- **Names:** `normalize_name` turns what the user typed into PokéAPI's spelling. It lowercases the name, turns ♀ and ♂ into `-f` and `-m`, removes `.`, `'` and `:`, and turns spaces into `-`. So `Mr. Mime` becomes `mr-mime` and `Nidoran♀` becomes `nidoran-f`. A name matches either a Pokémon or the default form of a species.
- **Not in the data:** a Pokémon the database does not have returns `{"found": false}`, and the agent says the data is not available instead of guessing. Mewtwo (#150) is outside the first 50, so it is the example.
- **Long location lists:** `get_pokemon_locations` returns the first 6 versions and names the rest in `other_versions`. Zubat alone has 568 encounter rows, more than the model's 4096-token context can hold. The agent can ask for one version with `version="red"`.

The instruction in `agent.py` tells the model to answer only from tool results and to call both the habitat and the locations tools for "where does it live" questions. Temperature is 0, so the same question gets the same tool calls.

### Evaluation

```bash
adk eval src/agents/pokedex_agent src/agents/pokedex_agent/pokedex.evalset.json --print_detailed_results --parallelism 1
```

`pokedex.evalset.json` holds 5 cases recorded from real `adk web` sessions. Each case stores the question, the tool calls expected with their arguments, and the expected answer:

| Case | Expected tool calls | Expected answer |
|---|---|---|
| Where does Pikachu live? | `get_pokemon_habitat`, `get_pokemon_locations` | forest; Viridian Forest in Red and Blue |
| What type is Charizard? | `get_pokemon_profile` | Fire and Flying |
| What does Oddish evolve into? | `get_evolution_chain` | Gloom, then Vileplume or Bellossom |
| Show me Bulbasaur's animated sprite | `get_sprite_uri(animated=True)` | `gs://<bucket>/gifs/1_bulbasaur.gif` |
| Where does Mewtwo live? | `get_pokemon_habitat`, `get_pokemon_locations` | not in the loaded data |

`test_config.json` sets the pass marks. `adk eval` picks it up because it sits next to the eval set:

- `tool_trajectory_avg_score` 1.0 with `ANY_ORDER`: every expected tool call must happen, with the same arguments, in any order. Extra calls are allowed.
- `response_match_score` 0.5: the answer must share at least half its words with the expected answer (ROUGE-1). A small model rewords its answers from run to run, so the default of 0.8 is too strict.

`--parallelism 1` runs one case at a time. There is only one local model, and the default of 4 cases at once makes them queue in Ollama and time out on an 8 GB machine.

Result on an 8 GB M-series Mac: **5 passed, 0 failed**, with every case scoring 1.0 on both metrics. A case takes 10 seconds to 2.5 minutes. ADK saves each run's details in `src/agents/pokedex_agent/.adk/eval_history/`, which is git-ignored.