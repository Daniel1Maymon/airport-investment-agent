"""Step 3 tests: the BTS T-100 form page and the `route_traffic` table.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `loader/route_traffic.py`
    - `parse_hidden_fields(html: str) -> dict` returns every hidden ASP.NET field
      whose name starts with `__` (`__VIEWSTATE`, `__EVENTVALIDATION`,
      `__VIEWSTATEGENERATOR`, `__EVENTTARGET`, ...) mapped to its value. Other inputs
      (checkboxes, text boxes) are not returned. Raises a clear error naming
      `__VIEWSTATE` when the page has no `__VIEWSTATE` field (the BTS page changed).
    - `download_t100(year, dest_dir) -> Path` uses the network; not tested here.
    - `load_route_traffic(zip_paths, con) -> LoadReport` reads
      `T_T100_SEGMENT_ALL_CARRIER.csv` inside each zip (the zip also holds
      `Documentation.csv`, which must be ignored), writes the `route_traffic` table
      (already made by `create_schema`, column types unchanged) and REPLACES its
      contents (running twice gives the same table).
      Returns `LoadReport(table="route_traffic", rows=<rows in the table>, warnings=[...])`.
      A missing required column raises a clear error that names the column.
* Rules pinned here (docs/data-sources.md C, docs/schema.md `route_traffic`,
  docs/decisions.md 7.7, implementation plan P6):
    - DEPARTURES_PERFORMED -> departures (NOT DEPARTURES_SCHEDULED), SEATS -> seats,
      PASSENGERS -> passengers, FREIGHT -> freight_lbs, DISTANCE -> distance_mi,
      UNIQUE_CARRIER -> carrier, CARRIER_NAME -> carrier_name, ORIGIN -> origin,
      DEST -> dest, DEST_COUNTRY -> dest_country, AIRCRAFT_TYPE -> aircraft_type,
      YEAR -> year, MONTH -> month;
    - is_passenger = PASSENGERS > 0 (not seats > 0);
    - foreign airports (HKG, NRT) are kept: no foreign keys (7.7);
    - fully identical rows are BOTH kept: the table has no primary key.

The sample files
----------------
* `tests/fixtures/raw/t100_sample.zip`: 20 made-up 2025 rows in the real format,
  built by `tests/fixtures/make_t100_sample.py`. Every row and the hand-worked
  totals are in tests/fixtures/TINY_DATA.md, "Step 3 sample: t100_sample.zip".
* `tests/fixtures/raw/bts_form_sample.html`: a short piece of the form page.
* Other zips (a column missing, a 2024 file) are built in tmp_path with the same
  writer, so they have the same format.

Each test imports `loader.route_traffic` itself, so before the builder starts
every test fails on its own with ModuleNotFoundError.
"""

from pathlib import Path

import duckdb
import pytest

from loader.common import create_schema
from tests.fixtures.make_t100_sample import HEADER, SAMPLE_ROWS, write_t100_zip

RAW = Path(__file__).parent / "fixtures" / "raw"
SAMPLE_ZIP = RAW / "t100_sample.zip"
FORM_HTML = RAW / "bts_form_sample.html"

# Hand-worked totals of the 20 sample rows (see TINY_DATA.md).
SAMPLE_ROW_COUNT = 20
# 800 + 900 + 2,500 + 2,400 + 1,200 + 1,300 + 0 + 0 + 0 + 30 + 600 + 600 + 0
# + 700 + 800 + 900 + 1,500 + 1,600 + 0 + 400 = 16,230
SAMPLE_PASSENGERS = 16230


@pytest.fixture
def con(tmp_path):
    """A fresh, writable DuckDB with the empty tables of schema.md part 1."""
    c = duckdb.connect(str(tmp_path / "x.duckdb"))
    create_schema(c)
    yield c
    c.close()


def _load(paths, con):
    from loader.route_traffic import load_route_traffic

    return load_route_traffic([Path(p) for p in paths], con)


def _one(con, sql, params=None):
    return con.execute(sql, params or []).fetchone()


# 1
def test_parse_hidden_fields():
    from loader.route_traffic import parse_hidden_fields

    html = FORM_HTML.read_text(encoding="utf-8")
    # The six hidden inputs of the sample page, copied by hand. The checkboxes,
    # the text box, the select and the submit button must not come back.
    assert parse_hidden_fields(html) == {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": "2hnAwVl/DByM+Wq66fap7z==",
        "__VIEWSTATEGENERATOR": "82CE8F70",
        "__EVENTVALIDATION": "y6vyuRa5rr7c+/Ab=",
    }


