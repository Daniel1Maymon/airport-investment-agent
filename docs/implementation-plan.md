# Implementation plan

The design ([DESIGN.md](../DESIGN.md) and the other files in `docs/`) is built in **20 small steps**. Each step is built by its own Claude session, test-first (TDD): the session uses two sub-agents, a test writer and then a builder. The user reviews each step before the next one starts (decisions 0.2).

Every step has the same sections:

- **Part**: which of the six parts it belongs to ([architecture.md](architecture.md)): Loader, Scoring, Tools, Conversation store, Agent loop, Chat page + API. Three extra labels cover the rest: **Setup**, **Deploy**, **Docs**.
- **Needs**: steps that must be finished first.
- **Builds**: what the step adds, in plain words.
- **Interface**: the exact functions this step gives to later steps. Later sessions rely on these names, so they must not change without the user's approval.
- **Tests (write first)**: the test list. These are written **before** any code, in this order.
- **Real-data check**: checks against the real `airports.duckdb`, where a real number is already known.
- **Design**: the docs that say how it must behave.

---

## Instructions for the Claude session building a step

You are building **one step** of this plan. Not more.

### 1. Read first (in full, not in parts)
1. [CLAUDE.md](../CLAUDE.md): the task and how the user wants to work.
2. This file, from the top down to "The steps", then **your step only**.
3. Every doc listed under **Design** in your step.
4. The code of the steps listed under **Needs** (only the files their Interface names).

### 2. Check you can start
- **Use the one shared Python environment**: `.venv` in the main project folder (see "One Python environment" below). Run every command with it (`.venv/bin/python -m pytest`, `.venv/bin/python -m loader.build`, …). Never create another environment and never use the system `python3` for project code. If `.venv` is missing and your step is not Step 0, stop and tell the user.
- Run `.venv/bin/python -m pytest`. Every existing test must pass. If not, **stop and tell the user**: an earlier step is broken, and it is not your job to fix it silently.
- Check that each function named in your **Needs** steps' Interface exists. If one is missing or different, stop and tell the user.

### 3. The order of work (TDD with two sub-agents)

**Every main session must use two sub-agents**, one after the other: a **test writer** and a **builder**. The main session doesn't write tests or code itself. It starts the sub-agents, checks their work and reports to the user.

Why two: if the same agent writes the tests and the code, a misunderstanding ends up in both, and the tests pass anyway. A separate test writer sets the target from the plan and the design. A fresh builder, who never saw the test writer's reasoning, must meet it.

A sub-agent starts with no memory of this conversation, so each one's instructions must say which step it works on and what to read (section 1 of these instructions, the step, its Design docs).

1. **Main session: create a branch** `step-NN-short-name` (for example `step-06-measures`).
2. **Sub-agent 1, test writer:**
   - reads the plan and the design docs (not any code from this step: there is none yet);
   - writes the tests from the step's **Tests (write first)** list, in the listed order, in the listed test file. It can add more tests, and must not skip any listed one;
   - works out every expected value by hand (see Rules);
   - runs the tests and sees them fail for the right reason: the function doesn't exist yet or returns the wrong value. A typo or an import error in the test itself is not "the right reason";
   - reports the test file(s) and the failing run.
3. **Sub-agent 2, builder** (a new sub-agent, not the test writer continued):
   - reads the plan, the design docs and the test files;
   - writes the code, one test at a time: makes one test pass, then the next. The smallest code that passes, no extra features;
   - **must not change the test files or the tiny dataset.** If it thinks a test is wrong, it stops and explains why instead of changing it;
   - reports the files changed and the test run.
4. **Main session: check the work itself**, without relying on the sub-agents' reports:
   - run the whole suite (`.venv/bin/python -m pytest`), not only this step's file. Earlier steps' tests must still pass;
   - run the real-data check if the step has one and `airports.duckdb` exists (`.venv/bin/python -m pytest -m realdata`).
5. **If something fails or the builder says a test is wrong:**
   - a test that really is wrong: start a new test writer to fix that test, then a new builder;
   - code that fails: start a new builder with the failing output;
   - after 2 rounds without success, stop and ask the user.
6. **Checkpoint: stop and report** to the user:
   - what was built, in plain words, with any new term explained;
   - the files changed;
   - the test output (fast suite and real-data check);
   - anything that differs from the design, and why;
   - any test the test writer had to fix, and why.
   Then wait. Don't start the next step.

The Rules below apply to both sub-agents; include them in their instructions.

