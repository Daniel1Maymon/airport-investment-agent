"""Step 5 tests: one command builds the whole airport database.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `loader/build.py` (contract: step05_contract.md, kept by the main session)
    - `build(raw_dir, out_path, download=True) -> list[LoadReport]` runs the four
      loaders in order (airports, enplanements, route_traffic, airport_delays),
      fills `data_sources`, and returns the 4 reports in that order.
    - `write_data_sources(con, reports)` writes one row per source.
    - Module-level constants read when `build()` runs, so tests can change them:
      `FAA_YEARS`, `T100_YEARS`, `ONTIME_YEAR`, `ONTIME_MONTHS`.
    - The loaders and download functions are imported into `loader.build` by name
      (`load_route_traffic`, `download_t100`, ...), so tests replace them there.
    - Raw folder layout:
        <raw>/ourairports/airports.csv, <raw>/ourairports/runways.csv
        <raw>/faa/arp-cy{Y}-commercial-service-enplanements.xlsx   (Y in FAA_YEARS)
        <raw>/t100/t100_{Y}.zip                                     (Y in T100_YEARS)
        <raw>/ontime/ontime_{ONTIME_YEAR}_{M}.zip                   (M in ONTIME_MONTHS)
    - The build writes to `<out dir>/<out stem>.tmp.duckdb` and renames it to
      `out_path` only when everything worked. On an error the temp file and its
      `.wal` are deleted, the error is raised again, and an older `out_path` is
      left untouched.

The sample files
----------------
Each test copies the samples from tests/fixtures/raw into a fresh raw folder in
tmp_path. One copy of each is enough because the tests set
FAA_YEARS = [2025], T100_YEARS = [2025], ONTIME_YEAR = 2025, ONTIME_MONTHS = [1].
(The On-Time sample already holds January AND February 2025 inside one file, so
copying it under two month names would load every flight twice.)
There is no FAA sample file, so a small .xlsx is written here with openpyxl, in
the same format as the Step 2 tests.

Hand-worked row counts for the build from these samples
-------------------------------------------------------
* airports = 9. airports_sample.csv has 12 rows; kept = US + scheduled_service
  'yes' + a IATA code: SFO, LAX, SNA, BOS, AZA (FAA IWA), WFB (FAA 5KE), BHB, MHT,
  ANC. Dropped: SJU (Puerto Rico), HWD (no scheduled service), PAO (no IATA code).
  12 - 3 = 9.
* enplanements = 8. The FAA file below has BOS, SFO, IWA and ANC, all with a
  IATA code through airports_sample.csv (IWA -> AZA), each with CY 25 and CY 24:
  4 airports x 2 years = 8. Period "2024, 2025".
* route_traffic = 20. t100_sample.zip has 20 data rows (TINY_DATA.md, "Step 3
  sample"), all year 2025; this table is not filtered by our airport list.
  Period "2025".
* airport_delays = 8. Of the On-Time sample's airports, only LAX and BOS are in
  our 9 airports (JFK, PBI/DJT, PSE are not). Each has flights leaving and
  arriving in both January and February 2025 (TINY_DATA.md, "Step 4 sample":
  LAX Jan dep F8-F10, arr F1-F4+F15; BOS Jan dep F6, F7, F15, arr F5, F10;
  LAX Feb dep F19, F20, F28, arr F16-F18, F27; BOS Feb dep F21, F26, F27,
  arr F22, F23, F25): 2 airports x 2 months x 2 directions = 8. Period "2025".

Each test imports `loader.build` itself (or monkeypatches `loader.build.*`), so
before the builder starts every test fails on its own with ModuleNotFoundError.
"""

import shutil
from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from app.db import open_airport_db

SAMPLES = Path(__file__).parent / "fixtures" / "raw"

FIVE_TABLES = {"airports", "enplanements", "route_traffic", "airport_delays", "data_sources"}

