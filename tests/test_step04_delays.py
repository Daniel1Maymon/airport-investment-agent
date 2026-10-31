"""Step 4 tests: the BTS On-Time files and the `airport_delays` table.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `loader/delays.py`
    - `download_ontime(year, month, dest_dir) -> Path` uses the network; not tested
      here. It saves `dest_dir/ontime_{year}_{month}.zip`.
    - `load_airport_delays(zip_paths, con) -> LoadReport` opens each zip, finds the
      data file by its `.csv` ending (the zip also holds `readme.html`, which must be
      ignored, and it may come first), and REPLACES the contents of the
      `airport_delays` table (already made by `create_schema`, column types
      unchanged; running twice gives the same table).
      Returns `LoadReport(table="airport_delays", rows=<rows in the table>, warnings=[...])`.
      A missing required column raises a clear error that names the column, and the
      table is left as it was (so the columns are checked BEFORE the old rows are
      deleted).
* Rules pinned here (docs/data-sources.md D, docs/schema.md `airport_delays`,
  docs/decisions.md 7.6 and 7.7):
    - one row per airport x year x month x direction. A flight counts at its
      `Origin` as a `dep` row and at its `Dest` as an `arr` row. Year and month come
      from the `Year` and `Month` columns, never from a file name.
    - `flights` = every flight, cancelled and diverted ones included.
    - `cancelled` = flights with Cancelled = 1.
    - `delayed_15`: on `dep` rows the flights with DepDel15 = 1; on `arr` rows the
      flights with ArrDel15 = 1. (Empty DepDel15/ArrDel15, as on cancelled and
      diverted flights, is not delayed.)
    - `avg_taxi_min`: on `dep` rows the average TaxiOut, on `arr` rows the average
      TaxiIn, over the flights that HAVE a value. Cancelled flights have none and
      are skipped (not counted as 0). A diverted flight that has a TaxiIn counts.
      If no flight in the group has a value, `avg_taxi_min` is NULL.
    - cause minutes (`nas_delay_min` <- NASDelay, `carrier_delay_min` <- CarrierDelay,
      `weather_delay_min` <- WeatherDelay, `late_aircraft_delay_min` <-
      LateAircraftDelay, `security_delay_min` <- SecurityDelay): on `arr` rows the
      SUM over the arriving flights; 0 (not NULL) when none of them has cause
      minutes. On `dep` rows all five are NULL.
    - "only our airports": the airport must be in the `airports` table already in
      `con`. Each side is checked on its own: a flight from an unlisted airport to a
      listed one still counts in the listed airport's `arr` row; only the unlisted
      side is dropped. Airports in the table with no flights get no rows.
    - `CODE_RENAMES` from `loader/common.py` is applied to Origin and Dest BEFORE the
      filter, so Palm Beach flights written `PBI` are stored as `DJT` and kept.

The sample files
----------------
* `tests/fixtures/raw/ontime_sample.zip`: 28 made-up flights (F1-F28) in January
  and February 2025, in the real format, built by
  `tests/fixtures/make_ontime_sample.py`. Every flight and the hand-worked totals
  are in tests/fixtures/TINY_DATA.md, "Step 4 sample: ontime_sample.zip".
* Other zips (one month each, readme.html first, a column missing) are built in
  tmp_path with the same writer, so they have the same format.
* Our airports (inserted by each test): JFK, LAX, BOS, DJT, SFO. Not in the list:
  PSE (Ponce, Puerto Rico; territories are out of scope) and PBI (renamed to DJT).

Each test imports `loader.delays` itself, so before the builder starts every test
fails on its own with ModuleNotFoundError.
"""

from pathlib import Path

import duckdb
import pytest

from loader.common import CODE_RENAMES, create_schema
from tests.fixtures.make_ontime_sample import FLIGHTS, HEADER, write_ontime_zip

RAW = Path(__file__).parent / "fixtures" / "raw"
SAMPLE_ZIP = RAW / "ontime_sample.zip"

DJT = CODE_RENAMES["PBI"]  # Palm Beach's current code (decisions 7.6)
OUR_AIRPORTS = ["JFK", "LAX", "BOS", DJT, "SFO"]  # SFO has no sample flights

CAUSES = ["nas_delay_min", "carrier_delay_min", "weather_delay_min",
          "late_aircraft_delay_min", "security_delay_min"]