### 4. Rules
- **Explain simply.** The user wants plain words, no jargon. Explain a technical term the first time you use it.
- **Stay in your step.** Don't build things from later steps, even small ones.
- **No new library without asking.** If your step needs one that is not in `requirements.txt`, ask the user. Once approved, add it to `requirements.txt` with an exact version and install it into the shared `.venv`. Never `pip install` anything that isn't written in `requirements.txt`.
- **Don't change an earlier step's Interface** or its tests. If you think one is wrong, stop and ask.
- **The tiny dataset** (`tests/fixtures/tiny_data.py`, built in Step 0) is shared by every step. The test writer may **add** rows or airports when your tests need them, only if the whole suite still passes. Never change existing values. Record what you added in `tests/fixtures/TINY_DATA.md`.
- **Expected values in tests are worked out by hand** from the tiny dataset and written in the test with a short comment showing the math (for example `# 900 / 0.80 - 1000 = 125`). Never take an expected value from running the code.
- **If a test compares against a doc** (for example "every measure in tools.md exists"), the test must read and parse that doc at run time, not copy its contents.
- **If the design must change**, ask the user first. Then update the doc in `docs/` in the same step, so the docs and the code stay consistent.
- **Downloaded data is untrusted.** It goes in `data/raw/` (not committed). Run any Python that reads it with `python3 -I`. Unit tests never use the network: they use small sample files in `tests/fixtures/raw/`.
- **Git (this project's own rules; they replace any other commit or push checks):**
  - Work in the **main project folder**, one session at a time, on the step's branch. Not in a separate copy of the repo: `CLAUDE.md` is not in git, so a copy wouldn't have it.
  - Before every commit, the whole `pytest` suite passes.
  - Never commit, merge or push without the user's approval.
  - No AI attribution text in commits or PRs.
  - After the user approves a step, its branch is merged into `main` (with the user's approval), and the next step starts from `main`.

### 5. What "done" means
A step is done when:
1. every listed test exists and passes;
2. the whole fast suite passes;
3. the real-data check (if any) has been run and its numbers reported;
4. the user has approved it.

---

## Shared ground rules for the code

- **One Python environment.** Every session uses the same virtual environment (a private folder of Python libraries for this project): `.venv` in the main project folder, created once in Step 0 with **Python 3.12**, the same version the Railway container will use.
  - It holds **only the libraries** from `requirements.txt` (exact versions). The project's own code is **not installed** into it. Tests find our code because `pyproject.toml` tells pytest to look in the current folder (`pythonpath = ["."]`).
  - Why not install our code into it: sessions work in the main folder (see Git rules), but if a separate copy of the repo (a git worktree) is ever used, an installed copy would make its tests run the **main folder's** code instead of its own, and pass or fail for the wrong reason. In such a copy, use the main folder's environment by its full path (`/Users/danielmaymon/MyProjects/Deloitte-fde-exam/.venv/bin/python -m pytest`), run from the copy's own folder.
  - The same environment means the same library versions for every step, so a test that passes for one session passes for the next.
- **Two kinds of tests.**
  - **Fast tests** use the tiny dataset or sample files. They run with plain `pytest` in seconds, with no network and no AI.
  - **Real-data tests** are marked `@pytest.mark.realdata`. They use the real `airports.duckdb` and are skipped automatically when that file is missing. Run them with `pytest -m realdata`.
- **Settings** come from environment variables, read in one place (`app/config.py`): `AIRPORTS_DB` (default `airports.duckdb`), `CHAT_DB` (default `chat.sqlite`), `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `ALLOWED_ORIGIN`.
- **The shared measure list has one home**: `app/measures.py` (Step 6). Scoring and every tool call it. No measure is calculated anywhere else.
- **Grades are national.** Scoring always grades all airports that pass the size filter. A region filter is applied after grading, never before.
- **Things that call the outside world are passed in**, so tests can replace them: the AI provider (Step 14), the HTTP fetch for the FAA live feed (Step 12). Downloads in the loader are separate functions from the parsing, so parsing is tested on sample files.

## Folder layout

```
loader/                 one file per data source, plus build.py (one command for everything)
app/config.py           settings from environment variables
app/db.py               opens airports.duckdb read-only
app/measures.py         the shared measure list (Step 6)
app/scoring.py          grades, weights, final score (Step 7)
app/refusals.py         the fixed refusal messages (Step 8)
app/tools/              base.py (checks, result format, registry), resolver.py, one file per tool group
app/store.py            chat.sqlite (Step 13)
app/agent/              provider.py, prompt.py, loop.py, cli.py (Step 14)
app/presenters.py       builds tables and "How I got this" steps (Step 16)
app/api.py              FastAPI, the 3 addresses (Step 16)
web/                    index.html, app.js, sample-reply.json (Step 17)
scripts/                ask_questions.py (Step 15), smoke_test.py (Step 18)
tests/                  one test file per step; conftest.py; fakes.py
tests/fixtures/         tiny_data.py, TINY_DATA.md, raw/ (small sample source files)
data/raw/               real downloads: untrusted, not committed
```

## Order at a glance

```
Setup(0) ─► Loader(1-5) ─► Scoring(6-7) ─► Tools(8-12) ─► Agent loop(14-15) ─► API(16) ─► Chat page(17) ─► Deploy(18) ─► Docs(19)
                                            Conversation store(13) ─┘
```

- Steps 1, 3 and 4 don't depend on each other (step 2 needs step 1's code translation).
- Steps 6–13 are built and tested on the tiny dataset, so they don't wait for the real download. Only their real-data checks need Step 5.
- Step 13 needs only Step 0, so it can be built at any time before Step 14.

## Small decisions this plan adds

The design docs didn't fix these details. They are written here so every session does the same thing. **Approved by the user on 2026-10-31.**

| # | Detail | Choice |
|---|---|---|
| P1 | Percentile grade | Share of graded airports with a **lower** value × 100; ties count half. Rounded to 1 decimal. |
| P2 | Ranking by `missing_seats_pct` | Uses the **85% target** (the cautious end of the range) unless the user asks for another target. |
| P3 | Airport with no runway data | `runway_count` is empty (NULL), so `departures_per_runway` is missing. Not 0. |
| P4 | Airport name length | Names are cut to 100 characters in the loader (safety). |
| P5 | City abbreviations | The resolver knows a short list: LA → Los Angeles, NYC → New York, SF → San Francisco, DC → Washington. It then returns every airport in that city, and the AI picks from that list. |
| P6 | Departures used | T-100 `DEPARTURES_PERFORMED` (flights that really flew), not scheduled. |
| P7 | FAA files overlap | 2024 appears in both FAA files; the value from the newer file (cy2025) wins. |
| P8 | AI model | A setting (`OPENROUTER_MODEL`), not fixed in code. Chosen during Step 14. |
| P9 | History too long | A fixed limit on the size of the history sent to the AI (a constant in `loop.py`); oldest whole turns are left out first. |
| P10 | Python version and environment | Python 3.12 (stable, with ready-made DuckDB packages; the newest Pythons on this laptop may lack them). One shared `.venv` holding only the libraries, at exact versions. |

---

## The steps

### Step 0: Project setup
- **Part:** Setup
- **Needs:** nothing.
- **Builds:** the shared environment: `.venv` with Python 3.12 (`python3.12 -m venv .venv`), `requirements.txt` with exact versions (DuckDB, FastAPI, uvicorn, httpx, openpyxl, pydantic, pytest), installed with `.venv/bin/pip install -r requirements.txt`; `pyproject.toml` with the pytest settings (`pythonpath = ["."]`, the `realdata` marker); the folder layout above; `.gitignore` for `.venv/`, `data/`, `*.duckdb`, `*.sqlite`, `.env`; the settings file; the code that creates the empty airport tables exactly as in schema.md; read-only opening of the airport database; the `realdata` test marker; and the **shared tiny dataset** every later step tests against.
- **Interface:**
  - `loader/common.py`: `create_schema(con)` creates the 5 airport tables from schema.md part 1. `LoadReport(table: str, rows: int, warnings: list[str])` is what every loader returns.
  - `app/config.py`: `Settings` with the five settings listed above.
  - `app/db.py`: `open_airport_db(path) -> duckdb connection`, read-only.
  - `tests/fixtures/tiny_data.py`: `build_tiny_db(path)` builds a small DuckDB file with `create_schema` and made-up rows.
  - `tests/conftest.py`: fixtures `tiny_db` (read-only connection to a fresh tiny database), `real_db` (skips the test when `AIRPORTS_DB` doesn't exist), `tmp_chat_path`.
- **The tiny dataset** must contain these airports, each there to test something. The session picks round numbers that are easy to work out by hand and writes every value in `tests/fixtures/TINY_DATA.md`:

  | Airport | Why it's there |
  |---|---|
  | BOS (MA, large) | New England, big, several runways, two airlines |
  | MHT (NH) | New England, fast growth |
  | BTV (VT) | New England, **no delay data** (tests the missing-data rule) |
  | BHB (ME) | **under 100,000 boardings** (tests the size filter) |
  | LAX (CA, city Los Angeles) | big, busy, one international route |
  | SNA (CA, city Santa Ana) | name resolver, 1 runway |
  | ANC (AK) | many **cargo** flights and one **3,000+ mile** passenger route |

  Rows needed: enplanements 2023–2025 for all; route_traffic for 2019, 2024, 2025 with at least 2 months in 2025 (one month over 85% full and one under 80%, at the same airport); delays for 2025 (departure and arrival rows) for all except BTV; one `data_sources` row per source.
- **Tests (write first)** in `tests/test_step00_setup.py`:
  1. `test_create_schema_makes_five_tables`: the 5 tables exist with the columns of schema.md part 1.
  2. `test_airport_db_is_read_only`: an `INSERT` through `open_airport_db` fails.
  3. `test_tiny_db_has_seven_airports`: the codes listed above.
  4. `test_tiny_db_btv_has_no_delays` and `test_tiny_db_bhb_under_100k`.
  5. `test_realdata_skips_without_db`: with `AIRPORTS_DB` pointing to a missing file, a `realdata` test is skipped, not failed.
  6. `test_settings_read_from_environment`.
  7. `test_python_is_3_12`: the tests run on Python 3.12.
  8. `test_code_imported_from_current_folder`: `app` and `loader` are loaded from the folder the tests run in, not from an installed copy.
  9. `test_installed_versions_match_requirements`: every library in `requirements.txt` (read at run time) is installed at that exact version.
- **Real-data check:** none.
- **Design:** [decisions.md](decisions.md) 1, [schema.md](schema.md) part 1.

### Step 1: Airports and runways
- **Part:** Loader
- **Needs:** 0.
- **Builds:** downloads OurAirports `airports.csv` and `runways.csv` and writes the `airports` table: US, scheduled service, IATA code; open runways only; names cut to 100 characters (P4). Also gives the FAA→IATA code translation for Step 2.
- **Interface** (`loader/airports.py`):
  - `download_ourairports(dest_dir) -> (airports_csv, runways_csv)` (network; not unit-tested).
  - `load_airports(airports_csv, runways_csv, con) -> LoadReport`; running it twice gives the same table, not double rows.
  - `faa_to_iata(airports_csv) -> dict[str, str]`, from `local_code` to `iata_code`.
- **Sample files:** `tests/fixtures/raw/airports_sample.csv` and `runways_sample.csv`, with the real column headers (data-sources.md A) and about 12 rows: normal US airports, a territory (PR), a US airport without scheduled service, one without an IATA code, a closed runway, an airport with no runways, a name over 100 characters, and a row where `local_code` ≠ `iata_code` (`IWA` / `AZA`).
- **Tests (write first)** in `tests/test_step01_airports.py`:
  1. `test_keeps_only_us_scheduled_with_iata`
  2. `test_territory_dropped`
  3. `test_state_from_iso_region` (`US-CA` → `CA`)
  4. `test_size_class_from_type` (`large_airport` → `large`)
  5. `test_counts_open_runways_only`
  6. `test_longest_runway_ft`
  7. `test_no_runways_gives_null` (P3)
  8. `test_long_name_cut_to_100`
  9. `test_faa_to_iata_translation` (`IWA` → `AZA`)
  10. `test_rerun_replaces_rows`
- **Real-data check:** 679 rows; every state is one of the 50 states or DC; SFO has 4 open runways.
- **Design:** [data-sources.md](data-sources.md) A, [schema.md](schema.md) `airports`, [agent.md](agent.md) "Safety" (names).

### Step 2: FAA passenger boardings
- **Part:** Loader
- **Needs:** 1 (`faa_to_iata`).
- **Builds:** downloads the FAA files for 2024 and 2025 and writes `enplanements` for 2023–2025: FAA codes turned into IATA codes, summary rows dropped, codes that can't be translated listed as warnings.
- **Interface** (`loader/enplanements.py`):
  - `download_faa(years, dest_dir) -> list[Path]` (network).
  - `load_enplanements(xlsx_paths, faa_to_iata: dict, con) -> LoadReport`.
- **Sample files:** a test helper builds two small `.xlsx` files with openpyxl, using the real headers (`Rank, RO, ST, Locid, City, Airport Name, S/L, Hub, CY25, CY24, % Change`, and the `CY24, CY23` version). Include a summary row, an `IWA` row, a code with no translation, and one airport present in both files with different 2024 values.
- **Tests (write first)** in `tests/test_step02_enplanements.py`:
  1. `test_one_file_gives_two_years`
  2. `test_year_columns_found_by_label` (`CY25`/`CY24`, not by position)
  3. `test_two_files_cover_three_years`
  4. `test_newer_file_wins_on_overlap` (P7)
  5. `test_faa_code_translated` (`IWA` → `AZA`)
  6. `test_summary_rows_dropped`
  7. `test_untranslated_code_in_warnings`
  8. `test_hub_type_kept`
- **Real-data check:** three years; for each year, the table total equals the file's airport rows total; the warnings list is printed for review.
- **Design:** [data-sources.md](data-sources.md) B, [schema.md](schema.md) `enplanements`.

### Step 3: Routes (flights, seats, passengers)
- **Part:** Loader
- **Needs:** 0.
- **Builds:** the BTS T-100 download (the form with hidden fields) for 2019, 2024, 2025, and the `route_traffic` table. Fails loudly if the BTS page changes or a column is missing.
- **Interface** (`loader/route_traffic.py`):
  - `parse_hidden_fields(html: str) -> dict` (raises a clear error if `__VIEWSTATE` is missing).
  - `download_t100(year, dest_dir) -> Path` (network).
  - `load_route_traffic(zip_paths, con) -> LoadReport`.
- **Sample files:** `tests/fixtures/raw/t100_sample.zip` with `T_T100_SEGMENT_ALL_CARRIER.csv` inside, real headers (data-sources.md C), about 20 rows: passenger and cargo rows, one foreign destination, two identical rows. `tests/fixtures/raw/bts_form_sample.html`: a short saved piece of the form page.
- **Tests (write first)** in `tests/test_step03_route_traffic.py`:
  1. `test_parse_hidden_fields`
  2. `test_page_without_viewstate_fails_loudly`
  3. `test_reads_csv_inside_zip`
  4. `test_columns_mapped` (`DEPARTURES_PERFORMED` → `departures` (P6), `FREIGHT` → `freight_lbs`, …)
  5. `test_is_passenger_when_passengers_over_zero`
  6. `test_dest_country_kept`
  7. `test_duplicate_rows_kept`
  8. `test_passenger_total_matches_file`
  9. `test_missing_column_fails_loudly`
- **Real-data check:** about 570K rows per year; passengers per year equal the downloaded file's sum; Anchorage: about 54% of departures are cargo.
- **Design:** [data-sources.md](data-sources.md) C, [schema.md](schema.md) `route_traffic`.

### Step 4: Delays
- **Part:** Loader
- **Needs:** 1 (the `airports` table, to keep only our airports).
- **Builds:** downloads the On-Time files for 2025, unzips each one, and reduces single flights to totals per airport × month × direction (`airport_delays`). One month is downloaded and checked first, before the 40-minute full download.
- **Interface** (`loader/delays.py`):
  - `download_ontime(year, month, dest_dir) -> Path` (network).
  - `load_airport_delays(zip_paths, con) -> LoadReport`.
- **Sample files:** `tests/fixtures/raw/ontime_sample.zip` with about 30 flights over 2 months. Take the column names from a real file's header. Include cancelled flights, flights 15+ minutes late with cause minutes, and a flight from an airport not in our list.
- **Tests (write first)** in `tests/test_step04_delays.py`:
  1. `test_unzips_and_reads`
  2. `test_one_row_per_airport_month_direction`
  3. `test_departure_flight_count`
  4. `test_arrival_flight_count`
  5. `test_cancelled_counted`
  6. `test_delayed_15_counted`
  7. `test_avg_taxi_skips_cancelled`
  8. `test_cause_minutes_only_on_arrival_rows`
  9. `test_airport_not_in_list_skipped`
  10. `test_two_months_loaded`
- **Real-data check:** for one month, the flight count per airport equals the count of single flights in the raw file; the full year gives about 10K rows.
- **Design:** [data-sources.md](data-sources.md) D, [schema.md](schema.md) `airport_delays`.

### Step 5: One command builds the database
- **Part:** Loader
- **Needs:** 1–4.
- **Builds:** `python -m loader.build --raw data/raw --out airports.duckdb`. It downloads what's missing, runs the four loaders in order, fills `data_sources`, prints a check summary, and writes to a temporary file that is renamed only when everything worked.
- **Interface** (`loader/build.py`):
  - `build(raw_dir, out_path, download=True) -> list[LoadReport]`.
  - `write_data_sources(con, reports)`.
- **Tests (write first)** in `tests/test_step05_build.py` (with `download=False`, on the sample files):
  1. `test_build_from_samples_makes_five_tables`
  2. `test_data_sources_one_row_per_source` (row count equals the table's row count)
  3. `test_failed_loader_leaves_no_file` (an error stops the build and no half-built database is left)
  4. `test_existing_raw_files_not_downloaded_again`
- **Real-data check:** the full build on an empty folder ends with no failed checks; the result opens read-only.
- **Design:** [architecture.md](architecture.md) part 1, [schema.md](schema.md) `data_sources`.

### Step 6: The shared measure list
- **Part:** Scoring
- **Needs:** 0 (tests use the tiny dataset); 5 only for the real-data check.
- **Builds:** `app/measures.py`, which calculates every measure in the tools.md list for every airport, plus the monthly missing-seats math used by Step 12.
- **Interface** (`app/measures.py`):
  - `MEASURES: dict[str, MeasureInfo]`: name → group, plain label, unit, source table.
  - `compute_measures(con, long_haul_miles=3000, target_load_factor=0.85) -> dict[str, dict[str, float | None]]`: airport code → {measure name → value}. Missing data gives `None`.
  - `missing_seats(passengers, seats, target_load_factor) -> float`: one month; never below 0.
  - `monthly_missing_seats(con, iata, target_load_factor) -> dict` with `missing_seats`, `missing_flights`, `seats_offered`, `by_month`.
- **Tests (write first)** in `tests/test_step06_measures.py`, on the tiny dataset, expected values worked out by hand:
  1. `test_measure_names_match_tools_doc` (parses the table in tools.md at run time)
  2. `test_missing_seats_math` (900 passengers, 1,000 seats, 80% → 125)
  3. `test_missing_seats_never_negative`
  4. `test_missing_seats_counted_by_month` (one full month counts although the yearly average is under target)
  5. `test_missing_flights`
  6. `test_missing_seats_pct`
  7. `test_enplanements`
  8. `test_passengers_departures_seats_passenger_flights_only`
  9. `test_growth_short`
  10. `test_growth_long`
  11. `test_load_factor`
  12. `test_nas_delay_per_flight_uses_arrivals`
  13. `test_taxi_out_uses_departures`
  14. `test_departures_per_runway_counts_cargo`
  15. `test_late_share` and `test_cancel_rate`
  16. `test_long_haul_share` and `test_long_haul_threshold_adjustable`
  17. `test_international_share` and `test_cargo_share`
  18. `test_top_airline_share`
  19. `test_no_delay_data_gives_none` (BTV)
  20. `test_no_runways_gives_none` (P3)
- **Real-data check:** SFO 2025 load factor 82.3% (June 89.5%); Anchorage long-haul share of passenger departures about 2.8%.
- **Design:** [tools.md](tools.md) "The shared measure list" and "Unmet demand".

### Step 7: Grades and final score
- **Part:** Scoring
- **Needs:** 6.
- **Builds:** `app/scoring.py`: size filter, national percentile grades (P1), weights, `final_score`, `demand_score`, `strain_score`, flags, and the missing-delay rule.
- **Interface** (`app/scoring.py`):
  - `DEFAULT_WEIGHTS = {"D1": 20, "D2": 20, "S1": 20, "S2": 15, "S3": 10, "S4": 15}`.
  - `percentile_grades(values: dict[str, float | None]) -> dict[str, float]`.
  - `score_airports(measures, weights=None, min_enplanements=100_000) -> list[ScoredAirport]`, sorted best first. `ScoredAirport` has `iata, raw, grades, final_score, demand_score, strain_score, rank, flags, missing`.
  - `WeightsError` when weights don't total 100 or use an unknown key.
- **Tests (write first)** in `tests/test_step07_scoring.py`:
  1. `test_percentile_grades` (a small list with known grades)
  2. `test_ties_get_same_grade`
  3. `test_default_weights_total_100`
  4. `test_small_airport_filtered_out` (BHB)
  5. `test_final_score_formula` (one airport worked out by hand)
  6. `test_rank_order_on_tiny_data`
  7. `test_custom_weights_change_order`
  8. `test_weights_not_100_refused`
  9. `test_missing_delay_weights_scaled_up` (BTV: scored, with a note in `missing`)
  10. `test_demand_and_strain_scores`
  11. `test_flags` ("planes over 85% full")
  12. `test_same_input_same_output`
- **Real-data check:** the full ranking takes under 1 second; print the top 10 for the user to look at.
- **Design:** [scoring.md](scoring.md).

### Step 8: What every tool shares
- **Part:** Tools
- **Needs:** 0 (tested on the tiny dataset).
- **Builds:** the tool result format (`data` + `about`), the tool list (registry), setting checks with pydantic (at most 25 rows, 5 airports, known states, known measures) with errors that list the allowed values, `run_tool` (the only way the agent calls a tool), the tool descriptions sent to the AI, and the fixed refusal messages.
- **Interface:**
  - `app/tools/base.py`: `ToolResult(data, about)` with `.to_dict()`; `register(name, description, settings_model)` as a decorator; `run_tool(con, name, settings: dict) -> dict` returns the result, or `{"error": ..., "allowed": [...]}` and never raises for a bad setting; `tool_specs_for_ai() -> list[dict]`.
  - `app/refusals.py`: `REFUSALS: dict[cause, message]`, one entry per cause in agent.md; `Refusal(cause, message)`.
- **Tests (write first)** in `tests/test_step08_tool_base.py`, using a small test-only tool:
  1. `test_result_has_data_and_about` (`about` has `data_period`, `filters`, `missing`, `assumptions`)
  2. `test_unknown_tool_returns_error`
  3. `test_top_n_over_25_refused_with_range`
  4. `test_more_than_5_airports_refused`
  5. `test_unknown_measure_lists_allowed`
  6. `test_unknown_state_refused`
  7. `test_bad_setting_returns_error_not_exception`
  8. `test_sql_text_in_setting_is_harmless` (a state like `CA'; DROP TABLE airports` is refused, the table is still there)
  9. `test_tool_specs_for_ai_have_json_schema`
  10. `test_one_refusal_per_cause_in_agent_doc` (parses the refusal table in agent.md at run time)
- **Real-data check:** none.
- **Design:** [tools.md](tools.md) "How a tool call works" and "Limits", [agent.md](agent.md) "Refusal messages", decisions 7.13, 7.19, 7.20.

### Step 9: Name resolver and `find_airports`
- **Part:** Tools
- **Needs:** 8.
- **Builds:** the name resolver (code, name, city, the abbreviations in P5), Census regions, and tool 1. `run_tool` turns every airport name in any tool's settings into a code before the tool runs.
- **Interface** (`app/tools/resolver.py`, `app/tools/find.py`):
  - `resolve_airport(con, text) -> list[AirportMatch]` (empty list = not found).
  - `REGIONS: dict[str, list[str]]` and `resolve_region(name) -> list[str]` (states).
  - Tool `find_airports` registered with the settings in tools.md.
- **Tests (write first)** in `tests/test_step09_resolver.py`:
  1. `test_code_any_case` (`sfo` → SFO)
  2. `test_city` ("Santa Ana" → SNA)
  3. `test_part_of_name`
  4. `test_abbreviation` ("LA" → matches include LAX)
  5. `test_not_found` ("Atlantis" → empty, "airport not found")
  6. `test_new_england_states` (CT, ME, MA, NH, RI, VT)
  7. `test_unknown_region_lists_regions`
  8. `test_find_by_state` and `test_find_by_size`
  9. `test_near_airport_within_miles` (SNA within 50 miles of LAX)
  10. `test_run_tool_turns_names_into_codes` (settings `["Santa Ana"]` reach the tool as `["SNA"]`)
- **Real-data check:** "Santa Ana" → SNA; "New England" gives only airports in those 6 states.
- **Design:** [tools.md](tools.md) tool 1, [agent.md](agent.md) "Name resolver".

### Step 10: `rank_airports` and `airport_profile`
- **Part:** Tools
- **Needs:** 7, 9.
- **Builds:** tools 2 and 3, built on `compute_measures` and `score_airports`. Region filters are applied after grading.
- **Interface:** tools `rank_airports` and `airport_profile` registered with the settings in tools.md (`app/tools/rank.py`, `app/tools/profile.py`).
- **Tests (write first)** in `tests/test_step10_rank_profile.py`:
  1. `test_rank_default_by_score`
  2. `test_rank_region_keeps_national_grades` (BOS's grade is the same with and without the New England filter)
  3. `test_rank_by_any_measure` and `test_rank_ascending`
  4. `test_rank_top_n`
  5. `test_rank_custom_weights`
  6. `test_weights_only_with_score`
  7. `test_rank_by_missing_seats_uses_85` (P2)
  8. `test_rank_about_lists_filters_and_missing`
  9. `test_profile_one_to_five_airports`
  10. `test_profile_has_every_measure_with_grade`
  11. `test_profile_congestion_measures_and_strain_score`
  12. `test_profile_small_airport_has_measures_but_no_score` (BHB)
- **Real-data check:** print the New England ranking and the LAX vs SNA profile for the user to read.
- **Design:** [tools.md](tools.md) tools 2–3 and congestion, decisions 7.18.

### Step 11: `traffic_trend`, `route_mix`, `delay_causes`
- **Part:** Tools
- **Needs:** 6, 9.
- **Builds:** tools 4, 5 and 6.
- **Interface:** tools `traffic_trend`, `route_mix`, `delay_causes` registered with the settings in tools.md (`app/tools/trend.py`, `routes.py`, `delays.py`).
- **Tests (write first)** in `tests/test_step11_trend_routes_delays.py`:
  1. `test_trend_by_year` and `test_trend_by_month`
  2. `test_trend_enplanements_by_month_refused`
  3. `test_trend_region_total`
  4. `test_trend_delay_measure_2025_only`
  5. `test_route_mix_by_destination` and `test_route_mix_by_airline`
  6. `test_route_mix_distance_band`
  7. `test_route_mix_aircraft_size_edges` (99 / 100 / 229 / 230 seats per flight)
  8. `test_route_mix_long_haul_setting`
  9. `test_route_mix_with_cargo` (`passengers_only=false`)
  10. `test_route_mix_shares_total_100`
  11. `test_delay_causes_minutes_and_per_flight`
  12. `test_delay_causes_by_month`
  13. `test_delay_causes_no_data_says_missing` (BTV)
- **Real-data check:** Anchorage long-haul share is about 2.8% of passenger departures and about 31% with cargo.
- **Design:** [tools.md](tools.md) tools 4–6.

### Step 12: `unmet_demand`, `data_info`, `live_status`
- **Part:** Tools
- **Needs:** 6, 9.
- **Builds:** tools 7, 8 and 9. Unmet demand is a range of 80%–85% (other targets 70–95%), with the "why" in the same result. `live_status` gets its HTTP fetch passed in, so tests use a saved sample.
- **Interface:** tools `unmet_demand`, `data_info`, `live_status` registered (`app/tools/unmet.py`, `info.py`, `live.py`); `live_status` takes a `fetch` function, defaulting to the real FAA feed.
- **Sample files:** `tests/fixtures/raw/faa_status_sample.xml` (a short piece of the real feed format).
- **Tests (write first)** in `tests/test_step12_unmet_info_live.py`:
  1. `test_unmet_range_80_and_85`
  2. `test_unmet_custom_target`
  3. `test_unmet_target_outside_70_95_refused`
  4. `test_unmet_missing_flights`
  5. `test_unmet_why_has_monthly_load_factor_and_delay_split`
  6. `test_unmet_caveats_in_about`
  7. `test_data_info_reads_data_sources_table`
  8. `test_data_info_states_scope_and_gaps`
  9. `test_live_status_parses_sample`
  10. `test_live_status_airport_with_no_events`
  11. `test_live_status_feed_down_message`
- **Real-data check:** SFO 2025: about 150,000 missing seats at 85% and 1,063,000 at 80% (within 1%); one real call to the FAA feed.
- **Design:** [tools.md](tools.md) tools 7–9 and "Unmet demand", decisions 7.17.

### Step 13: Chat history in SQLite
- **Part:** Conversation store
- **Needs:** 0.
- **Builds:** `app/store.py`: creates `chat.sqlite` with `conversations` and `messages`, starts a chat, saves a step, loads all steps in order.
- **Interface** (`app/store.py`):
  - `ChatStore(path)` with `new_chat() -> str`, `exists(chat_id) -> bool`, `add_step(chat_id, role, content, tool_calls=None, tool_call_id=None, model=None, input_tokens=None, output_tokens=None, cost_usd=None) -> int` (the step number), `load_steps(chat_id) -> list[Step]`.
  - `ChatNotFound` error.
- **Tests (write first)** in `tests/test_step13_store.py`:
  1. `test_new_chat_id_is_long_and_random`
  2. `test_steps_load_in_order` (the 4-step SFO example from schema.md)
  3. `test_tool_request_and_result_stay_linked`
  4. `test_cost_fields_saved`
  5. `test_unknown_chat_raises_not_found`
  6. `test_last_active_updated`
  7. `test_survives_reopen` (close the file, open again, same steps)
  8. `test_step_numbers_continue_after_reopen`
- **Real-data check:** none.
- **Design:** [schema.md](schema.md) part 2, decisions 7.9, 7.10.

### Step 14: The agent loop
- **Part:** Agent loop
- **Needs:** 9–13 (and 7, through the tools).
- **Builds:** the AI provider layer (OpenRouter, with separate "unavailable" and "quota reached" errors), a **fake provider for tests** that plays back scripted replies, the system prompt with its 5 rules, the loop (at most 5 tool rounds), history trimming (P9), the answer length limit, saving each step with model, tokens and cost, and a small command line for trying questions.
- **Interface:**
  - `app/agent/provider.py`: `AIProvider` with `send(messages, tools, max_tokens) -> AIReply` (`text`, `tool_calls`, `model`, `input_tokens`, `output_tokens`, `cost_usd`); `OpenRouterProvider`; errors `AIUnavailable`, `QuotaReached`.
  - `tests/fakes.py`: `FakeProvider(script)` returns the scripted replies in order and records what it was sent.
  - `app/agent/loop.py`: `run_turn(store, con, provider, chat_id: str | None, message: str) -> TurnResult` with `chat_id`, `answer`, `tool_events` (each request with its result), `refusal`.
  - `app/agent/cli.py`: `python -m app.agent.cli "question"`.
- **Tests (write first)** in `tests/test_step14_agent_loop.py`, all with `FakeProvider` (no network):
  1. `test_answer_without_tools` (2 steps saved)
  2. `test_one_tool_round` (the tool really runs; 4 steps saved; the result has `data` and `about`)
  3. `test_tool_error_goes_back_to_ai` (bad setting → the AI sees the error and tries again)
  4. `test_stops_after_5_rounds` ("too many steps" refusal)
  5. `test_no_chat_id_starts_new_chat` and `test_unknown_chat_id_refused`
  6. `test_follow_up_sees_earlier_tool_result`
  7. `test_trimming_drops_oldest_whole_turns` (a tool request and its result are kept or dropped together)
  8. `test_quota_reached_gives_ai_unavailable_refusal`
  9. `test_model_tokens_cost_saved`
  10. `test_system_prompt_has_five_rules`
  11. `test_max_tokens_sent` (answer length limit)
  12. `test_tool_list_sent_matches_registry`
  13. `test_openrouter_request_shape` (a fake HTTP layer, not the network)
  14. `test_openrouter_402_or_429_is_quota`
- **Real-data check:** with a real key, the four exam questions through the command line: the answers use only tool numbers and repeat the `about` notes; a follow-up ("what if growth matters more?") uses the earlier result. Report the cost per question.
- **Design:** [agent.md](agent.md), decisions 1.2, 7.9, 7.12.

### Step 15: Question script
- **Part:** Agent loop
- **Needs:** 14.
- **Builds:** `scripts/ask_questions.py`: runs a fixed list of questions through the agent and saves every answer, the tools called and the cost to a file. The list has the four exam questions, follow-ups, other investor questions, "no data" questions and attack questions.
- **Interface:** `run_questions(questions, provider, ...) -> path of the saved file`; the question list lives in `scripts/questions.yaml`, grouped by kind.
- **Tests (write first)** in `tests/test_step15_question_script.py`:
  1. `test_runs_every_question_with_fake_provider_and_saves_file`
  2. `test_saved_file_has_answer_tools_and_cost_per_question`
  3. `test_question_list_has_every_group` (exam, follow-up, other, no data, attack)
  4. `test_follow_ups_use_the_same_chat`
- **Real-data check:** run with the real AI; read the saved file together with the user. Wrong behaviour goes back to Step 14 before moving on.
- **Design:** decisions 7.21, [agent.md](agent.md) "Safety".

### Step 16: The backend API
- **Part:** Chat page + API
- **Needs:** 14.
- **Builds:** `app/api.py` (FastAPI): `POST /chat`, `GET /chat/{id}`, `GET /health`. `app/presenters.py` builds the tables and the "How I got this" steps straight from the tool requests and results. Also the 1,000-character limit, one message at a time per chat, the 60-second limit, CORS for the Vercel page only, and errors that never show technical details.
- **Interface:**
  - `app/api.py`: `create_app(settings, provider=None) -> FastAPI` (tests pass a `FakeProvider`).
  - `app/presenters.py`: `build_tables(tool_events) -> list[dict]`, `build_steps(tool_events) -> list[str]`.
- **Tests (write first)** in `tests/test_step16_api.py`, with FastAPI's test client and `FakeProvider`:
  1. `test_health_ok` and `test_health_fails_without_airport_db`
  2. `test_first_message_starts_chat_and_returns_id`
  3. `test_reply_has_answer_tables_steps_refusal`
  4. `test_table_numbers_come_from_tool_not_ai` (the fake AI writes a different number; the table keeps the tool's number)
  5. `test_steps_in_plain_words`
  6. `test_message_over_1000_refused_before_ai` (the fake provider is never called)
  7. `test_reload_rebuilds_tables_and_steps`
  8. `test_unknown_chat_gives_chat_not_found`
  9. `test_second_message_while_busy_refused`
  10. `test_turn_over_60_seconds_gives_internal_error`
  11. `test_internal_error_hides_details`
  12. `test_cors_allows_only_our_page`
- **Real-data check:** run the server on the laptop with the real AI; `curl` one exam question and a reload.
- **Design:** [api.md](api.md), decisions 7.22, 7.23.

### Step 17: The chat page
- **Part:** Chat page + API
- **Needs:** 16 (or `web/sample-reply.json` to build the page before the backend is ready).
- **Builds:** `web/index.html` + `web/app.js`: message box, "Working…" while waiting, Send disabled while waiting, the answer, tables, the "How I got this" list, refusal messages, reload by chat ID, voice input through the browser's speech recognition (bonus), and the backend address as one setting at the top of `app.js`.
- **Tests:** no automatic browser tests (they would cost more time than this exam allows). Instead, a **checklist written first** in `web/CHECKLIST.md`, then the page, then the checklist checked by hand:
  1. a question shows "Working…", then the answer, tables and steps;
  2. Send is disabled while waiting;
  3. a refusal shows its message, not an empty answer;
  4. reloading the page shows the same chat;
  5. "New chat" starts an empty chat;
  6. the page works at phone width;
  7. voice input fills the message box (in a browser that supports it).
- **Real-data check:** the four exam questions through the local backend.
- **Design:** [api.md](api.md), [architecture.md](architecture.md) part 6.

### Step 18: Put it online
- **Part:** Deploy
- **Needs:** 5, 16, 17.
- **Builds:** a container for Railway with `airports.duckdb` inside, a Railway disk for `chat.sqlite`, the OpenRouter key as a Railway setting, the page on Vercel, CORS set to the Vercel address.
- **Tests (write first):** `scripts/smoke_test.py <backend-url>` checks `/health`, sends one question and checks the reply's shape. Write it first and run it against the **local** server; then deploy and run it against the public address.
- **Real-data check:** the smoke test passes on the public address; the four exam questions work on the live page; a chat is still there after a redeploy.
- **Design:** [decisions.md](decisions.md) 7.4, [architecture.md](architecture.md).

### Step 19: Final docs
- **Part:** Docs
- **Needs:** 15, 18.
- **Builds:** README with how to run the loader, tests, backend and page; DESIGN.md updated with real results from the question script and anything that changed while building.
- **Tests:** a person (or a fresh session) follows the README from an empty folder to a running chat, with no help. Every doc matches the code.
- **Design:** the exam deliverables ([CLAUDE.md](../CLAUDE.md), "The task").
