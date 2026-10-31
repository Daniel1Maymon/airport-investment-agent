"""Step 0 tests: project setup, settings, read-only database, tiny dataset.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `app/` and `loader/` are regular packages: each has an `__init__.py`
  (otherwise `app.__file__` is None and test 8 cannot check where it came from).
* `loader/common.py`
    - `create_schema(con)`: creates the 5 airport tables of docs/schema.md part 1
      (column names exactly as in the doc, no extra tables).
    - `LoadReport(table: str, rows: int, warnings: list[str])`.
* `app/config.py`: `Settings()` reads the environment when it is created
  (not when the module is imported). Attribute names:
    - `settings.airports_db`        <- env `AIRPORTS_DB`   (default "airports.duckdb")
    - `settings.chat_db`            <- env `CHAT_DB`       (default "chat.sqlite")
    - `settings.openrouter_api_key` <- env `OPENROUTER_API_KEY`
    - `settings.openrouter_model`   <- env `OPENROUTER_MODEL`
    - `settings.allowed_origin`     <- env `ALLOWED_ORIGIN`
  `airports_db` / `chat_db` may be `str` or `pathlib.Path`; tests compare `str(...)`.
* `app/db.py`: `open_airport_db(path)` returns a read-only duckdb connection.
* `tests/fixtures/tiny_data.py`: `build_tiny_db(path)`.
* `tests/conftest.py` fixtures: `tiny_db`, `real_db`, `tmp_chat_path`.
  `real_db` reads `AIRPORTS_DB` at test time (function scope), and skips the
  test when that file does not exist.

Tiny dataset conventions pinned here
------------------------------------
* `route_traffic.dest_country` uses the T-100 `DEST_COUNTRY` column: a 2-letter
  country code. The United States is written `'US'`. (The long name is in
  T-100 `DEST_COUNTRY_NAME`, which we do not store.) The Step 3 loader must
  store the same 2-letter code.
* Airport-level route measures count flights that leave the airport:
  `origin = <airport>`, passenger rows only (`is_passenger`), as in
  docs/tools.md and docs/scoring.md (load factor S1, growth D1, long-haul and
  international share).
"""

import importlib.metadata
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import duckdb
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TINY_AIRPORTS = {
    # code: (state, city or None when the city is not pinned)
    "BOS": ("MA", None),
    "MHT": ("NH", None),
    "BTV": ("VT", None),
    "BHB": ("ME", None),
    "LAX": ("CA", "Los Angeles"),
    "SNA": ("CA", "Santa Ana"),
    "ANC": ("AK", None),
}
NEW_ENGLAND = ["BOS", "MHT", "BTV", "BHB"]


# ---------------------------------------------------------------------------
# Helper: parse docs/schema.md part 1 at run time
# ---------------------------------------------------------------------------

def parse_schema_doc_part1():
    """Return {table_name: set(column_names)} from docs/schema.md part 1.

    A table starts at a line like "**`airports`**: ...". Its columns are the
    backticked names in the first cell of each table row (several names per
    cell are possible, and a " (PK)" note may follow). The header row
    ("| Column | ...") and the separator row ("|---|") are skipped.
    Parsing stops at the heading that contains "Part 2".
    """
    text = (PROJECT_ROOT / "docs" / "schema.md").read_text(encoding="utf-8")
    lines = text.splitlines()

    start = None
    for i, line in enumerate(lines):
        if line.startswith("#") and "Part 1" in line:
            start = i
            break
    assert start is not None, "docs/schema.md has no 'Part 1' heading"

    tables = {}
    current = None
    for line in lines[start + 1:]:
        if line.startswith("#") and "Part 2" in line:
            break
        heading = re.match(r"^\*\*`([a-z_]+)`\*\*", line)
        if heading:
            current = heading.group(1)
            tables[current] = set()
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = line.strip().strip("|").split("|")
        first = cells[0].strip()
        if first == "Column" or set(first) <= set("-: "):
            continue
        tables[current].update(re.findall(r"`([a-z_0-9]+)`", first))
    return tables