# 2
def test_page_without_viewstate_fails_loudly():
    from loader.route_traffic import parse_hidden_fields

    # __VIEWSTATEGENERATOR contains the text "__VIEWSTATE", so a loose text search
    # would wrongly pass; only a real __VIEWSTATE field counts.
    html = (
        '<form method="post" id="form1">\n'
        '<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" />\n'
        '<input type="hidden" name="__VIEWSTATEGENERATOR" id="__VIEWSTATEGENERATOR" value="82CE8F70" />\n'
        '<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="y6vyuRa5rr7c+/Ab=" />\n'
        '<input type="checkbox" name="DEPARTURES_PERFORMED" id="DEPARTURES_PERFORMED" />\n'
        "</form>\n"
    )
    with pytest.raises(Exception, match="__VIEWSTATE"):
        parse_hidden_fields(html)


# 3
def test_reads_csv_inside_zip(con):
    # The zip holds Documentation.csv (19 field rows) first, then the data CSV
    # (20 rows). Reading the right member gives exactly 20 rows.
    _load([SAMPLE_ZIP], con)
    assert _one(con, "SELECT count(*) FROM route_traffic")[0] == SAMPLE_ROW_COUNT
    # Sample origins written by hand from R1-R20.
    origins = {r[0] for r in con.execute("SELECT DISTINCT origin FROM route_traffic").fetchall()}
    assert origins == {"BOS", "JFK", "LAX", "SNA", "SFO", "ANC", "HKG", "CPX", "FAI", "ORD", "SJC", "SEA"}


# 4
def test_columns_mapped(con):
    _load([SAMPLE_ZIP], con)

    # R5: DEPARTURES_SCHEDULED 12.00 but DEPARTURES_PERFORMED 10.00 -> departures 10 (P6).
    row = _one(
        con,
        "SELECT year, month, origin, dest, dest_country, carrier, carrier_name, aircraft_type,"
        " departures, seats, passengers, freight_lbs, distance_mi, is_passenger"
        " FROM route_traffic WHERE origin = 'SNA' AND dest = 'SFO'",
    )
    assert row == (2025, 2, "SNA", "SFO", "US", "AS", "Alaska Airlines Inc.", 698,
                   10, 1500, 1200, 500.0, 372.0, True)

    # Departures performed over all rows:
    # 10+10+20+20+10+10+5+5+4+2+8+8+0+6+6+4+12+12+3+5 = 160
    # (DEPARTURES_SCHEDULED would give 162, because R5 has 12 instead of 10).
    assert _one(con, "SELECT sum(departures) FROM route_traffic")[0] == 160
    # Seats: 1000+1000+3000+3000+1500+1500+0+0+0+40+800+800+0+900+900+1000+1800+1800+300+500 = 19,840
    assert _one(con, "SELECT sum(seats) FROM route_traffic")[0] == 19840
    # Freight: 500 (R5) + 100,000 (R7) + 80,000 (R8) + 40,000 (R9) + 2,000 (R16) = 222,500
    assert _one(con, "SELECT sum(freight_lbs) FROM route_traffic")[0] == 222500.0

    # The quoted carrier name with a comma is read whole (R10).
    assert _one(con, "SELECT carrier, carrier_name, distance_mi FROM route_traffic WHERE origin = 'CPX'") == (
        "F4", "Air Charter, Inc d/b/a Air Flamenco", 17.0)

    # The loader writes into the table create_schema made: types unchanged.
    types = {r[0]: r[1] for r in con.execute("DESCRIBE route_traffic").fetchall()}
    assert types == {
        "year": "INTEGER", "month": "INTEGER", "origin": "VARCHAR", "dest": "VARCHAR",
        "dest_country": "VARCHAR", "carrier": "VARCHAR", "carrier_name": "VARCHAR",
        "aircraft_type": "INTEGER", "departures": "BIGINT", "seats": "BIGINT",
        "passengers": "BIGINT", "freight_lbs": "DOUBLE", "distance_mi": "DOUBLE",
        "is_passenger": "BOOLEAN",
    }


# 5
def test_is_passenger_when_passengers_over_zero(con):
    _load([SAMPLE_ZIP], con)
    # Passengers > 0: R1-R6, R10, R11, R12, R14-R18, R20 = 6 + 3 + 5 + 1 = 15 rows.
    # Passengers = 0: R7, R8, R9 (cargo), R13 (all zero), R19 (seats but no passengers) = 5 rows.
    counts = dict(con.execute("SELECT is_passenger, count(*) FROM route_traffic GROUP BY 1").fetchall())
    assert counts == {True: 15, False: 5}
    # R19 offered 300 seats but carried 0 passengers: not a passenger row (rule is passengers, not seats).
    assert _one(con, "SELECT seats, is_passenger FROM route_traffic WHERE origin = 'SEA'") == (300, False)
    # R7 cargo: freight but no passengers.
    assert _one(con, "SELECT is_passenger FROM route_traffic WHERE dest = 'HKG'") == (False,)
    # R13 all-zero row.
    assert _one(con, "SELECT is_passenger FROM route_traffic WHERE origin = 'FAI'") == (False,)
    # R10 has only 30 passengers, still a passenger row.
    assert _one(con, "SELECT is_passenger FROM route_traffic WHERE origin = 'CPX'") == (True,)