EXPECTED_ROWS = {
    "airports": 9,  # 12 sample rows - SJU (PR) - HWD (not scheduled) - PAO (no IATA)
    "enplanements": 8,  # BOS, SFO, IWA->AZA, ANC x (2025, 2024)
    "route_traffic": 20,  # 20 data rows in t100_sample.zip
    "airport_delays": 8,  # LAX, BOS x Jan, Feb x dep, arr
}

# --- the FAA boardings file (same format as tests/test_step02_enplanements.py) ---

FAA_HEAD = ["Rank", "RO", "ST", "Locid", "City", "Airport Name", "S/L", "Hub",
            "CY 25 Enplanements", "CY 24 Enplanements", "% Change"]

# (Rank, RO, ST, Locid, City, Airport Name, S/L, Hub, CY 25, CY 24, % change)
FAA_ROWS = [
    (1, "NE", "MA", "BOS", "Boston", "General Edward Lawrence Logan International", "P", "L", 20000000, 19000000, 0.0526),
    (2, "WP", "CA", "SFO", "San Francisco", "San Francisco International", "P", "L", 25000000, 24000000, 0.0417),
    (3, "WP", "AZ", "IWA", "Mesa", "Mesa Gateway", "P", "S", 1000000, 900000, 0.1111),
    (4, "AL", "AK", "ANC", "Anchorage", "Ted Stevens Anchorage International", "P", "M", 3000000, 2800000, 0.0714),
]


def _write_faa_xlsx(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "ChangeinRevenuePassengerEnplan "  # real sheet name has a trailing space
    ws.append(FAA_HEAD)
    for r in FAA_ROWS:
        ws.append(list(r))
    wb.save(path)
    return path


# --- the raw folder, in the layout build() expects ---

def _put_ourairports(raw):
    d = raw / "ourairports"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLES / "airports_sample.csv", d / "airports.csv")
    shutil.copy(SAMPLES / "runways_sample.csv", d / "runways.csv")


def _put_faa(raw, year=2025):
    d = raw / "faa"
    d.mkdir(parents=True, exist_ok=True)
    _write_faa_xlsx(d / f"arp-cy{year}-commercial-service-enplanements.xlsx")


def _put_t100(raw, year=2025):
    d = raw / "t100"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLES / "t100_sample.zip", d / f"t100_{year}.zip")


def _put_ontime(raw, year=2025, month=1):
    d = raw / "ontime"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLES / "ontime_sample.zip", d / f"ontime_{year}_{month}.zip")


@pytest.fixture
def one_of_each(monkeypatch):
    """Ask build() for one file per source, so one copy of each sample is enough."""
    monkeypatch.setattr("loader.build.FAA_YEARS", [2025])
    monkeypatch.setattr("loader.build.T100_YEARS", [2025])
    monkeypatch.setattr("loader.build.ONTIME_YEAR", 2025)
    monkeypatch.setattr("loader.build.ONTIME_MONTHS", [1])


@pytest.fixture
def raw(tmp_path, one_of_each):
    """A raw folder holding every expected file."""
    raw = tmp_path / "raw"
    _put_ourairports(raw)
    _put_faa(raw)
    _put_t100(raw)
    _put_ontime(raw)
    return raw


@pytest.fixture
def out_dir(tmp_path):
    """The output folder, kept apart from the raw folder so leftovers are easy to see."""
    d = tmp_path / "out"
    d.mkdir()
    return d


def _tables(con):
    return {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()}


def _count(con, table):
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# 1 ---------------------------------------------------------------------------

def test_build_from_samples_makes_five_tables(raw, out_dir):
    from loader.build import build

    out = out_dir / "airports.duckdb"
    reports = build(raw, out, download=False)

    assert out.exists()
    con = open_airport_db(out)  # the result opens read-only
    try:
        assert _tables(con) == FIVE_TABLES
        for table, n in EXPECTED_ROWS.items():
            assert _count(con, table) == n, table
        assert _count(con, "data_sources") == 4  # one per source
    finally:
        con.close()

    # the 4 reports, in load order, each with the rows of its table
    assert [r.table for r in reports] == ["airports", "enplanements", "route_traffic", "airport_delays"]
    assert [r.rows for r in reports] == [9, 8, 20, 8]