# ---------------------------------------------------------------------------
# 1. Schema
# ---------------------------------------------------------------------------

def test_create_schema_makes_five_tables(tmp_path):
    from loader.common import create_schema

    expected = parse_schema_doc_part1()
    # The doc itself must give 5 tables, else the parser (or the doc) is wrong.
    assert len(expected) == 5, f"parsed tables from schema.md: {sorted(expected)}"

    con = duckdb.connect(str(tmp_path / "schema.duckdb"))
    try:
        create_schema(con)
        rows = con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
        ).fetchall()
        created_tables = {r[0] for r in rows}
        assert created_tables == set(expected)

        for table, doc_columns in expected.items():
            cols = con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ?",
                [table],
            ).fetchall()
            assert {c[0] for c in cols} == doc_columns, f"columns of {table}"
    finally:
        con.close()


def test_load_report_fields():
    from loader.common import LoadReport

    report = LoadReport(table="airports", rows=3, warnings=["one warning"])
    assert report.table == "airports"
    assert report.rows == 3
    assert report.warnings == ["one warning"]


# ---------------------------------------------------------------------------
# 2. Read-only database
# ---------------------------------------------------------------------------

def test_airport_db_is_read_only(tmp_path):
    from app.db import open_airport_db
    from loader.common import create_schema

    path = tmp_path / "ro.duckdb"
    writer = duckdb.connect(str(path))
    create_schema(writer)
    writer.close()

    con = open_airport_db(str(path))
    try:
        # Reading works ...
        assert con.execute("SELECT count(*) FROM airports").fetchone()[0] == 0
        # ... writing does not.
        with pytest.raises(duckdb.Error):
            con.execute("INSERT INTO airports (iata) VALUES ('XXX')")
    finally:
        con.close()


def test_tiny_db_fixture_is_read_only(tiny_db):
    with pytest.raises(duckdb.Error):
        tiny_db.execute("INSERT INTO airports (iata) VALUES ('XXX')")


# ---------------------------------------------------------------------------
# 3. Tiny dataset: the seven airports
# ---------------------------------------------------------------------------

def test_tiny_db_has_seven_airports(tiny_db):
    codes = [r[0] for r in tiny_db.execute("SELECT iata FROM airports").fetchall()]
    assert sorted(codes) == sorted(TINY_AIRPORTS)


# ---------------------------------------------------------------------------
# 4. BTV has no delays, BHB is under 100,000 boardings
# ---------------------------------------------------------------------------

def test_tiny_db_btv_has_no_delays(tiny_db):
    n = tiny_db.execute(
        "SELECT count(*) FROM airport_delays WHERE iata = 'BTV'"
    ).fetchone()[0]
    assert n == 0


def test_tiny_db_bhb_under_100k(tiny_db):
    rows = tiny_db.execute(
        "SELECT year, enplanements FROM enplanements WHERE iata = 'BHB' ORDER BY year"
    ).fetchall()
    assert [r[0] for r in rows] == [2023, 2024, 2025]
    for year, value in rows:
        assert value < 100_000, f"BHB {year}: {value}"


# ---------------------------------------------------------------------------
# 5. realdata tests skip when the real database is missing
# ---------------------------------------------------------------------------
# Approach: run a separate pytest process on a small generated test file.
# * The generated file imports the project's `real_db` fixture with
#   `from tests.conftest import real_db`. PYTHONPATH holds the project root
#   (so `tests.conftest` and `app`/`loader` import) and `<root>/tests`
#   (so a conftest that does `from fixtures.tiny_data import ...` also works).
# * It runs in its own temp folder, so the project's pyproject/conftest are not
#   picked up twice; `-o markers=realdata` registers the marker there.
# * The subprocess starts with AIRPORTS_DB pointing to an EXISTING file, and an
#   autouse fixture switches it to a missing file with monkeypatch at test time.
#   So the skip only happens if `real_db` reads AIRPORTS_DB at test time.