# Hand-worked rows, from the flight list in TINY_DATA.md.
# (iata, month, direction): (flights, cancelled, delayed_15, avg_taxi_min)
# The math is written next to each row: flights, then taxi values (cancelled skipped).
EXPECTED = {
    # ---- January ----
    # F1 F2 F3 F4(canc) F5 F12 F14 = 7; delayed F3, F12; taxi-out 20+30+40+10+35+24 = 159 / 6
    ("JFK", 1, "dep"): (7, 1, 2, 26.5),
    # F6 F7(canc) F15 = 3; F6 left 5 min late (not delayed); taxi-out 25+20 = 45 / 2
    ("BOS", 1, "dep"): (3, 1, 0, 22.5),
    # F8 F9(diverted) F10 = 3; delayed F10; taxi-out 18+14+22 = 54 / 3
    ("LAX", 1, "dep"): (3, 0, 1, 18.0),
    # F13 (written PBI) = 1; taxi-out 16
    (DJT, 1, "dep"): (1, 0, 0, 16.0),
    # F1 F2 F3 F4(canc) F15 = 5; delayed F3; taxi-in 10+6+8+10 = 34 / 4
    ("LAX", 1, "arr"): (5, 1, 1, 8.5),
    # F5 F10 = 2; delayed F10; taxi-in 4+7 = 11 / 2
    ("BOS", 1, "arr"): (2, 0, 1, 5.5),
    # F6 F7(canc) F8 F9(diverted) F11(from PSE) F13(from PBI) = 6; delayed F6;
    # taxi-in 12+9+15+11+13 = 60 / 5 (F9's 15 counts)
    ("JFK", 1, "arr"): (6, 1, 1, 12.0),
    # F14 (written PBI) = 1; delayed; taxi-in 6
    (DJT, 1, "arr"): (1, 0, 1, 6.0),
    # ---- February ----
    # F16 F17(canc) F18 F22 F23(canc) = 5; delayed F18, F22; taxi-out 25+45+20 = 90 / 3
    ("JFK", 2, "dep"): (5, 2, 2, 30.0),
    # F19 F20 F28(canc) = 3; taxi-out 15+17 = 32 / 2
    ("LAX", 2, "dep"): (3, 1, 0, 16.0),
    # F21 F26(canc) F27 = 3; delayed F27; taxi-out 19+30 = 49 / 2
    ("BOS", 2, "dep"): (3, 1, 1, 24.5),
    # F25 (written PBI) = 1; taxi-out 14
    (DJT, 2, "dep"): (1, 0, 0, 14.0),
    # F16 F17(canc) F18 F27 = 4; delayed F18, F27; taxi-in 5+15+10 = 30 / 3
    ("LAX", 2, "arr"): (4, 1, 2, 10.0),
    # F19 F20 F21 F24(from PSE) F28(canc) = 5; delayed F24; taxi-in 7+9+11+20 = 47 / 4
    ("JFK", 2, "arr"): (5, 1, 1, 11.75),
    # F22 F23(canc) F25(from PBI) = 3; F22 arrived only 10 min late; taxi-in 3+8 = 11 / 2
    ("BOS", 2, "arr"): (3, 1, 0, 5.5),
    # F26 (to PBI, cancelled) = 1; no taxi value at all -> NULL
    (DJT, 2, "arr"): (1, 1, 0, None),
}

# Cause minutes on arr rows: (nas, carrier, weather, late_aircraft, security), summed.
EXPECTED_CAUSES = {
    ("LAX", 1): (20, 100, 0, 0, 0),    # F3: carrier 100 + NAS 20 = its 120 min arrival delay
    ("BOS", 1): (10, 0, 50, 15, 5),    # F10: weather 50, NAS 10, security 5, late aircraft 15
    ("JFK", 1): (30, 0, 0, 0, 0),      # F6: NAS 30 (F9 diverted has no causes)
    (DJT, 1): (0, 0, 0, 40, 0),        # F14: late aircraft 40
    ("LAX", 2): (60, 45, 0, 30, 0),    # F18: NAS 60 + late aircraft 30; F27: carrier 45
    ("JFK", 2): (0, 0, 25, 0, 0),      # F24 (from PSE): weather 25
    ("BOS", 2): (0, 0, 0, 0, 0),       # nobody arrived 15+ min late -> 0, not NULL
    (DJT, 2): (0, 0, 0, 0, 0),         # only a cancelled flight -> 0, not NULL
}

ROW_COUNT = 16  # 4 airports x 2 months x 2 directions