def test_build_leaves_only_the_out_file(raw, out_dir):
    """After a good build the temp file and its .wal are gone."""
    from loader.build import build

    build(raw, out_dir / "airports.duckdb", download=False)
    assert sorted(p.name for p in out_dir.iterdir()) == ["airports.duckdb"]


# 2 ---------------------------------------------------------------------------

def test_data_sources_one_row_per_source(raw, out_dir):
    import loader.airports
    import loader.delays
    import loader.enplanements
    import loader.route_traffic
    from loader.build import build

    out = out_dir / "airports.duckdb"
    build(raw, out, download=False)

    con = open_airport_db(out)
    try:
        rows = con.execute(
            "SELECT source, url, period, row_count, loaded_at FROM data_sources"
        ).fetchall()
        by_source = {r[0]: r[1:] for r in rows}
        assert len(rows) == 4

        # source -> (table, url, period worked out by hand above)
        expected = {
            "OurAirports": ("airports", loader.airports.AIRPORTS_URL, "current"),
            "FAA enplanements": ("enplanements", loader.enplanements.FAA_URL, "2024, 2025"),
            "BTS T-100 Segment": ("route_traffic", loader.route_traffic.T100_URL, "2025"),
            "BTS On-Time": ("airport_delays", loader.delays.ONTIME_URL, "2025"),
        }
        assert set(by_source) == set(expected)
        for source, (table, url, period) in expected.items():
            got_url, got_period, row_count, loaded_at = by_source[source]
            assert got_url == url, source
            assert got_period == period, source
            # row count equals the table's row count ...
            assert row_count == _count(con, table), source
            # ... and the hand-worked count
            assert row_count == EXPECTED_ROWS[table], source
            assert loaded_at is not None, source
    finally:
        con.close()


def test_write_data_sources_twice_replaces(raw, out_dir):
    """Writing the sources again gives 4 rows, not 8."""
    from loader.build import build, write_data_sources

    out = out_dir / "airports.duckdb"
    reports = build(raw, out, download=False)

    con = duckdb.connect(str(out))
    try:
        write_data_sources(con, reports)
        assert _count(con, "data_sources") == 4
    finally:
        con.close()


# 3 ---------------------------------------------------------------------------

def test_failed_loader_leaves_no_file(raw, out_dir, monkeypatch):
    """A loader error stops the build; no half-built database is left behind."""

    def broken_route_traffic(zip_paths, con):
        raise RuntimeError("route traffic file is broken")

    monkeypatch.setattr("loader.build.load_route_traffic", broken_route_traffic)
    from loader.build import build

    # first with no older database
    out = out_dir / "airports.duckdb"
    with pytest.raises(RuntimeError, match="route traffic file is broken"):
        build(raw, out, download=False)
    assert list(out_dir.iterdir()) == []  # no out file, no .tmp.duckdb, no .wal

    # then with an older database already there: it keeps its bytes
    old = b"older database, must survive a failed rebuild"
    out.write_bytes(old)
    with pytest.raises(RuntimeError, match="route traffic file is broken"):
        build(raw, out, download=False)
    assert out.read_bytes() == old
    assert sorted(p.name for p in out_dir.iterdir()) == ["airports.duckdb"]


def test_corrupt_raw_file_leaves_no_file(raw, out_dir):
    """A broken download (not a zip) also stops the build and leaves nothing."""
    from loader.build import build

    (raw / "t100" / "t100_2025.zip").write_bytes(b"this is not a zip file")
    out = out_dir / "airports.duckdb"
    with pytest.raises(Exception):
        build(raw, out, download=False)
    assert list(out_dir.iterdir()) == []