def _run_inner_pytest(tmp_path, test_source, airports_db_at_start):
    test_file = tmp_path / "test_inner.py"
    test_file.write_text(textwrap.dedent(test_source), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(PROJECT_ROOT), str(PROJECT_ROOT / "tests")])
    env["AIRPORTS_DB"] = str(airports_db_at_start)
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", str(test_file),
            "-p", "no:cacheprovider", "-o", "markers=realdata", "-q", "-rs",
            "--rootdir", str(tmp_path),
        ],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result, result.stdout + result.stderr


def test_realdata_skips_without_db(tmp_path):
    existing = tmp_path / "exists.duckdb"
    existing.write_bytes(b"")  # exists at process start, so only a test-time read skips
    missing = tmp_path / "does_not_exist.duckdb"
    source = f"""
        import pytest
        from tests.conftest import real_db  # noqa: F401  (the project fixture)

        @pytest.fixture(autouse=True)
        def _point_to_missing_db(monkeypatch):
            monkeypatch.setenv("AIRPORTS_DB", {str(missing)!r})

        @pytest.mark.realdata
        def test_needs_real_db(real_db):
            assert False, "must be skipped, not run"
    """
    result, output = _run_inner_pytest(tmp_path, source, existing)
    assert re.search(r"\b1 skipped\b", output), output
    assert not re.search(r"\b\d+ (failed|errors?)\b", output), output
    assert result.returncode == 0, output


def test_realdata_runs_with_db(tmp_path):
    from tests.fixtures.tiny_data import build_tiny_db

    db_path = tmp_path / "tiny_as_real.duckdb"
    build_tiny_db(str(db_path))
    source = """
        import pytest
        from tests.conftest import real_db  # noqa: F401

        @pytest.mark.realdata
        def test_uses_real_db(real_db):
            assert real_db.execute("SELECT count(*) FROM airports").fetchone()[0] == 7
    """
    result, output = _run_inner_pytest(tmp_path, source, db_path)
    assert re.search(r"\b1 passed\b", output), output
    assert result.returncode == 0, output


# ---------------------------------------------------------------------------
# 6. Settings
# ---------------------------------------------------------------------------

def test_settings_read_from_environment(monkeypatch):
    # Import first, set the environment after: Settings must read it when created.
    from app.config import Settings

    monkeypatch.setenv("AIRPORTS_DB", "/tmp/some/airports_test.duckdb")
    monkeypatch.setenv("CHAT_DB", "/tmp/some/chat_test.sqlite")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-123")
    monkeypatch.setenv("OPENROUTER_MODEL", "some/model-name")
    monkeypatch.setenv("ALLOWED_ORIGIN", "https://example.vercel.app")

    s = Settings()
    assert str(s.airports_db) == "/tmp/some/airports_test.duckdb"
    assert str(s.chat_db) == "/tmp/some/chat_test.sqlite"
    assert s.openrouter_api_key == "sk-test-123"
    assert s.openrouter_model == "some/model-name"
    assert s.allowed_origin == "https://example.vercel.app"


def test_settings_defaults(monkeypatch):
    from app.config import Settings

    monkeypatch.delenv("AIRPORTS_DB", raising=False)
    monkeypatch.delenv("CHAT_DB", raising=False)
    s = Settings()
    assert str(s.airports_db) == "airports.duckdb"
    assert str(s.chat_db) == "chat.sqlite"


# ---------------------------------------------------------------------------
# 7. Python version
# ---------------------------------------------------------------------------

def test_python_is_3_12():
    assert sys.version_info[:2] == (3, 12)


# ---------------------------------------------------------------------------
# 8. Code comes from this folder, not an installed copy
# ---------------------------------------------------------------------------

def test_code_imported_from_current_folder():
    import app
    import loader

    assert (PROJECT_ROOT / "pyproject.toml").exists()
    for module in (app, loader):
        assert module.__file__ is not None, f"{module.__name__} needs an __init__.py"
        location = Path(module.__file__).resolve()
        assert location.is_relative_to(PROJECT_ROOT), location
        assert "site-packages" not in location.parts, location


# ---------------------------------------------------------------------------
# 9. Installed library versions match requirements.txt
# ---------------------------------------------------------------------------

