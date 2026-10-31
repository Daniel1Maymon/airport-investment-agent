"""Step 1 tests: the `airports` table from OurAirports airports.csv + runways.csv.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `loader/airports.py`
    - `load_airports(airports_csv, runways_csv, con) -> LoadReport`
      writes the `airports` table (already made by `create_schema`).
      Returns `LoadReport(table="airports", rows=<rows in the table>, warnings=[...])`.
    - `faa_to_iata(airports_csv) -> dict[str, str]`: `local_code` -> `iata_code`.
    - `download_ourairports(dest_dir)` uses the network and is not tested here.
* Rules pinned here (docs/data-sources.md A, docs/schema.md `airports`,
  implementation plan P3 and P4):
    - keep only `iso_country = 'US'`, `scheduled_service = 'yes'`, non-empty `iata_code`;
    - `state` = `iso_region` without `US-`; `city` = `municipality`;
      `lat`/`lon` from `latitude_deg`/`longitude_deg`;
    - `size_class`: large_airport -> large, medium_airport -> medium,
      small_airport -> small, any other type (seaplane_base, heliport, ...) -> small;
    - runways join on `runways.airport_ident = airports.ident`; only OPEN runways
      (`closed = "0"`) count; `runway_count` and `longest_runway_ft` are NULL when
      an airport has no open runway (P3: NULL, not 0);
    - names cut to 100 characters (P4);
    - running the loader twice gives the same table, not double rows.

The sample files (tests/fixtures/raw/), row by row
--------------------------------------------------
airports_sample.csv (12 rows, 9 kept):
  KSFO/SFO   large, US-CA, 4 open runways + 1 CLOSED one that is the longest (12500)
  KLAX/LAX   large, US-CA, 2 open runways
  KSNA/SNA   medium, US-CA, name with a comma (CSV quoting), 1 runway
  KBOS/BOS   large, US-MA, 3 runways (longest 10083 is not listed first)
  KIWA/AZA   medium, US-AZ, local_code IWA != iata_code AZA, 1 runway
  TJSJ/SJU   PR territory (iso_country PR)           -> dropped
  KHWD/HWD   scheduled_service = no                  -> dropped
  KPAO/--    empty iata_code                         -> dropped
  5KE/WFB    seaplane_base with scheduled service, no runway rows at all
  KBHB/BHB   small, US-ME, its only runway is closed (no open runway)
  KMHT/MHT   medium, US-NH, name of 124 characters, 1 runway
  PANC/ANC   large, US-AK, 3 runways
"""

from pathlib import Path

import duckdb
import pytest

from loader.common import create_schema

RAW = Path(__file__).parent / "fixtures" / "raw"
AIRPORTS_CSV = RAW / "airports_sample.csv"
RUNWAYS_CSV = RAW / "runways_sample.csv"

# The 9 airports that pass the filter (US, scheduled service, IATA code).
KEPT = {"SFO", "LAX", "SNA", "BOS", "AZA", "WFB", "BHB", "MHT", "ANC"}


@pytest.fixture
def con(tmp_path):
    """A fresh, writable DuckDB with the empty tables of schema.md part 1."""
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    create_schema(c)
    yield c
    c.close()


def _load(con):
    from loader.airports import load_airports

    return load_airports(AIRPORTS_CSV, RUNWAYS_CSV, con)


def _row(con, iata, columns):
    return con.execute(f"SELECT {columns} FROM airports WHERE iata = ?", [iata]).fetchone()


def _codes(con):
    return {r[0] for r in con.execute("SELECT iata FROM airports").fetchall()}


# 1
def test_keeps_only_us_scheduled_with_iata(con):
    report = _load(con)
    # 12 rows - SJU (PR) - HWD (no scheduled service) - KPAO (empty IATA) = 9
    assert _codes(con) == KEPT
    assert "HWD" not in _codes(con)  # scheduled_service = no
    assert con.execute("SELECT count(*) FROM airports WHERE iata IS NULL OR iata = ''").fetchone()[0] == 0  # KPAO
    assert report.table == "airports"
    assert report.rows == 9  # rows in the table, see above
    assert isinstance(report.warnings, list)


def test_city_and_location_copied(con):
    _load(con)
    name, city, lat, lon = _row(con, "SFO", "name, city, lat, lon")
    assert name == "San Francisco International Airport"
    assert city == "San Francisco"  # municipality
    assert lat == pytest.approx(37.619)  # latitude_deg
    assert lon == pytest.approx(-122.375)  # longitude_deg
    # name with a comma, quoted in the CSV
    assert _row(con, "SNA", "name")[0] == "John Wayne Airport, Orange County"