def test_leftover_temp_file_is_replaced(raw, out_dir):
    """A temp file left by an earlier crash does not break the next build."""
    from loader.build import build

    (out_dir / "airports.tmp.duckdb").write_bytes(b"left over from a crash")
    (out_dir / "airports.tmp.duckdb.wal").write_bytes(b"left over from a crash")
    out = out_dir / "airports.duckdb"
    build(raw, out, download=False)

    assert sorted(p.name for p in out_dir.iterdir()) == ["airports.duckdb"]
    con = open_airport_db(out)
    try:
        assert _count(con, "airports") == 9  # see EXPECTED_ROWS
    finally:
        con.close()


def test_empty_table_fails_the_build(raw, out_dir, monkeypatch):
    """A loader that loads 0 rows fails the check; the error names the table."""
    from loader.common import LoadReport

    def empty_route_traffic(zip_paths, con):
        return LoadReport(table="route_traffic", rows=0, warnings=[])

    monkeypatch.setattr("loader.build.load_route_traffic", empty_route_traffic)
    from loader.build import build

    with pytest.raises(ValueError, match="route_traffic"):
        build(raw, out_dir / "airports.duckdb", download=False)
    assert list(out_dir.iterdir()) == []


def test_missing_raw_file_without_download(raw, out_dir):
    """download=False and a file missing: FileNotFoundError naming it, no out file."""
    from loader.build import build

    (raw / "t100" / "t100_2025.zip").unlink()
    with pytest.raises(FileNotFoundError, match="t100_2025.zip"):
        build(raw, out_dir / "airports.duckdb", download=False)
    assert list(out_dir.iterdir()) == []


# 4 ---------------------------------------------------------------------------

def _must_not_download(name):
    def fail(*args, **kwargs):
        pytest.fail(f"{name} was called although its files are already there")
    return fail


def test_existing_raw_files_not_downloaded_again(raw, out_dir, monkeypatch):
    for name in ("download_ourairports", "download_faa", "download_t100", "download_ontime"):
        monkeypatch.setattr(f"loader.build.{name}", _must_not_download(name))
    from loader.build import build

    out = out_dir / "airports.duckdb"
    reports = build(raw, out, download=True)

    assert [r.rows for r in reports] == [9, 8, 20, 8]  # see EXPECTED_ROWS
    assert out.exists()


def test_missing_raw_files_are_downloaded(tmp_path, out_dir, one_of_each, monkeypatch):
    """Only the missing files are downloaded, into the right folder."""
    raw = tmp_path / "raw"
    _put_ourairports(raw)
    _put_faa(raw)  # T-100 and On-Time are missing

    calls = []

    def fake_t100(year, dest_dir):
        calls.append(("t100", year, Path(dest_dir)))
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        path = Path(dest_dir) / f"t100_{year}.zip"
        shutil.copy(SAMPLES / "t100_sample.zip", path)
        return path

    def fake_ontime(year, month, dest_dir):
        calls.append(("ontime", year, month, Path(dest_dir)))
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        path = Path(dest_dir) / f"ontime_{year}_{month}.zip"
        shutil.copy(SAMPLES / "ontime_sample.zip", path)
        return path

    monkeypatch.setattr("loader.build.download_ourairports", _must_not_download("download_ourairports"))
    monkeypatch.setattr("loader.build.download_faa", _must_not_download("download_faa"))
    monkeypatch.setattr("loader.build.download_t100", fake_t100)
    monkeypatch.setattr("loader.build.download_ontime", fake_ontime)
    from loader.build import build

    reports = build(raw, out_dir / "airports.duckdb", download=True)

    assert calls == [
        ("t100", 2025, raw / "t100"),
        ("ontime", 2025, 1, raw / "ontime"),
    ]
    assert [r.rows for r in reports] == [9, 8, 20, 8]  # see EXPECTED_ROWS