def test_installed_versions_match_requirements():
    pinned = {}
    for raw in (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        assert "==" in line, f"not an exact version: {raw!r}"
        name, version = (part.strip() for part in line.split("==", 1))
        pinned[name] = version
    assert pinned, "requirements.txt lists no libraries"
    for name, version in pinned.items():
        assert importlib.metadata.version(name) == version, name


# ---------------------------------------------------------------------------
# Extra: pin every property of the tiny dataset (it is frozen after Step 0)
# ---------------------------------------------------------------------------

def test_tiny_db_airport_states_and_cities(tiny_db):
    rows = tiny_db.execute("SELECT iata, state, city FROM airports").fetchall()
    found = {iata: (state, city) for iata, state, city in rows}
    for code, (state, city) in TINY_AIRPORTS.items():
        assert found[code][0] == state, code
        if city is not None:
            assert found[code][1] == city, code


def test_tiny_db_bos_large_several_runways_two_airlines(tiny_db):
    size, runways = tiny_db.execute(
        "SELECT size_class, runway_count FROM airports WHERE iata = 'BOS'"
    ).fetchone()
    assert size == "large"
    assert runways > 1
    carriers = tiny_db.execute(
        "SELECT count(DISTINCT carrier) FROM route_traffic WHERE origin = 'BOS'"
    ).fetchone()[0]
    assert carriers >= 2


def test_tiny_db_sna_one_runway(tiny_db):
    runways = tiny_db.execute(
        "SELECT runway_count FROM airports WHERE iata = 'SNA'"
    ).fetchone()[0]
    assert runways == 1


def test_tiny_db_lax_has_international_passenger_route(tiny_db):
    n = tiny_db.execute(
        "SELECT count(*) FROM route_traffic "
        "WHERE origin = 'LAX' AND is_passenger AND dest_country <> 'US' AND departures > 0"
    ).fetchone()[0]
    assert n >= 1


def test_tiny_db_dest_country_uses_two_letter_us(tiny_db):
    # Domestic routes are written 'US' (T-100 DEST_COUNTRY, 2-letter code).
    values = {r[0] for r in tiny_db.execute(
        "SELECT DISTINCT dest_country FROM route_traffic").fetchall()}
    assert "US" in values
    assert all(isinstance(v, str) and len(v) == 2 for v in values), values


def test_tiny_db_anc_cargo_and_long_haul(tiny_db):
    cargo = tiny_db.execute(
        "SELECT count(*) FROM route_traffic "
        "WHERE origin = 'ANC' AND NOT is_passenger AND departures > 0 AND freight_lbs > 0"
    ).fetchone()[0]
    assert cargo >= 1
    long_haul = tiny_db.execute(
        "SELECT count(*) FROM route_traffic "
        "WHERE origin = 'ANC' AND is_passenger AND distance_mi >= 3000 AND departures > 0"
    ).fetchone()[0]
    assert long_haul >= 1


def test_tiny_db_is_passenger_matches_passengers(tiny_db):
    # is_passenger = "the flight carried at least one passenger" (schema.md).
    bad = tiny_db.execute(
        "SELECT count(*) FROM route_traffic WHERE is_passenger <> (passengers > 0)"
    ).fetchone()[0]
    assert bad == 0


def test_tiny_db_enplanements_all_years_and_sizes(tiny_db):
    rows = tiny_db.execute("SELECT iata, year, enplanements FROM enplanements").fetchall()
    years = {}
    for iata, year, value in rows:
        years.setdefault(iata, set()).add(year)
        if iata == "BHB":
            assert value < 100_000, (iata, year, value)
        else:
            assert value >= 100_000, (iata, year, value)
    for code in TINY_AIRPORTS:
        assert years.get(code) == {2023, 2024, 2025}, code


def test_tiny_db_route_traffic_years_and_months(tiny_db):
    years = {r[0] for r in tiny_db.execute(
        "SELECT DISTINCT year FROM route_traffic").fetchall()}
    assert {2019, 2024, 2025} <= years
    months_2025 = tiny_db.execute(
        "SELECT count(DISTINCT month) FROM route_traffic WHERE year = 2025"
    ).fetchone()[0]
    assert months_2025 >= 2


def test_tiny_db_every_airport_has_passenger_routes_each_year(tiny_db):
    # Needed so growth D1 (2019 -> 2025) and later year views work for all 7,
    # and so BTV's "no delay data" is the only thing missing for BTV.
    rows = tiny_db.execute(
        "SELECT origin, year, sum(passengers), sum(seats) FROM route_traffic "
        "WHERE is_passenger GROUP BY origin, year"
    ).fetchall()
    found = {(o, y): (p, s) for o, y, p, s in rows}
    for code in TINY_AIRPORTS:
        for year in (2019, 2024, 2025):
            assert (code, year) in found, (code, year)
            passengers, seats = found[(code, year)]
            assert passengers > 0 and seats > 0, (code, year)


def test_tiny_db_load_factor_month_over_85_and_under_80(tiny_db):
    # Load factor per airport-month = passengers / seats on departing
    # passenger rows of 2025. One airport needs a month > 0.85 and another
    # month < 0.80 (tests the 80-85% unmet demand range).
    rows = tiny_db.execute(
        "SELECT origin, month, sum(passengers) * 1.0 / sum(seats) FROM route_traffic "
        "WHERE year = 2025 AND is_passenger GROUP BY origin, month"
    ).fetchall()
    by_airport = {}
    for origin, month, lf in rows:
        by_airport.setdefault(origin, []).append(lf)
    matches = [a for a, lfs in by_airport.items()
               if any(lf > 0.85 for lf in lfs) and any(lf < 0.80 for lf in lfs)]
    assert matches, by_airport


def test_tiny_db_mht_grows_fastest_in_new_england(tiny_db):
    # D1 = (passengers 2025 - passengers 2019) / passengers 2019  (route_traffic, departing)
    # D2 = (enplanements 2025 - enplanements 2024) / enplanements 2024
    pax = dict(((o, y), p) for o, y, p in tiny_db.execute(
        "SELECT origin, year, sum(passengers) FROM route_traffic "
        "WHERE is_passenger GROUP BY origin, year").fetchall())
    enp = dict(((i, y), e) for i, y, e in tiny_db.execute(
        "SELECT iata, year, enplanements FROM enplanements").fetchall())

    def d1(code):
        return (pax[(code, 2025)] - pax[(code, 2019)]) / pax[(code, 2019)]

    def d2(code):
        return (enp[(code, 2025)] - enp[(code, 2024)]) / enp[(code, 2024)]

    for other in NEW_ENGLAND:
        if other == "MHT":
            continue
        assert d1("MHT") > d1(other), other
        assert d2("MHT") > d2(other), other


def test_tiny_db_delays_2025_both_directions_except_btv(tiny_db):
    rows = tiny_db.execute(
        "SELECT DISTINCT iata, direction FROM airport_delays WHERE year = 2025"
    ).fetchall()
    found = set(rows)
    for code in TINY_AIRPORTS:
        if code == "BTV":
            continue
        assert (code, "dep") in found, code
        assert (code, "arr") in found, code
    directions = {r[0] for r in tiny_db.execute(
        "SELECT DISTINCT direction FROM airport_delays").fetchall()}
    assert directions <= {"dep", "arr"}


def test_tiny_db_has_data_sources(tiny_db):
    # 4 sources: OurAirports, FAA enplanements, BTS T-100, BTS On-Time.
    n = tiny_db.execute("SELECT count(DISTINCT source) FROM data_sources").fetchone()[0]
    assert n >= 4


def test_tiny_data_md_exists():
    doc = PROJECT_ROOT / "tests" / "fixtures" / "TINY_DATA.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    for code in TINY_AIRPORTS:
        assert code in text, code


def test_tmp_chat_path_fixture(tmp_chat_path):
    path = Path(os.fspath(tmp_chat_path))
    assert path.parent.is_dir()
    assert not path.exists()