# 2
def test_territory_dropped(con):
    _load(con)
    # TJSJ/SJU has iso_country PR, scheduled, has IATA -> still dropped
    assert "SJU" not in _codes(con)
    assert con.execute("SELECT count(*) FROM airports WHERE state LIKE 'PR%'").fetchone()[0] == 0


# 3
def test_state_from_iso_region(con):
    _load(con)
    assert _row(con, "SFO", "state")[0] == "CA"  # US-CA -> CA
    assert _row(con, "BOS", "state")[0] == "MA"  # US-MA -> MA
    assert _row(con, "ANC", "state")[0] == "AK"  # US-AK -> AK
    # no state keeps the "US-" prefix
    assert con.execute("SELECT count(*) FROM airports WHERE state LIKE 'US-%'").fetchone()[0] == 0


# 4
def test_size_class_from_type(con):
    _load(con)
    assert _row(con, "SFO", "size_class")[0] == "large"  # large_airport
    assert _row(con, "SNA", "size_class")[0] == "medium"  # medium_airport
    assert _row(con, "BHB", "size_class")[0] == "small"  # small_airport
    assert _row(con, "WFB", "size_class")[0] == "small"  # seaplane_base -> small (decided)
    # only the three labels ever appear
    sizes = {r[0] for r in con.execute("SELECT DISTINCT size_class FROM airports").fetchall()}
    assert sizes == {"large", "medium", "small"}


# 5
def test_counts_open_runways_only(con):
    _load(con)
    assert _row(con, "SFO", "runway_count")[0] == 4  # KSFO: 5 runways, 1 closed -> 4
    assert _row(con, "LAX", "runway_count")[0] == 2  # KLAX: 2 open
    assert _row(con, "BOS", "runway_count")[0] == 3  # KBOS: 3 open
    assert _row(con, "ANC", "runway_count")[0] == 3  # PANC: 3 open
    assert _row(con, "SNA", "runway_count")[0] == 1  # KSNA: 1 open
    # AZA's runways are found through ident KIWA, not the IATA code
    assert _row(con, "AZA", "runway_count")[0] == 1  # KIWA: 1 open


# 6
def test_longest_runway_ft(con):
    _load(con)
    # KSFO open: 11870, 10602, 8650, 7650; the CLOSED 12500 is ignored -> 11870
    assert _row(con, "SFO", "longest_runway_ft")[0] == 11870
    # KBOS: 10083, 7861, 10005 -> 10083
    assert _row(con, "BOS", "longest_runway_ft")[0] == 10083
    # PANC: 12400, 11584, 10960 -> 12400
    assert _row(con, "ANC", "longest_runway_ft")[0] == 12400
    # KIWA (IATA AZA): 10401
    assert _row(con, "AZA", "longest_runway_ft")[0] == 10401


# 7
def test_no_runways_gives_null(con):
    _load(con)
    # 5KE/WFB: no runway rows at all -> NULL, NULL (P3: NULL, not 0)
    assert _row(con, "WFB", "runway_count, longest_runway_ft") == (None, None)
    # KBHB/BHB: its only runway is closed -> no open runway -> NULL, NULL
    assert _row(con, "BHB", "runway_count, longest_runway_ft") == (None, None)


# 8
def test_long_name_cut_to_100(con):
    _load(con)
    name = _row(con, "MHT", "name")[0]
    # the sample name is 124 characters; its first 100 are:
    expected = "Manchester-Boston Regional Airport, also known by a very long made-up name that goes on past the one"
    assert len(expected) == 100
    assert name == expected
    # short names are left as they are
    assert _row(con, "BOS", "name")[0] == "Logan International Airport"
    assert con.execute("SELECT max(length(name)) FROM airports").fetchone()[0] == 100


# 9
def test_faa_to_iata_translation():
    from loader.airports import faa_to_iata

    table = faa_to_iata(AIRPORTS_CSV)
    assert isinstance(table, dict)
    assert table["IWA"] == "AZA"  # KIWA: local_code IWA, iata_code AZA
    assert table["SFO"] == "SFO"  # local_code = iata_code
    assert table["BOS"] == "BOS"
    assert "AZA" not in table  # keys are FAA codes (local_code), not IATA codes


# 10
def test_rerun_replaces_rows(con):
    _load(con)
    first = con.execute("SELECT * FROM airports ORDER BY iata").fetchall()
    report = _load(con)
    second = con.execute("SELECT * FROM airports ORDER BY iata").fetchall()
    assert second == first  # same table
    assert len(second) == 9  # not 18
    assert report.rows == 9