@pytest.fixture
def con(tmp_path):
    """A fresh, writable DuckDB with the empty tables, and our sample airports."""
    c = duckdb.connect(str(tmp_path / "x.duckdb"))
    create_schema(c)
    for code in OUR_AIRPORTS:
        c.execute("INSERT INTO airports (iata, name, state) VALUES (?, ?, ?)", [code, f"{code} airport", "XX"])
    yield c
    c.close()


def _load(paths, con):
    from loader.delays import load_airport_delays

    return load_airport_delays([Path(p) for p in paths], con)


def _rows(con):
    """{(iata, month, direction): (flights, cancelled, delayed_15, avg_taxi_min)}"""
    return {
        (r[0], r[1], r[2]): (r[3], r[4], r[5], r[6])
        for r in con.execute(
            "SELECT iata, month, direction, flights, cancelled, delayed_15, avg_taxi_min FROM airport_delays"
        ).fetchall()
    }


def _all(con):
    return sorted(con.execute("SELECT * FROM airport_delays").fetchall())


def _one(con, sql, params=None):
    return con.execute(sql, params or []).fetchone()


# 1
def test_unzips_and_reads(con, tmp_path):
    report = _load([SAMPLE_ZIP], con)
    assert report.table == "airport_delays"
    assert report.rows == _one(con, "SELECT count(*) FROM airport_delays")[0] == ROW_COUNT

    # The loader writes into the table create_schema made: types unchanged.
    types = {r[0]: r[1] for r in con.execute("DESCRIBE airport_delays").fetchall()}
    assert types == {
        "iata": "VARCHAR", "year": "INTEGER", "month": "INTEGER", "direction": "VARCHAR",
        "flights": "BIGINT", "cancelled": "BIGINT", "delayed_15": "BIGINT", "avg_taxi_min": "DOUBLE",
        "nas_delay_min": "DOUBLE", "carrier_delay_min": "DOUBLE", "weather_delay_min": "DOUBLE",
        "late_aircraft_delay_min": "DOUBLE", "security_delay_min": "DOUBLE",
    }

    # readme.html FIRST in the zip: the CSV must be found by its .csv ending,
    # not by its place in the zip. Same 28 flights -> same 16 rows.
    readme_first = write_ontime_zip(tmp_path / "readme_first.zip", FLIGHTS, readme_first=True)
    first = _all(con)
    _load([readme_first], con)
    assert _all(con) == first


# 2
def test_one_row_per_airport_month_direction(con):
    _load([SAMPLE_ZIP], con)
    keys = con.execute("SELECT iata, year, month, direction FROM airport_delays").fetchall()
    # No key twice.
    assert len(keys) == len(set(keys)) == ROW_COUNT
    # Exactly the 16 hand-worked keys, all in 2025. SFO (no flights), PSE (not ours)
    # and PBI (renamed) have no rows.
    assert set(keys) == {(k[0], 2025, k[1], k[2]) for k in EXPECTED}
    assert {r[0] for r in con.execute("SELECT DISTINCT direction FROM airport_delays").fetchall()} == {"dep", "arr"}


# 3
def test_departure_flight_count(con):
    _load([SAMPLE_ZIP], con)
    got = {k: v[0] for k, v in _rows(con).items() if k[2] == "dep"}
    assert got == {k: v[0] for k, v in EXPECTED.items() if k[2] == "dep"}
    # All dep rows: 7+3+3+1 (Jan) + 5+3+3+1 (Feb) = 26
    # = 28 flights minus the 2 that left from PSE (F11, F24).
    assert _one(con, "SELECT sum(flights) FROM airport_delays WHERE direction = 'dep'")[0] == 26


# 4
def test_arrival_flight_count(con):
    _load([SAMPLE_ZIP], con)
    got = {k: v[0] for k, v in _rows(con).items() if k[2] == "arr"}
    assert got == {k: v[0] for k, v in EXPECTED.items() if k[2] == "arr"}
    # All arr rows: 5+2+6+1 (Jan) + 4+5+3+1 (Feb) = 27
    # = 28 flights minus the 1 that went to PSE (F12). Cancelled F4 and diverted F9 count.
    assert _one(con, "SELECT sum(flights) FROM airport_delays WHERE direction = 'arr'")[0] == 27