# 6
def test_dest_country_kept(con):
    _load([SAMPLE_ZIP], con)
    # R7 ANC -> HKG: empty DEST_STATE_ABR, DEST_COUNTRY HK. Foreign airports are kept (7.7).
    assert _one(con, "SELECT origin, dest_country, freight_lbs FROM route_traffic WHERE dest = 'HKG'") == (
        "ANC", "HK", 100000.0)
    # R16 LAX -> NRT, a passenger flight abroad.
    assert _one(con, "SELECT dest_country, passengers FROM route_traffic WHERE dest = 'NRT'") == ("JP", 900)
    # R8 HKG -> ANC: a foreign ORIGIN is kept too.
    assert _one(con, "SELECT dest, dest_country FROM route_traffic WHERE origin = 'HKG'") == ("ANC", "US")
    # 18 US rows + HK (R7) + JP (R16).
    counts = dict(con.execute("SELECT dest_country, count(*) FROM route_traffic GROUP BY 1").fetchall())
    assert counts == {"US": 18, "HK": 1, "JP": 1}


# 7
def test_duplicate_rows_kept(con):
    _load([SAMPLE_ZIP], con)
    # R11 and R12 are fully identical (DL BOS -> LGA, April, 8 departures, 600 passengers).
    rows = con.execute(
        "SELECT departures, seats, passengers FROM route_traffic WHERE origin = 'BOS' AND dest = 'LGA'"
    ).fetchall()
    assert rows == [(8, 800, 600), (8, 800, 600)]
    # 600 + 600 = 1,200
    assert _one(con, "SELECT sum(passengers) FROM route_traffic WHERE dest = 'LGA'")[0] == 1200


# 8
def test_passenger_total_matches_file(con):
    _load([SAMPLE_ZIP], con)
    # Sum of PASSENGERS over all 20 rows, duplicate pair included:
    # 800 + 900 + 2,500 + 2,400 + 1,200 + 1,300 + 0 + 0 + 0 + 30 + 600 + 600 + 0
    # + 700 + 800 + 900 + 1,500 + 1,600 + 0 + 400 = 16,230
    assert _one(con, "SELECT sum(passengers) FROM route_traffic")[0] == 16230
    assert SAMPLE_PASSENGERS == 16230


# 9
def test_missing_column_fails_loudly(con, tmp_path):
    from loader.route_traffic import load_route_traffic

    i = HEADER.index("PASSENGERS")
    header = HEADER[:i] + HEADER[i + 1:]
    rows = [r[:i] + r[i + 1:] for r in SAMPLE_ROWS]
    bad_zip = write_t100_zip(tmp_path / "no_passengers.zip", rows, header)
    with pytest.raises(Exception, match="PASSENGERS"):
        load_route_traffic([bad_zip], con)


# 10 (added)
def test_rerun_replaces_rows(con):
    _load([SAMPLE_ZIP], con)
    _load([SAMPLE_ZIP], con)
    # Still 20 rows and 16,230 passengers, not 40 and 32,460: the second run REPLACES.
    assert _one(con, "SELECT count(*), sum(passengers) FROM route_traffic") == (SAMPLE_ROW_COUNT, SAMPLE_PASSENGERS)


# 2024 rows for the two-zip test (made up, same format).
ROWS_2024 = [
    (4, 4, 400, 100, 0, 187, "B6", "JetBlue Airways", "BOS", "MA", "US", "JFK", "NY", "US", "United States", 694, 2024, 1, "F"),
    (6, 6, 600, 200, 0, 2611, "AA", "American Airlines Inc.", "LAX", "CA", "US", "BOS", "MA", "US", "United States", 622, 2024, 6, "F"),
    (2, 2, 0, 0, 30000, 5063, "5X", "United Parcel Service", "ANC", "AK", "US", "HKG", "", "HK", "Hong Kong", 819, 2024, 3, "G"),
]


# 11 (added)
def test_two_zips_two_years(con, tmp_path):
    zip_2024 = write_t100_zip(tmp_path / "t100_2024.zip", ROWS_2024)
    _load([zip_2024, SAMPLE_ZIP], con)
    per_year = {
        r[0]: (r[1], r[2])
        for r in con.execute("SELECT year, count(*), sum(passengers) FROM route_traffic GROUP BY 1").fetchall()
    }
    # 2024: 3 rows, 100 + 200 + 0 = 300 passengers. 2025: the 20 sample rows, 16,230 passengers.
    assert per_year == {2024: (3, 300), 2025: (SAMPLE_ROW_COUNT, SAMPLE_PASSENGERS)}


# 12 (added)
def test_report_rows_and_table(con):
    report = _load([SAMPLE_ZIP], con)
    assert report.table == "route_traffic"
    assert report.rows == _one(con, "SELECT count(*) FROM route_traffic")[0] == SAMPLE_ROW_COUNT
