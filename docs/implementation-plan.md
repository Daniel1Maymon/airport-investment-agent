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

### 0. Find your step (from the GitHub repo only)
The GitHub repo is the only record of progress. A step is **done** when it has been merged into `main` on GitHub. There is no progress file to keep up to date.

1. Run `git fetch origin`.
2. List the finished steps: `git log origin/main --merges --format=%s | grep -E '^Step [0-9]{2}:'`. Each merge of a finished step has a message that starts with `Step NN:`, where `NN` is **always two digits** (`Step 00:`, `Step 06:`, `Step 13:`). See the Git rules below.
3. **Your step** is the lowest step number that is not in that list (read `06` as 6). If the list is empty, your step is Step 0.
4. If a branch for your step already exists (`git branch -a --list '*step-NN-*'`), an earlier session started it and didn't finish, or the user created it. **Stop and tell the user**; don't continue it or delete it on your own. This stop is expected: the user decides what happens to the branch.
5. If the user named a different step than the one you found, stop and tell the user.
6. Tell the user in one line which step you are building, then go on.

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

1. **Main session: update `main`, then create a branch** from it: `git checkout main && git pull origin main`, then `git checkout -b step-NN-short-name`. This makes sure the step starts from every finished step's code. Example branch name: `step-06-measures`.
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
- **File header.** Every file in `app/` and `loader/` starts with a docstring in this fixed format (agreed with the user 2026-10-31). Package `__init__.py` files that only hold one line are exempt. Test files start with one line naming the step they test.
  ```python
  """<One line: what this file is.>

  What it is:   <a bit more detail, in plain words>
  Why we need:  <the problem it solves>
  Used by:      <the files that call it>
  Uses:         <what it reads or depends on: tables, other files>
  Main parts:   <each public function/class, one line each>
  Design:       <where the decision is written in docs/>
  """
  ```
  The labels are fixed, always in this order. A step that starts using a file adds itself to that file's **Used by** line, so the line doesn't go out of date. Older explanation text that doesn't fit a label stays below the header.
- **Plain-language comments in the code** (asked by the user 2026-10-31, as in Steps 14–16). The user reads every change, so the code must explain itself in plain words:
  - Below the header, a short walk-through of how the main part works, in numbered steps, with one real example question (see the "How one turn works, in short" part of `app/agent/loop.py`, or "How one question works" in `app/api.py`).
  - A docstring on every function, also private ones: what it does and, when it helps, an example of what it returns.
  - A short comment on every constant: what it limits and why.
  - A comment before each block that is not obvious at first sight, saying **why**, not only what.
  - Example numbers in comments are either real (checked on the data) or marked as made up.
  - Comments only explain; they never change what the code does. The builder writes them together with the code; the main session checks they are there before the checkpoint.