# 5
def test_cancelled_counted(con):
    _load([SAMPLE_ZIP], con)
    got = {k: v[1] for k, v in _rows(con).items()}
    assert got == {k: v[1] for k, v in EXPECTED.items()}
    # 6 cancelled flights (F4 F7 F17 F23 F26 F28), all between our airports, so each
    # counts once on a dep row and once on an arr row: 6 x 2 = 12.
    assert _one(con, "SELECT sum(cancelled) FROM airport_delays")[0] == 12
    # Cancelled flights are still in `flights`: JFK Feb dep has 5 flights, 2 of them cancelled.
    assert _one(con, "SELECT flights, cancelled FROM airport_delays"
                     " WHERE iata = 'JFK' AND month = 2 AND direction = 'dep'") == (5, 2)


# 6
def test_delayed_15_counted(con):
    _load([SAMPLE_ZIP], con)
    got = {k: v[2] for k, v in _rows(con).items()}
    assert got == {k: v[2] for k, v in EXPECTED.items()}
    # dep: DepDel15 = 1 on F3 F10 F12 F18 F22 F27 = 6 (all leave from our airports).
    assert _one(con, "SELECT sum(delayed_15) FROM airport_delays WHERE direction = 'dep'")[0] == 6
    # arr: ArrDel15 = 1 on F3 F6 F10 F12 F14 F18 F24 F27 = 8, minus F12 (to PSE) = 7.
    assert _one(con, "SELECT sum(delayed_15) FROM airport_delays WHERE direction = 'arr'")[0] == 7
    # F6 left 5 min late but arrived 30 min late: delayed on arrival only.
    # F22 left 20 min late but arrived 10 min late: delayed on departure only.
    assert _rows(con)[("BOS", 1, "dep")][2] == 0 and _rows(con)[("JFK", 1, "arr")][2] == 1
    assert _rows(con)[("JFK", 2, "dep")][2] == 2 and _rows(con)[("BOS", 2, "arr")][2] == 0


# 7
def test_avg_taxi_skips_cancelled(con):
    _load([SAMPLE_ZIP], con)
    got = _rows(con)
    for key, (_, _, _, taxi) in EXPECTED.items():
        if taxi is None:
            assert got[key][3] is None, key
        else:
            assert got[key][3] == pytest.approx(taxi), key
    # Counting cancelled F4 as 0 would give JFK Jan dep 159 / 7 = 22.71, not 26.5.
    assert got[("JFK", 1, "dep")][3] == pytest.approx(26.5)
    # Diverted F9 has a taxi-in of 15 and counts: 60 / 5 = 12 (without it 45 / 4 = 11.25).
    assert got[("JFK", 1, "arr")][3] == pytest.approx(12.0)
    # Palm Beach Feb arr: only cancelled F26 -> no value -> NULL (not 0).
    assert got[(DJT, 2, "arr")][3] is None


# 8
def test_cause_minutes_only_on_arrival_rows(con):
    _load([SAMPLE_ZIP], con)
    cols = ", ".join(CAUSES)
    # dep rows: all five cause columns are NULL, on all 8 dep rows.
    dep = con.execute(f"SELECT {cols} FROM airport_delays WHERE direction = 'dep'").fetchall()
    assert len(dep) == 8 and all(v is None for row in dep for v in row)
    # arr rows: the hand-worked sums (0, not NULL, where nobody was 15+ min late).
    arr = {
        (r[0], r[1]): tuple(r[2:])
        for r in con.execute(f"SELECT iata, month, {cols} FROM airport_delays WHERE direction = 'arr'").fetchall()
    }
    assert arr == {k: tuple(float(x) for x in v) for k, v in EXPECTED_CAUSES.items()}
    # Table-wide totals (a leak onto dep rows or from F12 to PSE would change them):
    # NAS 20+10+30+60 = 120; carrier 100+45 = 145 (not 205: F12's 60 went to PSE);
    # weather 50+25 = 75; late aircraft 15+40+30 = 85; security 5.
    assert _one(con, f"SELECT {', '.join(f'sum({c})' for c in CAUSES)} FROM airport_delays") == (
        120.0, 145.0, 75.0, 85.0, 5.0)


