# PokéAPI Data Pipeline

Downloads all 1,351 Pokémon from [PokéAPI](https://pokeapi.co), stores them in PostgreSQL, and saves every PNG and GIF sprite (77,156 files) to disk and to Google Cloud Storage. All concurrency uses threads.

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
3. Start PostgreSQL (Docker Desktop must be running):
   ```bash
   docker compose up -d db
   ```

## Run

```bash
python -m pokeapi_pipeline
```

There are no command-line options: every setting comes from `.env`. The pipeline creates or updates the schema itself (Alembic migrations in `src/migrations`) before it loads anything. You can also apply the migrations from Docker with `docker compose run --rm migrate`.

| Setting | Default | Meaning |
|---|---|---|
| `POKEMON_LIMIT` | 1351 | how many Pokémon to load. 1351 is all of them |
| `API_WORKERS` | 64 (max 128) | threads that fetch JSON from PokéAPI |
| `SPRITE_WORKERS` | 64 (max 128) | threads that download sprites, and as many that upload them |
| `HTTP_TIMEOUT` | 10 | seconds before a request times out |
| `MAX_RETRIES` | 3 | retries after a timeout, a dropped connection or a 5xx |
| `RATE_LIMIT_PAUSE` | 30 | seconds every request to a host waits after a 429, doubled on each pause |
| `RATE_LIMIT_MAX_PAUSES` | 0 | pauses before the run gives up on a host that keeps answering 429 |
| `BATCH_SIZE` | 500 | rows per INSERT |
| `LOG_LEVEL` | INFO | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `LOG_FILE` | `logs/pipeline.log` | where the log is written |

### Logs

The terminal stays empty: the pipeline writes only to `logs/pipeline.log`. Warnings from libraries and the traceback of a crash go there too. Each line shows the thread that wrote it, for example `[MainThread]`, `[download_7]` or `[upload_12]`.

The last line of every run says how it ended and how long it took:

```bash
tail -1 logs/pipeline.log
```
```
2026-11-18 17:56:27,841 INFO    [MainThread] pokeapi_pipeline: run 3 finished: completed_with_errors in 4m 33.6s
```

### Run status

Each run adds one row to `pipeline_runs` (start, end, status, Pokémon count, sprite count) and one `run_errors` row per failure.

| Status | Meaning |
|---|---|
| `succeeded` | everything was loaded |
| `completed_with_errors` | every table was loaded, some sprites failed. Each failed sprite is in `run_errors` |
| `failed` | an error stopped the run. Nothing was loaded, because the load is one transaction |

## A full load takes two or three runs

The sprites come from `raw.githubusercontent.com`. It allows about **45,000 requests per rolling hour** from one IP address (measured, GitHub does not publish it), and there are 77,156 sprites. They do not fit in one hour.

With `RATE_LIMIT_MAX_PAUSES=0`, a run stops downloading at the first 429. The sprites it did not get are recorded as failed, and everything else is loaded: every table, and every sprite that was downloaded. The next run downloads only what is missing (see [Re-running](#re-running)).

GitHub counts the requests of the **last 60 minutes**, so wait one hour after the previous run's **last download**, not after its 429. Measured from an empty bucket:

| Run | Started | What happened | Time | Sprites in GCS |
|---|---|---|---|---|
| 1 | 16:20 | 429 after 44,204 downloads | 12m 12s | 44,140 |
| 2 | 17:21 | too early: 31,095 of run 1's downloads were still in GitHub's hour, so 429 after 15,177 | 2m 55s | 59,351 |
| 3 | 17:51 | no 429 | 4m 34s | 77,127 |

Two runs are enough when the second one starts an hour after the first one's last download.

Check the result:

```sql
select count(*), count(gcs_uri) from sprites;  -- 77156 | 77127
select id, status, pokemon_count, sprite_count, finished_at - started_at from pipeline_runs order by id;
```

29 sprites never load. They are animated GIFs of `versions/generation-vii/lets-go-pikachu-lets-go-eevee` that GitHub serves as `application/octet-stream` instead of `image/gif`. The content type check rejects them, so their rows keep an empty `gcs_uri` and every run records them in `run_errors`. A complete load therefore ends as `completed_with_errors` with exactly 29 errors.

## Stages

`pipeline/runner.py` (`PipelineRunner`) runs every stage once and records the run:

```
Discover -> Extract + Media (at the same time) -> Transform -> Load
```

| Stage | File | What it does |
|---|---|---|
| Discover | `pipeline/discover.py` | reads `/pokemon?limit=1351&offset=0` to get the Pokémon ids |
| Extract | `pipeline/extract.py` | `API_WORKERS` threads fetch each Pokémon, its encounters, types, abilities, species and evolution chain. Each resource is fetched once, even when many Pokémon share it. Species in a chain that were not fetched yet are fetched at the end |
| Media | `pipeline/media.py`, `pipeline/sprites.py` | as soon as a Pokémon's JSON arrives, its sprites go to the download threads. Each finished download goes to the upload threads. So downloads and uploads run while Extract is still fetching |
| Transform | `pipeline/transform.py` | pandas turns the JSON into one DataFrame per table. The sprites DataFrame has every sprite file plus the GCS columns Media returned |
| Load | `pipeline/load.py` | upserts every DataFrame in the order below, in one transaction |

The PokéAPI JSON is fetched again on every run (4,599 requests, 20 to 35 seconds), so the tables always match the API. Nothing is cached.

## Load order

A row can only be inserted after the rows it points to, otherwise its foreign key fails. So tables are loaded in this order:

1. **Lookups:** `generations`, `habitats`, `evolution_chains`, `evolution_triggers`, `types`, `abilities`, `stats`, `location_areas`, `versions`. They point at nothing.
2. **`species`:** points at the lookups and at itself (`evolves_from_species_id`). Rows are sorted **parents first**: Pichu (172) goes in before Pikachu (25), and Pikachu before Raichu (26). Sorting by id would put Pikachu first, and its parent would not exist yet.
3. **`pokemon`:** points at `species`.
4. **Link tables:** `pokemon_types`, `pokemon_abilities`, `pokemon_stats`, `encounters`. They point at `pokemon` and the lookups.
5. **`sprites`:** points at `pokemon`. One row per sprite file, with its GCS URI, size and checksum, or an empty `gcs_uri` when it failed.

Everything is loaded in one transaction: if one table fails, nothing is saved.

## Re-running

Running the pipeline again does not create duplicates:

- Every insert is `INSERT ... ON CONFLICT (primary key) DO UPDATE`. A row that already exists is updated, not copied. The three runs above all loaded the same row counts.
- `pipeline_runs` gets a new row on every run on purpose: each run is a new event.

The bucket is listed once at the start of a run: the name and MD5 of every file. It takes 34 seconds for 44,000 files and 48 seconds for 59,000. Then each sprite is handled like this:

| On disk (`data/sprites`) | In the bucket | What happens |
|---|---|---|
| yes | yes | skipped: no download, no upload |
| yes | no | uploaded from disk, no download |
| no | any | downloaded, then uploaded. The upload is skipped when the bucket already has a file with the same MD5 |

So a run after a 429 only downloads the sprites that are missing, and a sprite whose upload failed is uploaded again without downloading it again.

Upserts never delete. If PokéAPI removes a Pokémon or a sprite, its old row stays in the database. To start from nothing, run `docker compose down -v` and `docker compose up -d db`, empty the bucket, and delete `data/sprites`.

## Threads and locks

Only `threading` and `concurrent.futures.ThreadPoolExecutor` are used, with no asyncio. There are three thread pools: `extract` (`API_WORKERS`), `download` and `upload` (`SPRITE_WORKERS` each).

- Each thread gets its own `requests.Session` (`threading.local()`), because a session is not guaranteed to be safe to share.
- The upload threads share one GCS client. Its HTTP connection pool holds `SPRITE_WORKERS` connections (`cloud/gcs.py`), so 64 uploads do not wait for the default pool of 10.
- `Media` is a context manager. Entering it lists the bucket and starts the download and upload pools. Leaving it waits for both pools, or cancels the queued work if an error stopped the run.

Shared state is protected by a lock:

| Shared state | Where | Race without the lock |
|---|---|---|
| request and download counters | `PokeAPIClient` | `+= 1` is read, add, write. Two threads both read 5 and both write 6, so one count is lost |
| rate limit state: when a host may be called again, how many pauses it had, and which hosts the run gave up on | `PokeAPIClient` | two threads get a 429 at the same moment and both start a pause, so the wait doubles twice |
| set of already-claimed resources (types, abilities, species, chains) | `Extractor` | two threads both see type 12 as "not fetched yet" and both download it |
| collected responses (`_raw`) | `Extractor` | many threads write into the same dict |
| list of download futures | `Media` | many extract threads add sprites at the same time |

A sprite file is first written to a temporary file and then renamed. So a crash in the middle of a write never leaves half a file on disk, which matters because the next run trusts every file it finds there.

Media threads return their results instead of changing shared variables. The main thread collects them with `media.results()`.

The database is reached through SQLAlchemy's connection pool, which is thread-safe.

## Sprites on disk and in GCS

The same layout is used in `data/sprites/` and in the bucket:

```
gs://<bucket>/
├── 1_bulbasaur/
│   ├── pngs/
│   │   ├── front_default.png
│   │   ├── other__official-artwork__front_default.png
│   │   └── versions__generation-i__red-blue__front_default.png ...
│   └── gifs/
│       ├── other__showdown__front_default.gif
│       └── versions__generation-v__black-white__animated__front_default.gif ...
└── 2_ivysaur/ ...
```

- Every PNG and GIF URL in the Pokémon's `sprites` JSON is saved, at any depth. Null URLs, SVG and WebP files are skipped.
- The file name is the path of keys to the URL joined with `__`. The `sprite_key` column joins the same keys with `/`, for example `other/showdown/front_default`.
- The response `Content-Type` must match the extension (`image/png` or `image/gif`), and the file is uploaded with it.
- A download that times out, loses its connection or gets a 5xx is retried 3 times with backoff (0.5s, 1s, 2s). An upload is retried by the GCS library for up to 120 seconds. After that the sprite is recorded in `run_errors`, its row keeps an empty `gcs_uri`, and the rest of the run continues.
- 1,718 sprite rows share their URL with another row. For example, `front_female` points at the same file as `front_default` when the female looks the same. Each row is downloaded on its own, so those files are fetched twice.

## Tests

```bash
pytest -m integration
```

Checks the database connection and a GCS upload and delete. Needs the database running and the key in place.

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
   The model uses about 5 GB of memory while it is loaded. Stop Ollama with `brew services stop ollama` when you are done.
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
| `get_sprite_uri(name, animated=False)` | Show me Bulbasaur's animated sprite | the `gs://` URI of the `front_default` PNG, or of the Showdown GIF (`other/showdown/front_default`) when `animated=True` |

- **Names:** `normalize_name` turns what the user typed into PokéAPI's spelling. It lowercases the name, turns ♀ and ♂ into `-f` and `-m`, removes `.`, `'` and `:`, and turns spaces into `-`. So `Mr. Mime` becomes `mr-mime` and `Nidoran♀` becomes `nidoran-f`. A name matches either a Pokémon or the default form of a species.
- **Not in the data:** a name the database does not have returns `{"found": false}`, and the agent says the data is not available instead of guessing. Every Pokémon is loaded, so the example is a name that is not a Pokémon at all: Agumon.
- **Long location lists:** `get_pokemon_locations` returns the first 6 versions and names the rest in `other_versions`. Zubat alone has 568 encounter rows, more than the model's 4096-token context can hold. The agent can ask for one version with `version="red"`.

The instruction in `agent.py` tells the model to answer only from tool results and to call both the habitat and the locations tools for "where does it live" questions. Temperature is 0, so the same question gets the same tool calls.

### Evaluation

```bash
adk eval src/agents/pokedex_agent src/agents/pokedex_agent/pokedex.evalset.json --print_detailed_results --parallelism 1
```

`pokedex.evalset.json` holds 5 cases. Each case stores the question, the tool calls expected with their arguments, and the expected answer:

| Case | Expected tool calls | Expected answer |
|---|---|---|
| Where does Pikachu live? | `get_pokemon_habitat`, `get_pokemon_locations` | forest; Viridian Forest in Red and Blue |
| What type is Charizard? | `get_pokemon_profile` | Fire and Flying |
| What does Oddish evolve into? | `get_evolution_chain` | Gloom, then Vileplume or Bellossom |
| Show me Bulbasaur's animated sprite | `get_sprite_uri(animated=True)` | `gs://<bucket>/1_bulbasaur/gifs/other__showdown__front_default.gif` |
| Where does Agumon live? | `get_pokemon_habitat`, `get_pokemon_locations` | not in the loaded data |

`test_config.json` sets the pass marks. `adk eval` picks it up because it sits next to the eval set:

- `tool_trajectory_avg_score` 1.0 with `ANY_ORDER`: every expected tool call must happen, with the same arguments, in any order. Extra calls are allowed.
- `response_match_score` 0.5: the answer must share at least half its words with the expected answer (ROUGE-1). A small model rewords its answers from run to run, so the default of 0.8 is too strict.

`--parallelism 1` runs one case at a time. There is only one local model, and the default of 4 cases at once makes them queue in Ollama and time out on an 8 GB machine.

Result on an 8 GB M-series Mac: **5 passed, 0 failed**, with every case scoring 1.0 on both metrics. A case takes 38 seconds to 3 minutes, and the whole eval about 12 minutes. ADK saves each run's details in `src/agents/pokedex_agent/.adk/eval_history/`, which is git-ignored.