- **The tiny dataset** (`tests/fixtures/tiny_data.py`, built in Step 0) is shared by every step. The test writer may **add** rows or airports when your tests need them, only if the whole suite still passes. Never change existing values. Record what you added in `tests/fixtures/TINY_DATA.md`.
- **Expected values in tests are worked out by hand** from the tiny dataset and written in the test with a short comment showing the math (for example `# 900 / 0.80 - 1000 = 125`). Never take an expected value from running the code.
- **If a test compares against a doc** (for example "every measure in tools.md exists"), the test must read and parse that doc at run time, not copy its contents.
- **If the design must change**, ask the user first. Then update the doc in `docs/` in the same step, so the docs and the code stay consistent.
- **Downloaded data is untrusted.** It goes in `data/raw/` (not committed). Run any Python that reads it with `python3 -I`. Unit tests never use the network: they use small sample files in `tests/fixtures/raw/`.
- **Git (this project's own rules; they replace any other commit or push checks):**
  - Work in the **main project folder**, one session at a time, on the step's branch. Not in a separate copy of the repo: `CLAUDE.md` is not in git, so a copy wouldn't have it.
  - Before every commit, the whole `pytest` suite passes.
  - On a step branch, commit and push freely (no approval needed). **Merging into `main` or pushing `main` always needs the user's approval.**
  - A secret scan runs on every commit and every push (global git hooks in `~/.claude/git-hooks/`). It blocks: files that must never be committed (`.env` except `.env.example`, `*.duckdb`, `*.sqlite`, `data/`, `CLAUDE.md`, the exam PDF, key files), files over 5 MB, and anything that looks like a key or password pattern (gitleaks). Only the user adds exceptions.
  - Never bypass the checks: no `--no-verify` or `-n`, never change `core.hooksPath`, never edit the hooks. If a check blocks you, stop and tell the user.
  - No AI attribution text in commits or PRs.
  - After the user approves a step, its branch is merged into `main` (with the user's approval) with `git merge --no-ff step-NN-short-name -m "Step NN: short name"`, and `main` is pushed to GitHub. The `--no-ff` and the `Step NN:` message (two digits) are required: they are how the next session finds its step (section 0). **Merge on the laptop, never with the "Merge pull request" button on the GitHub website**: the website writes its own message ("Merge pull request #12 from …"), and the next session would think the step is not done. The next step starts from `main`.

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
app/presenters.py       builds tables and "How I got this" steps, rebuilds a saved chat (Step 16)
app/turn_runner.py      one turn at a time per chat, 60-second limit (Step 16)
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
| P8 | AI model | A setting (`OPENROUTER_MODEL`), not fixed in code. Chosen during Step 14: `deepseek/deepseek-v4.1-flash` ($0.045 / $0.50 per million input / output tokens on OpenRouter, 2026-10-31), one of the models allowed on the user's OpenRouter key (with Qwen3.7 Flash and GLM 5.3 Flash). Sonnet 5.5 was considered first. Real-data check: the four exam questions and a follow-up cost $0.0008–0.0018 each, with correct tool choices and numbers. Approved 2026-10-31 (Step 14). |
| P9 | History too long | A fixed limit on the size of the history sent to the AI (a constant in `loop.py`); oldest whole turns are left out first. |
| P10 | Python version and environment | Python 3.12 (stable, with ready-made DuckDB packages; the newest Pythons on this laptop may lack them). One shared `.venv` holding only the libraries, at exact versions. |
| P11 | Units of measures | Shares, growth, load factor and `missing_seats_pct` are stored as **fractions** (0.823, not 82.3), the same unit as `target_load_factor=0.85`. Each `MEASURES` entry names its unit, so the chat page can show it as a percent. Approved 2026-10-31 (Step 6). |
| P12 | Score rows in the measure list | `score`, `demand_score`, `strain_score` are listed in `MEASURES` (group "Score", calculated by Step 7) but `compute_measures` does not return them. Approved 2026-10-31 (Step 6). |
| P13 | Percentile denominator (P1 in detail) | grade = (number of airports with a lower value + ½ × number of **other** airports with the same value) ÷ number of airports graded on that measure (the airport itself included) × 100, rounded to 1 decimal. The top of 6 gets 5/6 = 83.3; the bottom gets 0. Approved 2026-10-31 (Step 7). |
| P14 | Grading pool | For each measure, the airports that pass the size filter **and** have a value (not `None`) for that measure. `percentile_grades` leaves `None` airports out of its result. So BTV's missing delay data makes the S2/S3 pool one smaller. |
| P15 | Weight keys | D1 = `growth_long`, D2 = `growth_short`, S1 = `load_factor`, S2 = `nas_delay_per_flight`, S3 = `taxi_out_min`, S4 = `departures_per_runway`. Higher is a stronger candidate for all six (none reversed). `ScoredAirport.raw` is the airport's full measure dict from `compute_measures`; `grades` is keyed by **measure name** (e.g. `"load_factor"`), only for the six scored measures that have a value. |
| P16 | Any missing measure | Same rule as missing delay data, for any of the six: the measure is skipped, the remaining weights are scaled up to total 100, and its **measure name** is added to `missing` (a list, in D1…S4 order). When both delay measures are missing, `flags` also holds `"scored without delay data"`. Approved 2026-10-31 (Step 7). |
| P17 | Rounding | Scores use the rounded grades (P13). `final_score`, `demand_score` and `strain_score` are rounded to 1 decimal. |
| P18 | Half scores | `demand_score` = D1, D2 with their weights scaled to 100; `strain_score` = S1–S4 with their weights scaled to 100. The same scaling uses the weights in force (custom ones too) and skips missing measures. If a half has no measures with a value or its weights total 0, its score is `None`. |
| P19 | Flags (exact text) | `"planes over 85% full"` when `load_factor > 0.85`; `"NAS delays in the top 10% nationally"` when the `nas_delay_per_flight` grade ≥ 90; `"scored without delay data"` (P16). No other flags. Order: as listed here. |
| P20 | Custom weights | A dict given to `score_airports` replaces `DEFAULT_WEIGHTS`; keys it leaves out count as 0. `WeightsError` if a key is not D1…S4, a value is negative, or the total is not 100. |
| P21 | Order, rank, size filter | Kept: `enplanements` is not `None` and ≥ `min_enplanements`. Sorted by `final_score` high to low, ties by IATA code A→Z; `rank` = 1, 2, 3 … in that order. |
| P22 | No final score | With custom weights an airport may have no value for any weighted measure (e.g. `{"D1": 100}` and no 2019 traffic). Its `final_score` is `None` (as P18 for the halves) and it is placed last, still ordered by IATA code. Approved 2026-10-31 (Step 7). |
| P23 | Refusal keys | The refusal table in agent.md has a **Key** column (`no_data`, `airport_not_found`, `chat_not_found`, `out_of_scope`, `ai_unavailable`, `too_many_steps`, `question_too_long`, `busy`, `internal_error`). `REFUSALS` uses exactly these keys; Steps 14 and 16 pick a message by its key. Approved 2026-10-31 (Step 8). |
| P24 | Tool setting checks | `about` always has its four keys (empty `""`/`[]` when not given). Errors: unknown tool → `allowed` = tool names; number out of range → `allowed` = `[min, max]`; too many airports → `[1, 5]`; unknown state → the 51 codes; unknown measure → `MEASURES` names; unknown setting name → the tool's setting names. `US_STATES` is a fixed list in code (50 states + DC); `"ca"` is accepted as `"CA"`. Tool specs use the OpenAI function format OpenRouter takes. A tool's own crash is not caught by `run_tool` (Step 16 turns it into "internal error"). The shared setting types also work when wrapped as optional (`StateList \| None = None`): the error still lists the allowed values. Approved 2026-10-31 (Step 8). |
| P25 | Name resolver order | `resolve_airport` tries, in this order, and **stops at the first rule that finds something**: (1) the text is a code in our `airports` table, any case (`sfo` → SFO); (2) a P5 abbreviation, any case (`LA`, `NYC`, `SF`, `DC`) → every airport whose city is that city; (3) exact city, any case; (4) exact airport name, any case; (5) part of the airport name, any case, only for text of 3+ characters. Spaces at the ends are ignored. Matches are sorted by code. `AirportMatch(iata, name, city, state, size)`, `size` as in P26. So "Boston" stops at rule 3 and gives only BOS, not Manchester-Boston. Approved 2026-10-31 (Step 9). |
| P26 | Airport size | `size` = the FAA hub size of **2025** from `enplanements.hub_type`: `L` → `large`, `M` → `medium`, `S` → `small`, `N` → `non-hub`. No 2025 hub type → `None`; a `size` filter leaves such airports out, and `about.missing` says so. Not `airports.size_class` (OurAirports' type, a different thing). Approved 2026-10-31 (Step 9). |
| P27 | `find_airports` rules | Settings: `text` (1–100 characters), `states` (`StateList`), `region`, `size` (`large`/`medium`/`small`/`non-hub`), `near_airport` (one airport, `AirportCode`), `within_miles` (1–500; 50 when not given). **At least one** of `text`, `states`, `region`, `size`, `near_airport` must be given, else an error listing those setting names. All given filters must **all** match (so `states` + `region` = airports in both). `within_miles` without `near_airport` is an error. `region` is one of the 4 US Census regions or 9 divisions (`REGIONS`), any case; an unknown one gives an error whose `allowed` = the region names. Distance: great circle from `lat`/`lon`, earth radius 3,958.8 miles; the `near_airport` itself is left out. Rows: code, name, city, state, size (+ `distance_mi`, 1 decimal, with `near_airport`); sorted by code (by distance with `near_airport`); at most 25, and `about` says when more matched. No airport matches → empty list and `about.missing` holds the `airport_not_found` message. Approved 2026-10-31 (Step 9). |
| P28 | Names in any tool's settings | `run_tool` turns names into codes **after** the pydantic checks, and only in settings typed `AirportList` or `AirportCode` (one airport), never in `states` ("LA" there is Louisiana). Each value goes through `resolve_airport` with all P25 rules: exactly 1 match → its code; 0 → error with the `airport_not_found` message and `allowed` = `[]`; several → error whose `allowed` = the matching codes, so the AI picks one. The tool does not run on an error. Approved 2026-10-31 (Step 9). |
| P29 | Grades for every measure | `score_airports` grades only the six scored measures. The Step 10 tools grade **every** measure that `compute_measures` returns with `percentile_grades`, over the same pool as P14: airports with `enplanements` ≥ `min_enplanements` and a value for that measure. Higher value → higher grade for every measure (a grade means "higher than X% of graded airports", not "better"). For the six scored measures this gives the same grades as `ScoredAirport.grades`. `score`, `demand_score`, `strain_score` are already 0–100 and have **no grade** (`None`). `app/scoring.py` is not changed. Approved 2026-10-31 (Step 10). |
| P30 | Weights in `rank_airports` | `weights` is a dict with keys `D1`…`S4` (P15), numbers ≥ 0, total 100; keys left out count as 0 (P20). It is checked **in the settings model**, so a bad value is a `SettingsError` the AI sees, never a crash (P24): unknown key or negative value or total ≠ 100 → `allowed` = `["D1", "D2", "S1", "S2", "S3", "S4"]`; `weights` with a `sort_by` other than `score` → `allowed` = `["score"]`. Approved 2026-10-31 (Step 10). |
| P31 | `rank_airports` settings | `states` (`StateList`), `region` and `size` (the `Region` and `Size` types of `find_airports`), `sort_by` (`MeasureName`, default `score`), `order` (`highest_first` or `lowest_first`, default `highest_first`), `weights` (P30), `min_enplanements` (whole number 0–10,000,000, default 100,000), `top_n` (`TopN`, default 10). All settings are optional. Approved 2026-10-31 (Step 10). |
| P32 | Which airports `rank_airports` lists | Only airports that pass the size filter (P21). Grades and `national_rank` are worked out on that national pool **first**; `states`, `region` and `size` are applied **after** (all given filters must match, as P27). An airport with no value for `sort_by` is left out and `about.missing` gives their count ("N airport(s) have no value for X and are not listed"). `size` leaves out airports with no 2025 hub size, and `about.missing` says so (as P27). Order: `sort_by` value high → low (`lowest_first`: low → high); ties by code A→Z. With `sort_by` = `score`, an airport whose `final_score` is `None` (P22) is listed **last in both orders**. At most `top_n` rows; when more matched, `about.missing` says "N airports matched; only the first `top_n` are shown." No airport left → empty list and `about.missing` holds "No airport matches these filters." Approved 2026-10-31 (Step 10). |
| P33 | `rank_airports` result shape | `data` = `{"sort_by", "order", "airports": [rows]}`. Each row: `iata, name, city, state, size` (size as P26), `national_rank`, `value`, `grade`. `national_rank` = 1, 2, 3 … over the **whole national pool before** the region/state/size filters, always counted from the **highest** value (rank 1 = highest, ties by code A→Z, `None` scores last), whatever `order` is, so in a `lowest_first` list the ranks go down (tied airports are still listed A→Z, as P32) (for `score` it is `ScoredAirport.rank`), so BOS can be first in a New England list and still national rank 3. Step 15 adds `region_rank` (P71). `value` = the `sort_by` value as `compute_measures` (or `score_airports` for the three scores) gives it, not rounded again; `grade` = its P29 grade (`None` for the three scores). With `sort_by` = `score` each row also has `demand_score`, `strain_score`, `grades` (the six scored grades, by measure name), `flags` and `missing` from `ScoredAirport`. Approved 2026-10-31 (Step 10). |
| P34 | `airport_profile` | Setting: `airports` (`AirportList`, 1–5, names or codes). Pool: the default 100,000 size filter and default weights. `data` = `{"airports": [one entry per airport, in the order asked, a repeated code shown once]}`. Each entry: `iata, name, city, state, size`; `measures` = `{measure name: {"value", "grade"}}` for every measure `compute_measures` returns (P29 grades); `final_score`, `demand_score`, `strain_score`, `national_rank`, `flags`, `missing` from `ScoredAirport`; `congestion` = `{"measures": {the five crowding measures of decisions 7.18 — departures_per_runway, nas_delay_per_flight, taxi_out_min, late_share, cancel_rate — each {"value", "grade"}}, "strain_score"}`. An airport under the size filter (BHB) keeps its values, but every grade, the three scores and `national_rank` are `None`, `flags` and `missing` are `[]`, and `about.missing` says "BHB has fewer than 100,000 boardings in 2025, so it has no grades or score." Approved 2026-10-31 (Step 10). |
| P35 | `about` of both tools | `data_period`: "2025 (growth from 2019 and 2024; delays Jan–Dec 2025)". `filters`: "airports with N+ enplanements in 2025" plus each given filter. `assumptions` always: "Grades are national: compared with all US airports with N+ enplanements in 2025, before any region filter." Also, when the measure is shown (rank: the `sort_by` measure, or the six scored measures for `score`/`demand_score`/`strain_score`; profile: always): `long_haul_share` → "Long-haul = 3,000+ miles, passenger flights only."; `missing_seats_pct` → "missing_seats_pct uses an 85% target load factor (the cautious end of the 80–85% range)."; any delay measure (`nas_delay_per_flight`, `taxi_out_min`, `late_share`, `cancel_rate`) → the delay-coverage limit of tools.md; `taxi_out_min` → the taxi-out limit; `top_airline_share` → the operating-airline limit. With `score`, the weights in force are stated ("Weights: D1 20, D2 20, …"). Approved 2026-10-31 (Step 10). |
| P36 | Formulas for other years and months | The Step 11 tools need the measure formulas for 2019/2024 and by month. They are **new functions added to `app/measures.py`** (nothing existing changes), so every formula keeps one home. Tests check consistency: with default settings, `route_mix` shares and `delay_causes` NAS minutes per flight equal `compute_measures`. Approved 2026-10-31 (Step 11). |
| P37 | `traffic_trend` | Settings: `measure` (required) one of `passengers`, `departures`, `seats`, `load_factor` (years 2019, 2024, 2025), `enplanements` (2023–2025, by year only), `nas_delay_per_flight`, `taxi_out_min`, `late_share`, `cancel_rate` (2025 only); another measure → error, `allowed` = these 9. `by`: `year` (default) or `month`; `enplanements` by month → error "FAA counts boardings only per year", `allowed` = `["year"]`; a delay measure by year → one 2025 point. **Either** `airports` (`AirportList`) **or** an area (`states` and/or `region`, both must match), not both and not neither → error, `allowed` = `["airports", "states", "region"]`. Formulas as in measures.py (passenger flights only for the first four). Area total: every airport of ours in the area, no size filter; counts are added, ratios are worked out again from the added parts (all passengers ÷ all seats). `data` = `{"measure", "by", "series": [{"name" (code, or the area label), "airports" (codes added up), "points": [{"year", "month" (only by month), "value", "change_from_first" (only by year: fraction vs the first year, `None` if that is `None`/0)}]}]}`; one series per airport in the order asked, a repeated code once; points in time order, only periods with data. Approved 2026-10-31 (Step 11). |
| P38 | `route_mix` groups | Settings: `airport` (one, `AirportCode`, required), `group_by`, `passengers_only`, `long_haul_miles`, `year`, `top_n` as in tools.md. `passengers_only=true` → `is_passenger` rows only. `distance_band` fixed: `under 500`, `500-999`, `1,000-1,999`, `2,000-2,999`, `3,000+` (lower edge included), not moved by `long_haul_miles`. `aircraft_size` per data row: seats ÷ departures; `< 100` regional, `100–229` single-aisle, `≥ 230` wide-body; rows with 0 seats (cargo) → group `cargo`; rows with 0 departures are left out of this grouping. Order: destination/country/airline by departures high → low, ties by name A→Z; bands and sizes in their natural order (short → long, regional → wide-body → cargo); only groups with rows. Approved 2026-10-31 (Step 11). |
| P39 | `route_mix` shares and result | Each group row: `group` (destination code, country code, airline code with `airline_name`, band or size), `departures`, `seats`, `passengers` and `departures_share`, `seats_share`, `passengers_share` (fractions of the airport's total in scope; `None` when the total is 0). More groups than `top_n` → the rest are added into one last row `group` = `"other"` (with `groups` = how many), so shares total 1. `data` = `{"airport", "year", "group_by", "passengers_only", "totals": {departures, seats, passengers}, "long_haul_share", "international_share", "cargo_share", "groups": [rows]}`. `long_haul_share` (distance ≥ `long_haul_miles`) and `international_share` are over the departures in scope; `cargo_share` is always cargo ÷ all departures (as measures.py). No rows for that airport and year → `groups` = `[]`, shares `None`, and `about.missing` says "No departures from X in YEAR." Approved 2026-10-31 (Step 11). |
| P40 | `delay_causes` | Settings: `airports` (`AirportList`), `by` (`year` default, or `month`). 2025, `arr` rows. Per airport (in the order asked, a repeated code once): `iata`, `arriving_flights`, `total_delay_min`, `causes` = `{carrier, weather, nas, late_aircraft, security: {"minutes", "per_flight", "share"}}`; `per_flight` = minutes ÷ all arriving flights (cancelled included, the same as `nas_delay_per_flight`), `share` = minutes ÷ total delay minutes (`None` if 0). By month: the same per month in `months` (list, month order). An airport with no delay rows (BTV) stays in the list with `None` values and `about.missing` says "BTV has no delay data for 2025." plus the delay-coverage limit. Approved 2026-10-31 (Step 11). |
| P41 | `about` of the Step 11 tools | `data_period` names the years used ("2019, 2024, 2025", "2023, 2024, 2025", "2025 (Jan–Dec)", or the `route_mix` year). The Step 10 notes are reused: long-haul definition (`route_mix`, stated with the `long_haul_miles` in force), delay-coverage limit (delay measures, `delay_causes`), operating-airline limit (`route_mix` by airline). `filters` names the airports or area; an area says how many airports were added up. `delay_causes` also says: "Causes are recorded on arriving flights 15+ minutes late; per-flight minutes divide by all arriving flights." Approved 2026-10-31 (Step 11). |
| P42 | Seat-size edge test | The 99/100/229/230 seats-per-flight test builds its **own** small DuckDB in `tmp_path` (`create_schema` + only the edge rows). The shared tiny dataset is not changed, so Steps 0–10 keep their numbers. Approved 2026-10-31 (Step 11). |
| P50 | `unmet_demand` settings | (Numbered from P50 because Step 11 was built at the same time.) `airports` (`AirportList`, 1–5, names or codes); `target_load_factor` optional, a fraction (P11) from 0.70 to 0.95, else an error with `allowed` = `[0.7, 0.95]`. The 80% and 85% estimates are **always** returned (decisions 7.17: never one number); a custom target is added as a third estimate (not repeated if it is 0.80 or 0.85). Approved 2026-10-31 (Step 12). |
| P51 | `unmet_demand` result | `data` = `{"airports": [one entry per airport, in the order asked, a repeated code once]}`. Each entry: `iata, name, city, state`; `passengers`, `seats_offered`, `load_factor` (2025, departing passenger flights); `estimates` = list of `{"target", "label", "missing_seats", "missing_flights", "missing_seats_pct"}` in target order 0.80, 0.85, then the custom one; label `"high estimate"` (0.80), `"low estimate"` (0.85), `"custom target"`; `why` = `{"by_month": [{"month", "passengers", "seats", "load_factor"}] (list, by month), "delay_causes": {"nas", "weather", "carrier", "late_aircraft", "security": {"minutes", "share"}} or None, "runway_and_taxi": {"departures_per_runway", "taxi_out_min": {"value", "grade"}}}`. Math only from `monthly_missing_seats` (Step 6) and grades from `grade_every_measure` (P29, 100,000 pool); `missing_seats_pct` = missing seats ÷ seats offered, so at 0.85 it equals `compute_measures`' value. Delay causes: 2025 `arr` rows summed; share = minutes ÷ total of the five. No delay rows (BTV) → `delay_causes` None and `about.missing` says so. No 2025 passenger flights → `estimates` empty and `about.missing` says so. Numbers not rounded. The result must survive `json.dumps`. Approved 2026-10-31 (Step 12). |
| P52 | `unmet_demand` `about` | `data_period`: "2025 by month (departing passenger flights; delays Jan–Dec 2025)". `assumptions` always: "This is an estimate of missing seats, not a count of people turned away."; "It counts only people who would have flown at today's prices."; "Monthly averages hide daily peaks, so the true peak shortage is likely larger."; "Range: an 80% target load factor gives the high estimate, 85% the low estimate."; the national-grades note of P35; the delay-coverage and taxi-out limits of tools.md (`NOTE_DELAYS`, `NOTE_TAXI`). Approved 2026-10-31 (Step 12). |
| P53 | `data_info` | No settings; any setting given is an error (P24, unknown setting). `data` = `{"sources": [{"source", "url", "period", "loaded_at" (text), "row_count"}] sorted by source, read from `data_sources`; "scope": {"airports": count of the `airports` table (not a fixed 679), "text": "US airports with scheduled passenger service and an IATA code; US territories excluded."}; "gaps": a fixed list: no terminal size or gate counts (runways and traffic stand in), no ticket prices, no airport finances, delay data only for domestic flights of the larger US airlines, live FAA status is never part of a score}`. Approved 2026-10-31 (Step 12). |
| P54 | `live_status` | Setting: `airport` (`AirportCode`). The tool is `live_status(con, settings, fetch=None)`; `None` means `fetch_faa_status()` (looked up at call time, so tests can replace it), which gets the FAA feed with `httpx` and a 10-second timeout and returns the XML text. Parsed with the standard library: every element with an `ARPT` child is an event for that code; event = `{"type": the enclosing Delay_type Name, "reason": cut to 200 characters, other child fields as text (e.g. start, reopen, or direction, min, max, trend)}`. `data` = `{"airport", "feed_available", "updated": the feed's Update_Time, "events": [...]}`. No events → `events` = `[]` and `about.missing`: "No FAA delays or closures reported for X right now." Feed down, timeout, HTTP error or broken XML → a normal result with `feed_available` false and `about.missing`: "The FAA live status feed is not available right now; try again later." (never an error, never a crash). `about.assumptions`: "Live status is context only; it is never part of any score." The sample file uses only the two event formats seen in the real feed on 2026-10-31 (arrival/departure delays, closures). Approved 2026-10-31 (Step 12). |
| P43 | Chat ID and clock | `new_chat` returns `str(uuid.uuid4())` (36 characters, 122 random bits, can't be guessed). Times (`created_at`, `last_active_at`) are stored as UTC ISO-8601 text (`datetime.now(timezone.utc).isoformat()`). **Interface addition:** `ChatStore(path, now=None)`; `now` is a function returning a timezone-aware `datetime`, `None` means the real UTC clock, so tests can replace the clock (the plan's "outside world is passed in" rule). Approved 2026-10-31 (Step 13). |
| P44 | `Step` shape | `Step` is a frozen dataclass with the `messages` columns: `seq, role, content, tool_calls, tool_call_id, model, input_tokens, output_tokens, cost_usd, created_at`. `tool_calls` is a list of dicts in schema.md's form `[{"id", "name", "args"}]`, stored as JSON text and given back exactly as given (`None` when not given). Turning it into the AI service's format is Step 14's job. Approved 2026-10-31 (Step 13). |
| P45 | Empty text | `content` may be `None` (an assistant step that only asks for tools). The caller turns a tool result into JSON text before saving it. Approved 2026-10-31 (Step 13). |
| P46 | Unknown vs. empty chat | `add_step` and `load_steps` on an unknown chat ID raise `ChatNotFound`. A chat that exists with no steps gives `load_steps` = `[]`. `exists` returns `True`/`False` and never raises. Approved 2026-10-31 (Step 13). |
| P47 | Few checks | A `role` other than `user`, `assistant`, `tool` raises `ValueError`. Nothing else is checked (e.g. that a `tool_call_id` matches an earlier request): that belongs to the agent loop (Step 14). Approved 2026-10-31 (Step 13). |
| P48 | Safe step numbers | Every method opens and closes its own SQLite connection (safe across the API's threads). Tables are created with `CREATE TABLE IF NOT EXISTS` when `ChatStore` is made. `add_step` runs in one `BEGIN IMMEDIATE` transaction: next `seq` = largest `seq` of that chat + 1 (1 for the first step), insert the row, update `last_active_at`; so two saves at once can't get the same number. `messages.conversation_id` references `conversations.id`. Approved 2026-10-31 (Step 13). |
| P55 | Message format | The loop turns the saved steps into OpenRouter's chat format (the OpenAI format, as P24): `{"role": "system"}` first, then `user` → `{"role": "user", "content"}`, `assistant` → `{"role": "assistant", "content", "tool_calls": [{"id", "type": "function", "function": {"name", "arguments": JSON text}}]}` (`tool_calls` only when there are some), `tool` → `{"role": "tool", "tool_call_id", "content"}`. The provider sends these messages unchanged and turns the AI's reply back into the store's shape: `AIReply.tool_calls` = `[{"id", "name", "args"}]` (P44) or `None`. A tool result is saved as `json.dumps(result)` (P45). Approved 2026-10-31 (Step 14). |
| P56 | Unreadable tool settings | If the AI's `arguments` text is not valid JSON, the provider keeps the raw text as `args`. The loop passes it to `run_tool`, which returns its usual "Settings must be a set of name/value pairs" error (not a dict), and the AI sees that error and can try again. Never a crash. Approved 2026-10-31 (Step 14). |
| P57 | Rounds | One AI reply that asks for tools = one round, however many tools it asks for (they run in the order asked). At most 5 rounds run. If the AI's reply after round 5 still asks for tools, the turn stops with `too_many_steps`; that last request is **not** saved and its tools don't run. So the AI is called at most 6 times per turn. Approved 2026-10-31 (Step 14). |
| P58 | When steps are saved | Each step is saved as soon as it happens: the user step first (after the chat ID check), then each assistant step and each tool result. No chat ID → `new_chat()`. Unknown chat ID → `chat_not_found` refusal, the AI is never called and nothing is saved. Approved 2026-10-31 (Step 14). |
| P59 | A turn that ends early | On `ai_unavailable` (any round) or `too_many_steps`, the steps already saved stay, and the refusal message is saved as a final `assistant` text step (`model` etc. `None`). So the saved history always stays valid for the next turn: every saved tool request is followed by all its results, and a turn ends with assistant text. A test replays a chat after each early end and checks this. Approved 2026-10-31 (Step 14). |
| P60 | History trimming (P9 in detail) | Measured in characters of `json.dumps` of the history messages (system prompt and tool list not counted). Limit `HISTORY_CHAR_LIMIT = 60_000` (about 15K tokens), a constant in `loop.py` that tests can replace. A turn = a user step up to the next user step. While over the limit, the oldest whole earlier turn is left out; the current turn is never left out, even if it alone is over. Nothing is deleted from the store. Approved 2026-10-31 (Step 14). |
| P61 | Answer length | `MAX_TOKENS = 4_000`, a constant in `loop.py`, sent on every AI call; the system prompt also says "Keep each answer short, at most about 250 words: start with the direct answer and its key number in one or two sentences, then at most 6 short bullets." (was "at most about 800 words"; changed by P103) **Changed 2026-10-31 (Step 14 real-data check):** the first value, 1,100 (about 800 words), cut the answer off: reasoning models such as DeepSeek V4.1 Flash spend hidden "thinking" tokens from the same limit (exam question 1: 1,100 output tokens, only about 175 of them visible text). So the token limit now leaves room for thinking, and the 800-word length is asked for in the prompt. Approved 2026-10-31 (Step 14). |
| P68 | Cut-off answer | **Interface addition:** `AIReply` gains `cut_off: bool = False`; `OpenRouterProvider` sets it when `choices[0].finish_reason` is `"length"` (the reply stopped at `max_tokens`). When a final text reply is cut off, the loop adds `CUT_OFF_NOTE` (a constant in `loop.py`: "(This answer was cut off because it reached the length limit. Ask a narrower question to get the rest.)") after the text, separated by a blank line, both in `TurnResult.answer` and in the saved step. It is not a refusal (`refusal` stays `None`). A cut-off reply that asks for tools is handled as usual. Approved 2026-10-31 (Step 14). |
| P62 | System prompt | `app/agent/prompt.py`: `SYSTEM_PROMPT` holds the 5 rules of agent.md "Rules in the system prompt" **word for word** (the test reads them from agent.md at run time), plus: the exact `out_of_scope` sentence of `REFUSALS`, to be answered alone and unchanged for questions outside US airport investment; use the tools for every number; pass on each tool result's `about` part. Approved 2026-10-31 (Step 14). |
| P63 | `refusal` in `TurnResult` | `Refusal(cause, message)` or `None`. Set by Python: `chat_not_found`, `ai_unavailable` (also for `QuotaReached`), `too_many_steps`; and `out_of_scope` when the AI's final text, spaces at the ends removed, equals the `out_of_scope` sentence. When `refusal` is set, `answer` is `""` (api.md). Other causes (`airport_not_found`, `no_data`) are written by the AI inside a normal answer. `question_too_long`, `busy` and `internal_error` belong to Step 16. Approved 2026-10-31 (Step 14). |
| P64 | `TurnResult` and `tool_events` | `TurnResult(chat_id, answer, tool_events, refusal)`. `tool_events` = this turn's tool calls only, in the order run: `[{"id", "name", "args", "result"}]`, `result` = the `run_tool` dict (an error dict too). The same list can be rebuilt from the saved steps (Step 16 reload). `chat_id` is the new or given chat ID (for `chat_not_found`, the unknown ID that was given). Approved 2026-10-31 (Step 14). |
| P65 | OpenRouter provider | **Interface addition:** `OpenRouterProvider(api_key, model, client=None)`; `client` is an `httpx.Client` (tests pass one with `httpx.MockTransport`; `None` = a real client, 45-second timeout, under the API's 60 s). Missing key or model → `ValueError` when it is made. Request: `POST https://openrouter.ai/api/v1/chat/completions`, header `Authorization: Bearer <key>`, JSON `{"model", "messages", "tools", "max_tokens"}`. Reply: `choices[0].message` (`content`, `tool_calls`), `model`, `usage.prompt_tokens`, `usage.completion_tokens`, `usage.cost` (cost is in every reply, no request flag; OpenRouter docs checked 2026-10-31); a missing usage field → `None`. HTTP 402 or 429 → `QuotaReached`; any other HTTP error, timeout, network error or unreadable reply → `AIUnavailable`. `QuotaReached` is a kind of `AIUnavailable`. Approved 2026-10-31 (Step 14). |
| P66 | `FakeProvider` | `tests/fakes.py`, written by the test writer. `FakeProvider(script)`: each item is an `AIReply` (returned) or an exception (raised), in order; running out of script fails the test. `calls` records a **deep copy** of `(messages, tools, max_tokens)` of every call. Approved 2026-10-31 (Step 14). |
| P67 | Command line | `python -m app.agent.cli "question" [--chat ID]`: reads `Settings`, opens `airports.duckdb` read-only and `chat.sqlite`, runs one turn with `OpenRouterProvider`, prints the answer (or refusal message), the tools used with their settings, the cost of the turn and the chat ID. Settings come from environment variables (`set -a; source .env; set +a`); no new library. Approved 2026-10-31 (Step 14). |
| P69 | Grade direction in tool results | Found in a three-question chat test after Step 14 (2026-10-31): the AI said "a higher grade means less strain", which turned part of its explanation upside down. Fix in Step 15: every tool result that holds grades adds one plain line to its `about` part: "A grade of 80 means a higher value than 80% of US airports; for strain measures, a higher grade means more strain. level = high (grade 67+), middle, or low (grade 33 or less): a high level means a high value of that measure, e.g. a low cancel_rate level means fewer cancellations than most US airports." (extended by P76) A test checks the line is there. Approved 2026-10-31 (for Step 15). |
| P70 | Rank inside a region | Found in the same test: asked how LAX ranks in California, the AI counted the California ranks itself and got them wrong (SNA "6th", then "10th"). This breaks "Python does all numbers". Fix in Step 15: **interface addition:** `rank_airports` returns `region_rank` (1, 2, 3… inside the airports left after the filters) next to `national_rank`, for both `score` and the chosen `sort_by` order; the `about` part says which rank is which. Tests check `region_rank` on the tiny dataset. Approved 2026-10-31 (for Step 15). |
| P71 | P69 and P70 in detail | P69: the line is the constant `NOTE_GRADES` in `app/tools/rank.py` (next to `NOTE_DELAYS`), added to `about.assumptions` of **every** `rank_airports`, `airport_profile` and `unmet_demand` result (all three hold grades), after the national-grades note. P70: every `rank_airports` row gets `region_rank` = 1, 2, 3 … over **all** airports that `rank_airports` would list after the `states`/`region`/`size` filters (P32), **before** the `top_n` cut, counted the same way as `national_rank` (from the highest value, ties by code A→Z), whatever `order` is. With `sort_by` = `score`, airports whose `final_score` is `None` are listed (P32) and take the last `region_rank` places; with any other `sort_by`, airports with no value are not listed, so they have no `region_rank`. With no filter, `region_rank` = `national_rank` for every row. `about.assumptions` of `rank_airports` always adds: "national_rank = place among all US airports in the size filter; region_rank = place among the airports that match these filters. Rank 1 = the highest value." The tool description names `region_rank`. Approved 2026-10-31 (Step 15). |
| P72 | Question file | `scripts/questions.yaml`, read with **PyYAML 6.0.3** (`yaml.safe_load`; added to `requirements.txt`, approved by the user 2026-10-31). Top-level keys are exactly the five groups, in this order: `exam`, `follow_up`, `other`, `no_data`, `attack`. Each group is a list of **chats**; each chat is a list of 1+ question texts, asked in order in one chat (the first starts a new chat, the rest are follow-ups). Every `follow_up` chat has 2+ questions. `exam` holds the four exam questions, one chat each. `load_questions(path)` reads and checks this shape (`ValueError` if a group is missing, unknown, empty, or a chat is not a list of texts). Approved 2026-10-31 (Step 15). |
| P73 | `run_questions` | `scripts/ask_questions.py` (with `scripts/__init__.py`): `run_questions(questions, provider, store, con, out_dir, now=None) -> Path` of the JSON file; `now` as P43. Runs the groups in the P72 order, each chat with `run_turn` (chat ID `None` for its first question, then the returned ID). Saves `questions-YYYYMMDD-HHMMSS.json` (UTC time of the start) and a Markdown file of the same name in `out_dir` (made if missing). If `run_turn` raises, that question gets `error` = "`ExceptionType: message`" and the rest of that chat are not asked (`error` = "skipped: an earlier question in this chat failed"); the run goes on with the next chat. Command: `python -m scripts.ask_questions [--group NAME]` (only one group), with `Settings`, `OpenRouterProvider`, the `CHAT_DB` file and `out_dir` = `scripts/results/`; prints the paths and the total cost. Approved 2026-10-31 (Step 15). |
| P74 | Saved JSON | `{"started_at" (ISO UTC), "total_cost_usd", "questions": [one row per question, in the order asked]}`. Row: `group`, `chat` (1, 2, 3 … within the group), `turn` (1, 2, 3 … within the chat), `chat_id`, `question`, `answer`, `refusal` (`{"cause", "message"}` or `None`), `tools` (`[{"name", "args", "ok"}]`, `ok` false when the result is an error dict, i.e. has an `"error"` key), `model` (the model of the turn's last AI step, `None` if none), `input_tokens`, `output_tokens`, `cost_usd` (sums over the AI steps saved during the turn; a `None` value is skipped; 0 when there are none), `error` (`None` or text, P73). Costs come from the saved steps, as `cli.py` does. `total_cost_usd` = sum of the rows' `cost_usd`. The Markdown file shows the total cost, then one section per question (group, chat, turn, question, answer or refusal message, tools with their settings as JSON, cost), made only from the JSON data. Approved 2026-10-31 (Step 15). |
| P75 | Score parts | Found in a review of the Step 15 question run (`scripts/results/questions-20261031-184913.*`): the numbers were right, but the AI sometimes named the wrong cause of a score, because it had to guess which measure weighed most. Fix: **interface addition:** every `rank_airports` row (every `sort_by`) and every `airport_profile` entry gets `demand_points` and `strain_points` = {measure: points}. Points of measure m in a half = grade × weight / (total weight of that half's measures the airport has a grade for), rounded to 1 decimal like the scores, so a half's points add up to its score (apart from rounding). Weights = the ones used: custom `weights` for `rank_airports` with `sort_by` `score`, else the defaults (also for a ranking by one measure). A measure with no grade is left out; no graded measure or a total weight of 0 → `{}`; an airport with no score → `{}` for both. Helper: `half_points` in `app/scoring.py`. `about.assumptions` of `rank_airports` and `airport_profile` adds: "demand_points / strain_points = how many points each measure adds to the demand / strain score; they add up to that score. The measure with the most points is the biggest reason for the score." Approved 2026-10-31 (answer-quality fixes). |
| P76 | Grade levels | Same review: the AI read some grades the wrong way round. Fix: `grade_level(grade)` in `app/tools/base.py`: 67 or more → high, 33 or less → low, in between → middle, no grade → `None`. `airport_profile` cells (also in `congestion.measures`) and `unmet_demand` `why.runway_and_taxi` cells become {value, grade, level}; every `rank_airports` row gets `level` (of its `grade`; `None` for the score sorts), and rows with `grades` (`sort_by` `score`) also get `levels` = {measure: level}. `NOTE_GRADES` (P69) ends with: "level = high (grade 67+), middle, or low (grade 33 or less): a high level means a high value of that measure, e.g. a low cancel_rate level means fewer cancellations than most US airports." Approved 2026-10-31 (answer-quality fixes). |
| P77 | Months over the target | Same review: asked about unmet demand, the AI named months as "above 85%" that were not. Fix: **interface addition:** each item of `unmet_demand` `estimates` gets `months_over_target` = [{month, load_factor, missing_seats}] for the months that miss seats at that target, in month order, and `annual_vs_target`, one sentence made by Python, e.g. "The 2025 load factor (79.2%) is below the 80% target; 1 month is above it: Jul." ("equal to" when the year equals the target; "no month is above it." when none is; "The 2025 load factor is not known." when there is no load factor). A month counts only when it misses more than 1e-9 seats, so a month exactly at the target is not listed because of a rounding leftover. Approved 2026-10-31 (answer-quality fixes). |
| P78 | Measure label | Same review: the AI described the sort measure in its own words. Fix: **interface addition:** `rank_airports` `data` gets `measure_label` = the plain label of `sort_by` from `MEASURES` (`app/measures.py`); for `score` it is "Final score (demand 40% + strain 60% by default)", or with custom weights "Final score (demand D% + strain S%)" with the two halves' weight totals (written like 50, not 50.0, and never "by default"). Approved 2026-10-31 (answer-quality fixes). |
| P79 | Prompt rules for explanations | Same review: the AI also used "only", "most" or "lowest" without a tool showing it, and added causes and facts that no tool returned. Fix: six more "how to work" lines in `SYSTEM_PROMPT`, listed in docs/agent.md "Rules in the system prompt" as plain bullets and copied word for word (a test checks this): use the level word, explain a score with its points, use `annual_vs_target` and `months_over_target`, say "only"/"most"/"lowest" only when a tool shows it, give no facts that no tool returned, copy repeated numbers from the earlier tool result. The real fix is P75–P78 (Python gives the meaning); these lines tell the AI to copy it. Approved 2026-10-31 (answer-quality fixes). |
| P80 | Start-up and the two databases | (Numbered from P80 because Step 15 was built at the same time.) `create_app(settings, provider=None)` **never raises**. `provider=None` → `OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)`; if that raises `ValueError` (no key or model), the app still starts and every `POST /chat` that would reach the AI gets the `ai_unavailable` refusal (nothing saved, no chat created, AI never called). `ChatStore(settings.chat_db)` is made in `create_app`. The airport database is opened read-only with `open_airport_db(settings.airports_db)` **for each turn**, inside the turn's own thread (P85), and closed when the turn ends; if it can't open, that turn is an internal error (P86). `GET /health` opens it, runs `SELECT 1`, closes it: `200 {"status": "ok"}`; any failure → `503 {"status": "error"}` (no details). Why: a server that crashes at start gives no message; a per-request check says exactly what is wrong. Approved 2026-10-31 (Step 16). |
| P81 | Replies and HTTP codes | Every `POST /chat` reply has the five keys `conversation_id, answer, tables, steps, refusal` (api.md), refusals included (`answer` = `""`, `tables`/`steps` from the turn's tool events, `[]` when none ran). Answers and every refusal → HTTP 200, so the page has one rule: show `refusal.message` when it is set. `internal_error` → HTTP 500 with the same five keys. A request body the page never sends (not JSON, `message` missing / not text / empty after removing spaces at the ends, `conversation_id` not text) → HTTP 400, `conversation_id` `null`, `internal_error` refusal, no technical details (FastAPI's own validation reply is replaced). Approved 2026-10-31 (Step 16). |
| P82 | Order of the checks in `POST /chat` | 1. body (P81) → 2. `len(message)` > 1,000 characters → `question_too_long` (exactly 1,000 is allowed) → 3. a given `conversation_id` that `store.exists` doesn't know → `chat_not_found` → 4. no provider (P80) → `ai_unavailable` → 5. no `conversation_id` → `store.new_chat()` (P83) → 6. busy lock (P84) → 7. the turn (P85). Checks 1–4 and 6 save nothing and never call the AI; `conversation_id` in their reply is the one given (or `null`). Why: a refused question costs nothing and leaves the history clean. Approved 2026-10-31 (Step 16). |
| P83 | Chat ID made by the API | For a new chat the API calls `store.new_chat()` itself and passes that ID to `run_turn` (which then behaves as for an existing chat). Why: the busy lock and the time limit must know the chat ID before the turn starts. Approved 2026-10-31 (Step 16). |
| P84 | One message at a time per chat | An in-memory dict chat ID → `threading.Lock`, guarded by one more lock. The turn takes its chat's lock without waiting; if it is taken → `busy` refusal (nothing saved, AI not called). The lock is released by the turn's thread when `run_turn` **really** ends (also after a timeout, P85), so a message sent while a timed-out turn still runs is `busy` too. Approved 2026-10-31 (Step 16). |
| P85 | 60-second limit | `TURN_TIMEOUT_SECONDS = 60`, a constant in `app/api.py`, read at request time so tests can lower it. The turn runs in its own thread, which owns the airport connection and the chat's lock: open DB → `run_turn(store, con, provider, chat_id, message)` → close DB → release lock (in `finally`). The request waits at most `TURN_TIMEOUT_SECONDS`; after that the reply is `internal_error` (HTTP 500, `conversation_id` = the chat ID, `tables`/`steps` `[]`) and the event is logged. The thread is not stopped: it finishes and saves its own steps, so the saved history stays valid (P59); the provider's 45-second timeout (P65) bounds it. Why: Python can't stop a thread halfway. Approved 2026-10-31 (Step 16). |
| P86 | Internal errors hide details | Any exception in the turn (a tool crash, the database, the store) or anywhere else in a request → `logging` logger `app.api`, `logger.exception(...)` (full details in the server log only) → the `internal_error` refusal, HTTP 500. No exception text, type or path ever appears in a reply. Why: error details can show file paths or keys (agent.md "Safety"). Approved 2026-10-31 (Step 16). |
| P87 | CORS | FastAPI's `CORSMiddleware` with `allow_origins` = `[settings.allowed_origin]` (exact text) or `[]` when it is not set, `allow_methods` = `["GET", "POST"]`, `allow_headers` = `["Content-Type"]`, no credentials. Not set → no web page may call the server (`curl` still works). Why: strangers can't build their own site on our AI budget. Approved 2026-10-31 (Step 16). |
| P88 | `build_steps(tool_events)` | One line per event, in order: `LABEL` + (` (settings)` when the AI sent any) + (` – not run: <error>` when `result` has an `"error"` key; the error is our own text from `run_tool`). Labels: `find_airports` "Looked up airports", `rank_airports` "Ranked airports", `airport_profile` "Looked up airport profiles", `traffic_trend` "Looked at traffic over time", `route_mix` "Split departures into groups", `delay_causes` "Looked at delay causes", `unmet_demand` "Estimated unmet demand", `data_info` "Checked which data we have", `live_status` "Checked today's FAA status"; an unknown tool name → `Asked for an unknown tool "<name>"`. Settings, in the order the AI sent them: `name: value` joined by `; `, `_` in the name → space; a list → items joined by `, `; a dict → `key value` pairs joined by `, `; `true`/`false` → `yes`/`no`; anything else → `str(value)`. Settings that are not a dict (raw text, P56) → ` (settings could not be read)`. Example: `Ranked airports (region: New England; top n: 5)`. Why: Python writes it from the real request, so it shows what really happened. Approved 2026-10-31 (Step 16). |
| P89 | Table shape: raw numbers with units | `build_tables(tool_events)` → list of `{"title", "columns", "units", "rows", "about"}`; `units` has one entry per column; `rows` hold the tool's values **unchanged** (not rounded, not turned into text; `None` stays `None`), so the page (Step 17) formats them by unit. Units: `text`, `rank`, `grade`, `year`, `month`, `miles`, `row` (take the unit from the row's `Unit` column), or a `MEASURES` unit (`passengers`, `departures`, `seats`, `share`, `minutes`, `departures per runway`, `points`). `about` = the result's `about`, unchanged. An error result or an unknown tool → no table. Why: the number stays exactly what the tool returned (decisions 7.19). Approved 2026-10-31 (Step 16). |
| P90 | Tables per tool | Labels below are `MEASURES` labels. `find_airports` "Airports found": Code, Name, City, State, Size (+ Distance (miles) when rows have `distance_mi`). `rank_airports` "Airports ranked by <label of sort_by> (highest first / lowest first)": National rank, (Region rank, only when rows have `region_rank`), Code, Name, State, Size, <label of sort_by> (its unit), Grade; with `score` also Demand score, Strain score (`points`). `airport_profile` "Profile: <codes joined by , >": Measure, Unit, then per airport `<code>` (`row`) and `<code> grade`; one row per entry of `measures` (label, unit), then Score, Demand score, Strain score (`points`, grade `None`) and National rank (`rank`, grade `None`). `traffic_trend` "<label> by year / by month": Airport or area, Year, (Month, by month), Value (the measure's unit), (Change from first year, `share`, by year). `route_mix` gives **two** tables: "<code> flight mix, <year>" (Long-haul share, International share, Cargo share; one row) and "<code> departures by <group_by, _ → space>, <year>" (Group, (Airline, by airline), Departures, Seats, Passengers, Departures share, Seats share, Passengers share). `delay_causes` "Delay causes, 2025 (arriving flights)": Airport, (Month, by month), Cause, Minutes, Minutes per flight, Share of delay; one row per airport (per month) per cause in the order carrier "Airline", weather "Weather", nas "Airspace/airport (NAS)", late_aircraft "Late incoming plane", security "Security". `unmet_demand` gives **two** tables: "Unmet demand estimates, 2025" (Airport, Estimate, Target load factor, Missing seats, Missing flights, Missing seats share) and "Load factor by month, 2025" (Airport, Month, Passengers, Seats, Load factor). `data_info` "Data sources": Source, URL, Period, Loaded at, Rows. `live_status` "FAA live status for <code>": Type, Reason, Details (the event's other fields as `key: value` joined by `; `); no events → `rows` = `[]`. So api.md now says "one or more tables per tool result". Why: exam question 3 asks for the long-haul share, which is in `route_mix`'s summary, not its groups. Approved 2026-10-31 (Step 16). |
| P91 | `GET /chat/{id}` | `200 {"conversation_id", "turns": [{"question", "answer", "tables", "steps", "refusal"}], "refusal": null}`. Unknown ID → `200 {"conversation_id": id, "turns": [], "refusal": chat_not_found}`. Rebuilt from `load_steps` only: a turn = a `user` step up to the next one; its tool events = each `tool_calls` entry of its assistant steps paired with the `tool` step of the same `tool_call_id` (`result` = `json.loads(content)`; a call with no saved result is left out); `answer` = text of the turn's last assistant step without `tool_calls` (`""` if none). If that text equals the saved `ai_unavailable` or `too_many_steps` message (P59), or, with spaces at the ends removed, the `out_of_scope` message (as `loop.py`), `refusal` is set and `answer` = `""`. Tables and steps use the same `build_tables`/`build_steps`, so a reloaded turn equals the live reply (a test compares them). Approved 2026-10-31 (Step 16). |
| P92 | Local ports | The backend runs on port 8000 (`uvicorn --factory app.api:main_app --port 8000`); the page is served from `web/` on port 5500 with Python's built-in server (`.venv/bin/python -m http.server 5500 --directory web`). Why: the page stays separate from the backend, as online (Vercel + Railway). Approved 2026-10-31 (Step 17). |
| P93 | Allowed page address | `ALLOWED_ORIGIN` in `.env.example` is `http://localhost:5500` (was port 8000, the backend's own port). CORS compares the exact text, so the page must be opened at `http://localhost:5500`, not `127.0.0.1`. Approved 2026-10-31 (Step 17). |
| P94 | Backend address | One line at the top of `web/app.js`: `const BACKEND_URL = "http://localhost:8000";`. Step 18 changes only this line. Approved 2026-10-31 (Step 17). |
| P95 | Text only, never HTML | Everything from the server (answer, airport names, `about` notes, refusal messages, steps) is put in the page as text (`textContent` / text nodes), never with `innerHTML`. The answer keeps a small safe markdown subset, built from DOM nodes: `**bold**`, lines starting with `#` as headings, lines starting with `- ` or `* ` as bullet lists, blank lines as paragraph breaks. Why: AI text and downloaded data can never change or attack the page (agent.md "Safety"). Approved 2026-10-31 (Step 17). |
| P96 | Number formats by unit | `share` → percent, 1 decimal (`0.823` → `82.3%`); `passengers`, `departures`, `seats`, `departures per runway` → whole number with thousands separators; `grade`, `points`, `minutes`, `miles` → 1 decimal; `rank`, `year` → as is; `month` 1–12 → `Jan`…`Dec`; `text` → as is; `row` → the unit in that row's `Unit` cell; `null` → `–`. An unknown unit → the value as is. Approved 2026-10-31 (Step 17). |
| P97 | Table caveats | Each table has its title, then the table inside its own sideways-scrolling box, then a closed `<details>` "About this data" with data period, filters, missing and assumptions (empty parts left out). Why: caveats one click away; a wide table never makes the page scroll sideways at phone width. Approved 2026-10-31 (Step 17). |
| P98 | Errors, reload, voice | The page reads the JSON reply on any HTTP status and shows `refusal.message` when set (400/500 replies carry it, P81); only a failed request (network down, reply not JSON) shows "Could not reach the server. Try again.". The chat ID is kept in `localStorage` (wrapped in try/catch); on load a stored ID is reloaded with `GET /chat/{id}`; if the reply's refusal is `chat_not_found`, the ID is cleared and an empty chat shown. "New chat" clears the ID and the messages. While waiting, Send is disabled and Enter does not send either. Voice: the microphone button is shown only when the browser has speech recognition (`SpeechRecognition` or `webkitSpeechRecognition`), language `en-US`; the spoken text fills the message box and is not sent on its own. Approved 2026-10-31 (Step 17). |
| P103 | Shorter, plainer answers | The prompt asks for at most about 250 words, the direct answer with its key number first, then at most 6 bullets; plain measure names instead of code names; no tables in the text (the page already shows the tool tables). Why: the first look at the chat page showed long answers that were hard to read. Approved 2026-10-31 (Step 17). |
| P104 | Readable chat page | The answer text is at most about 70 characters per line with more line spacing and real heading sizes; tables the AI writes anyway (`| a | b |` lines) are drawn as real tables, still built from text nodes (P95 stays: never HTML); the tool tables sit under the answer in one closed box "Show the numbers (N tables)"; "How I got this" stays visible. Why: the first look showed a dense wall of text and raw `|---|` lines. Approved 2026-10-31 (Step 17). |
| P105 | Welcome screen for a business reader | While the chat is empty, the page shows one question headline, one sentence on what the agent does, the score split as a sign (Demand 40%: two growth measures; Strain 60%: four crowding measures), and the four exam questions as one-click buttons. Data sources, the full method, the AI's role and the limits sit in a "How the score works" panel (header button), so the first screen stays short. A one-line note under the message box: decision support from public data, not investment advice. All text is static and matches docs/scoring.md and docs/data-sources.md. Why: the page is shown to people who do not know the project; they need the context without reading a wall of text. Approved 2026-10-31 (Step 17). |
| P106 | Hebrew version, right to left | A flag button switches the page between English and Hebrew; the Hebrew page is mirrored (right to left) and remembers the choice. The page sends `"language": "he"` with each question, and the backend adds one system line asking for the whole answer in Hebrew, also for an English question; level words and measure names are in Hebrew too. The page shows refusal messages and the "How I got this" labels in Hebrew by their fixed key. Data tables, airport names and codes stay in English, left to right. A `language` other than "en" or "he" is a bad request (400). | The firm's readers may prefer Hebrew; one page language means no mixed-language answers. The out-of-scope sentence stays English inside the backend so the loop's word-for-word check still works. |
| P107 | Calm chat layout; "US" in the name | The page is named "US Airport Investment Agent" (Hebrew: סוכן השקעות בשדות תעופה בארה״ב), and the input says "Ask about any US airport". Layout follows common chat sites: an empty chat shows one centred question, the input box and four example questions; questions appear as grey bubbles, answers as plain text without a card; the send button is a round arrow; the input box grows with the text. The score split (Demand 40%, Strain 60%) shows as a thin bar under the examples. Works at phone width with no sideways scroll. | The tool covers US airports only, so the name must say so. A layout readers already know from chat sites needs no learning, and a calm page puts the answer and its numbers first. |
| P108 | Deloitte colours; a clear way back to the start | The page uses Deloitte colours: black, white, Deloitte green (#86BC25) for Demand and the logo mark, a darker green (#26890D) for links and focus, and cool greys. Colours only, no Deloitte logo or name, so the page does not look like an official Deloitte product. The app name in the header and a "+ New chat" button both clear the chat and show the start page. | The project is for a Deloitte exam, so its colours fit the reader. Readers expect the name at the top to lead back to the start, as on most sites. |
| P109 | The browser keeps the list of your chats | After each answer the page saves the chat ID, its first question (as a title, cut to 80 characters) and the time in the browser (localStorage, newest first, at most 50). A chat the server no longer has leaves the list. No backend change: opening a chat uses `GET /chat/{id}`. | There are no user accounts, so the server cannot tell which chats are yours; a server list of all chats would show every visitor everyone's chats. |
| P110 | "Your chats" side panel | A panel on the start side (left in English, right in Hebrew) lists past chats, newest first. Clicking one loads it; the open chat is highlighted with a green bar. New chat clears the page and the list stays. | Works like common chat sites, so readers already know how to use it. |
| P111 | On narrow screens the panel hides behind a menu button | Below 900 px wide the panel is hidden; a ☰ button in the header opens it over the page. A tap outside, the × button or Escape closes it. | A phone is too narrow for the panel and the chat side by side. |
| P112 | Remove a chat from the list | A small × next to each chat removes it from this browser's list; the server keeps the chat. Removing the open chat shows the start page. | Keeps the list tidy without deleting data. |
| P113 | "About the data" button and panel | A header button "About the data" (Hebrew: על הנתונים) opens a panel, like "How the score works": why these years (2025 main year; 2019 the last normal year before COVID; 2020–2022 left out on purpose; 2024 the recent trend), what each source covers, and what COVID means for the score. English and Hebrew. The header buttons now have a border and a white fill, so they look clickable. | A business reader should see why the years were chosen without asking. The reasons were only in decisions.md 7.1. |
| P114 | COVID note in answers that use 2019 | `NOTE_COVID` (app/tools/rank.py) is added to the "about" assumptions when growth since 2019 is shown (rank by score or by growth_long, airport_profile) and for passenger, departure, seat and load-factor trends. Delay-only answers do not get it. Tests: tests/test_p114_covid_note.py. | The note travels with the numbers, so every answer that compares with 2019 carries the reason in its "About this data" box. |
| P115 | An honest COVID limit | The "About the data" panel and NOTE_COVID say that airports that recovered slowly after COVID show weaker growth since 2019, even when they grow fast now; recent growth (2025 vs 2024) balances this. | This is a real bias in the long-term growth measure, so it is stated openly. |
| P116 | Author links | A small line under the disclaimer links to this project's code (github.com/Daniel1Maymon/airport-investment-agent, public), the author's GitHub profile (github.com/Daniel1Maymon) and LinkedIn (daniel-maymon-ramon), opening in a new tab. |

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
  2. `test_year_columns_found_by_label` (`CY 25 Enplanements`/`CY 24 Enplanements`, not by position)
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
- **Real-data check:** about 490K–570K rows per year (2019 488K, 2024 550K, 2025 571K); passengers per year equal the downloaded file's sum; Anchorage: about 54% of departures are cargo. Check which code Palm Beach has in each year (`PBI` or `DJT`; decisions 7.6) and report it.
- **Design:** [data-sources.md](data-sources.md) C, [schema.md](schema.md) `route_traffic`.

### Step 4: Delays
- **Part:** Loader
- **Needs:** 1 (the `airports` table, to keep only our airports).
- **Builds:** downloads the On-Time files for 2025, unzips each one, and reduces single flights to totals per airport × month × direction (`airport_delays`). One month is downloaded and checked first, before the 40-minute full download. Airport codes go through `CODE_RENAMES` from `loader/common.py` (`PBI` → `DJT`, decisions 7.6) before the "only our airports" filter, so Palm Beach is kept.
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
  - **Done 2026-10-31 on the existing downloads in `data/raw`, not an empty folder** (user's decision). The build found all 20 raw files, downloaded nothing, and passed its checks in about 11 seconds: airports 679, enplanements 1,503, route_traffic 1,608,927, airport_delays 7,898; the file opens read-only. It warned about 16 FAA codes with no IATA code (15 in US territories, which are out of scope, and Kake, AK, `AFE`).
  - **Why the empty-folder download was skipped:** it would download about 340 MB again (15–40 minutes) and add nothing about our code. The download functions were already used in Steps 1–4 to fetch these files. Finding all 20 files without downloading proves the build expects the same file names the downloads write. The "download only what's missing" logic is covered by unit tests with fake downloads. An empty-folder run would only show that the BTS and FAA websites still work that day; if they change, the loader stops with a clear error.
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
  - `app/tools/base.py`: `ToolResult(data, about)` with `.to_dict()`; `register(name, description, settings_model)` as a decorator; `run_tool(con, name, settings: dict) -> dict` returns the result, or `{"error": ..., "allowed": [...]}` and never raises for a bad setting; `tool_specs_for_ai() -> list[dict]`; `TOOLS` (the registry: name → `Tool(name, description, settings_model, fn)`); shared setting types for later tools `TopN`, `AirportList`, `StateList`, `MeasureName`, the `Allowed` marker and `US_STATES` (P24).
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
  - Tool `find_airports` registered with the settings in tools.md (P27). `app/tools/__init__.py` imports each tool file, so `TOOLS` is full wherever `app.tools` is imported.
  - `app/tools/base.py` gains `AirportCode` (one airport; P28) and the name-to-code step in `run_tool`.
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
- **Interface:** `run_questions(questions, provider, store, con, out_dir, now=None) -> path of the saved file` and `load_questions(path)`; the question list lives in `scripts/questions.yaml`, grouped by kind. Details: P71–P74.
- **Tests (write first)** in `tests/test_step15_question_script.py`:
  1. `test_runs_every_question_with_fake_provider_and_saves_file`
  2. `test_saved_file_has_answer_tools_and_cost_per_question`
  3. `test_question_list_has_every_group` (exam, follow-up, other, no data, attack)
  4. `test_follow_ups_use_the_same_chat`
- **Real-data check:** run with the real AI; read the saved file together with the user. Wrong behaviour goes back to Step 14 before moving on.
- **Also in this step:** the two answer fixes P69 (grade direction line) and P70 (`region_rank` in `rank_airports`), with their tests, before the real-data run.
- **Design:** decisions 7.21, [agent.md](agent.md) "Safety".

### Step 16: The backend API
- **Part:** Chat page + API
- **Needs:** 14.
- **Builds:** `app/api.py` (FastAPI): `POST /chat`, `GET /chat/{id}`, `GET /health`. `app/presenters.py` builds the tables and the "How I got this" steps straight from the tool requests and results. Also the 1,000-character limit, one message at a time per chat, the 60-second limit, CORS for the Vercel page only, and errors that never show technical details.
- **Interface:**
  - `app/api.py`: `create_app(settings, provider=None) -> FastAPI` (tests pass a `FakeProvider`).
  - `app/presenters.py`: `build_tables(tool_events) -> list[dict]`, `build_steps(tool_events) -> list[str]`, `rebuild_turns(steps) -> list[dict]` (GET /chat/{id}), `refusal_dict(cause) -> dict`.
  - `app/turn_runner.py`: `TurnRunner(store, provider, airports_db)`, `.run(chat_id, message, timeout) -> (status, TurnResult | None)` with status `"busy"`, `"done"`, `"crash"` or `"timeout"` (the busy lock and the time limit).
  - Split into three files so each has one job: `api.py` only the addresses and their checks (approved by the user 2026-10-31).
  - Details: P80–P91.
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
- **Details:** P92–P98, P103–P116.
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