# 9
def test_airport_not_in_list_skipped(con):
    _load([SAMPLE_ZIP], con)
    # PSE is not in our airports table: no PSE rows at all.
    assert _one(con, "SELECT count(*) FROM airport_delays WHERE iata = 'PSE'")[0] == 0
    # ... but the OTHER side of its flights is kept:
    # F11 PSE -> JFK counts in JFK's Jan arr row (6 flights: F6 F7 F8 F9 F11 F13).
    assert _rows(con)[("JFK", 1, "arr")][0] == 6
    # F12 JFK -> PSE counts in JFK's Jan dep row (7 flights: F1 F2 F3 F4 F5 F12 F14),
    # and its late departure is counted (delayed F3, F12 = 2).
    assert _rows(con)[("JFK", 1, "dep")][:3] == (7, 1, 2)
    # F24 PSE -> JFK arrived 25 min late (weather): JFK Feb arr has it.
    assert _one(con, "SELECT flights, delayed_15, weather_delay_min FROM airport_delays"
                     " WHERE iata = 'JFK' AND month = 2 AND direction = 'arr'") == (5, 1, 25.0)
    # SFO is ours but has no flights: no rows.
    assert _one(con, "SELECT count(*) FROM airport_delays WHERE iata = 'SFO'")[0] == 0
    # Every code in the table is in our airports list (decisions 7.7 check).
    assert {r[0] for r in con.execute("SELECT DISTINCT iata FROM airport_delays").fetchall()} == {
        "JFK", "LAX", "BOS", DJT}


# 10
def test_two_months_loaded(con, tmp_path):
    _load([SAMPLE_ZIP], con)
    per_month = dict(con.execute(
        "SELECT month, sum(flights) FROM airport_delays GROUP BY month").fetchall())
    # January: 14 dep (15 flights - F11 from PSE) + 14 arr (15 - F12 to PSE) = 28.
    # February: 12 dep (13 flights - F24 from PSE) + 13 arr = 25.
    assert per_month == {1: 28, 2: 25}
    combined = _all(con)

    # Real downloads are one zip per month. Two single-month zips, loaded together,
    # give exactly the same table as the combined sample.
    jan = write_ontime_zip(tmp_path / "ontime_2025_1.zip", [f for f in FLIGHTS if f[1] == 1], 2025, 1)
    feb = write_ontime_zip(tmp_path / "ontime_2025_2.zip", [f for f in FLIGHTS if f[1] == 2], 2025, 2)
    _load([jan, feb], con)
    assert _all(con) == combined


# 11 (added)
def test_palm_beach_pbi_stored_as_djt(con):
    assert CODE_RENAMES["PBI"] == "DJT"
    _load([SAMPLE_ZIP], con)
    # The file says PBI (F13 F14 F25 F26); the table says DJT, and the flights are kept.
    assert _one(con, "SELECT count(*) FROM airport_delays WHERE iata = 'PBI'")[0] == 0
    djt = {k: v[:3] for k, v in _rows(con).items() if k[0] == DJT}
    assert djt == {
        (DJT, 1, "dep"): (1, 0, 0),  # F13 PBI -> JFK
        (DJT, 1, "arr"): (1, 0, 1),  # F14 JFK -> PBI, 40 min late
        (DJT, 2, "dep"): (1, 0, 0),  # F25 PBI -> BOS
        (DJT, 2, "arr"): (1, 1, 0),  # F26 BOS -> PBI, cancelled
    }
    # F14's late-aircraft minutes land on DJT's Jan arr row.
    assert _one(con, "SELECT late_aircraft_delay_min FROM airport_delays"
                     " WHERE iata = ? AND month = 1 AND direction = 'arr'", [DJT])[0] == 40.0


# 12 (added)
def test_rerun_replaces_rows(con):
    _load([SAMPLE_ZIP], con)
    first = _all(con)
    _load([SAMPLE_ZIP], con)
    # Still 16 rows and 53 flights (26 dep + 27 arr), not 32 and 106: the second run REPLACES.
    assert _one(con, "SELECT count(*), sum(flights) FROM airport_delays") == (ROW_COUNT, 53)
    assert _all(con) == first


# 13 (added)
def test_missing_column_fails_loudly(con, tmp_path):
    from loader.delays import load_airport_delays

    _load([SAMPLE_ZIP], con)
    before = _all(con)
    # A file without the NASDelay column (header and every row).
    header = [h for h in HEADER if h != "NASDelay"]
    bad_zip = write_ontime_zip(tmp_path / "no_nas.zip", FLIGHTS, header=header)
    with pytest.raises(Exception, match="NASDelay"):
        load_airport_delays([bad_zip], con)
    # The table is left as it was: still 16 rows, 53 flights, same values.
    assert _one(con, "SELECT count(*), sum(flights) FROM airport_delays") == (ROW_COUNT, 53)
    assert _all(con) == before
