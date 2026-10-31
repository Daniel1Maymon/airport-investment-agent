"""Step 2 tests: the `enplanements` table from the FAA boardings .xlsx files.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `loader/enplanements.py`
    - `load_enplanements(xlsx_paths, faa_to_iata: dict, con) -> LoadReport`
      writes the `enplanements` table (already made by `create_schema`) and
      REPLACES its contents (running twice gives the same table).
      Returns `LoadReport(table="enplanements", rows=<rows in the table>, warnings=[...])`.
    - `download_faa(years, dest_dir) -> list[Path]` uses the network; not tested here.
* Rules pinned here (docs/data-sources.md B, docs/schema.md `enplanements`,
  docs/decisions.md 7.6, implementation plan P7):
    - read the FIRST sheet (its real name is not a fixed string);
    - row 1 is the header; the two year columns are found by their LABEL
      (`CY 25 Enplanements` -> 2025, `CY 24 Enplanements` -> 2024), never by position;
    - each file gives two years, so the cy2025 + cy2024 files give 2023-2025;
    - when two files give the same (airport, year), the NEWER file wins. "Newer" is
      decided by the year labels inside the file, not by the order of `xlsx_paths`.
      An airport only in the older file keeps its rows from that file;
    - FAA code (`Locid`) -> IATA code only through the `faa_to_iata` dict passed in.
      No "FAA code = IATA code" fallback. A code missing from the dict is not
      loaded and is named in `LoadReport.warnings`;
    - summary rows (Rank empty, a count in Locid, a label in City) and fully blank
      rows are dropped silently: not loaded, not warnings;
    - `hub_type` keeps L / M / S / N as given; the text `None` is stored as NULL.

The sample files (built at test time with openpyxl into tmp_path)
-----------------------------------------------------------------
cy2025 file, header `... Hub, CY 25 Enplanements, CY 24 Enplanements, % Change`:
  Locid  Hub    CY 25        CY 24       note
  BOS    L      20,000,000   19,000,000  also in cy2024 file with 2024 = 18,000,000
  SFO    L      25,000,000   24,000,000  also in cy2024 file (same 2024 value)
  IWA    S       1,000,000      900,000  FAA IWA = IATA AZA
  ANC    M       3,000,000    2,800,000
  MHT    None       50,000       40,000  hub text 'None' -> NULL
  SNA    N         100,000       90,000
  QQQ    N          10,000        8,000  not in faa_to_iata -> warning
  (blank row)
  summary: Rank None, Locid 31,  City 'Large Count'
  summary: Rank None, Locid 522, City 'Total Primary Airports'

cy2024 file, header `... Hub, CY 24 Enplanements, CY 23 Enplanements, % Change`:
  Locid  Hub    CY 24        CY 23       note
  BOS    L      18,000,000   17,000,000  2024 loses to the cy2025 file (19,000,000)
  SFO    L      24,000,000   22,000,000
  LAX    L      30,000,000   29,000,000  only in this (older) file -> kept
  IWA    S         900,000      800,000
  (blank row)
  summary: Rank None, Locid 30, City 'Large Count'
"""

from pathlib import Path

import duckdb
import pytest
from openpyxl import Workbook

from loader.common import create_schema

# FAA code -> IATA code, written by hand (QQQ is deliberately missing).
FAA_TO_IATA = {
    "BOS": "BOS",
    "SFO": "SFO",
    "IWA": "AZA",
    "ANC": "ANC",
    "MHT": "MHT",
    "SNA": "SNA",
    "LAX": "LAX",
}

HEAD = ["Rank", "RO", "ST", "Locid", "City", "Airport Name", "S/L", "Hub"]

# (Rank, RO, ST, Locid, City, Airport Name, S/L, Hub, newer year, older year, % change)
CY2025_ROWS = [
    (1, "NE", "MA", "BOS", "Boston", "General Edward Lawrence Logan International", "P", "L", 20000000, 19000000, 0.0526),
    (2, "WP", "CA", "SFO", "San Francisco", "San Francisco International", "P", "L", 25000000, 24000000, 0.0417),
    (3, "WP", "AZ", "IWA", "Mesa", "Mesa Gateway", "P", "S", 1000000, 900000, 0.1111),
    (4, "AL", "AK", "ANC", "Anchorage", "Ted Stevens Anchorage International", "P", "M", 3000000, 2800000, 0.0714),
    (5, "NE", "NH", "MHT", "Manchester", "Manchester-Boston Regional", "P", "None", 50000, 40000, 0.25),
    (6, "WP", "CA", "SNA", "Santa Ana", "John Wayne Airport-Orange County", "P", "N", 100000, 90000, 0.1111),
    (7, "XX", "ZZ", "QQQ", "Nowhere", "Untranslatable Field", "P", "N", 10000, 8000, 0.25),
]

CY2024_ROWS = [
    (1, "NE", "MA", "BOS", "Boston", "General Edward Lawrence Logan International", "P", "L", 18000000, 17000000, 0.0588),
    (2, "WP", "CA", "SFO", "San Francisco", "San Francisco International", "P", "L", 24000000, 22000000, 0.0909),
    (3, "WP", "CA", "LAX", "Los Angeles", "Los Angeles International", "P", "L", 30000000, 29000000, 0.0345),
    (4, "WP", "AZ", "IWA", "Mesa", "Mesa Gateway", "P", "S", 900000, 800000, 0.125),
]

BLANK = (None,) * 11


def _summary(count, label):
    """A summary row like the real ones: no Rank, an int in Locid, a label in City."""
    return (None, None, None, count, label, None, None, None, None, None, None)


def _write_xlsx(path, header, rows, sheet_name="ChangeinRevenuePassengerEnplan "):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name  # real sheet name has a trailing space
    ws.append(header)
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    return path


def make_cy2025(tmp_path):
    header = HEAD + ["CY 25 Enplanements", "CY 24 Enplanements", "% Change"]
    rows = CY2025_ROWS + [BLANK, _summary(31, "Large Count"), _summary(522, "Total Primary Airports")]
    return _write_xlsx(tmp_path / "arp-cy2025-commercial-service-enplanements.xlsx", header, rows)


def make_cy2024(tmp_path):
    header = HEAD + ["CY 24 Enplanements", "CY 23 Enplanements", "% Change"]
    rows = CY2024_ROWS + [BLANK, _summary(30, "Large Count")]
    return _write_xlsx(tmp_path / "arp-cy2024-commercial-service-enplanements.xlsx", header, rows)


def make_cy2025_swapped(tmp_path):
    """Same data as the cy2025 file, but the year columns in the other order."""
    header = HEAD + ["CY 24 Enplanements", "CY 25 Enplanements", "% Change"]
    rows = [r[:8] + (r[9], r[8], r[10]) for r in CY2025_ROWS]
    rows += [BLANK, _summary(31, "Large Count")]
    return _write_xlsx(tmp_path / "swapped-cy2025.xlsx", header, rows)


@pytest.fixture
def con(tmp_path):
    """A fresh, writable DuckDB with the empty tables of schema.md part 1."""
    c = duckdb.connect(str(tmp_path / "t.duckdb"))
    create_schema(c)
    yield c
    c.close()


def _load(paths, con):
    from loader.enplanements import load_enplanements

    return load_enplanements([Path(p) for p in paths], FAA_TO_IATA, con)


def _value(con, iata, year):
    row = con.execute(
        "SELECT enplanements FROM enplanements WHERE iata = ? AND year = ?", [iata, year]
    ).fetchone()
    return None if row is None else row[0]


def _count(con):
    return con.execute("SELECT count(*) FROM enplanements").fetchone()[0]


# 1
def test_one_file_gives_two_years(con, tmp_path):
    report = _load([make_cy2025(tmp_path)], con)
    years = {r[0] for r in con.execute("SELECT DISTINCT year FROM enplanements").fetchall()}
    assert years == {2024, 2025}
    # 6 translatable airports (BOS SFO AZA ANC MHT SNA) x 2 years = 12 rows
    assert _count(con) == 12
    assert report.table == "enplanements"
    assert report.rows == 12
    assert _value(con, "BOS", 2025) == 20000000
    assert _value(con, "BOS", 2024) == 19000000


# 2
def test_year_columns_found_by_label(con, tmp_path):
    # Header is "... CY 24 Enplanements, CY 25 Enplanements ..." (swapped).
    # By label: BOS 2025 = 20,000,000 and 2024 = 19,000,000.
    # By position it would wrongly be 2025 = 19,000,000.
    _load([make_cy2025_swapped(tmp_path)], con)
    assert _value(con, "BOS", 2025) == 20000000
    assert _value(con, "BOS", 2024) == 19000000
    assert _value(con, "AZA", 2025) == 1000000
    assert _value(con, "AZA", 2024) == 900000


# 3
def test_two_files_cover_three_years(con, tmp_path):
    report = _load([make_cy2025(tmp_path), make_cy2024(tmp_path)], con)
    years = {r[0] for r in con.execute("SELECT DISTINCT year FROM enplanements").fetchall()}
    assert years == {2023, 2024, 2025}
    # BOS 3 + SFO 3 + AZA 3 (2023-2025) + ANC 2 + MHT 2 + SNA 2 (2024-2025)
    # + LAX 2 (2023-2024, only in cy2024 file) = 17 rows, no duplicates
    assert _count(con) == 17
    assert report.rows == 17
    assert _value(con, "BOS", 2023) == 17000000
    assert _value(con, "SFO", 2023) == 22000000
    assert _value(con, "AZA", 2023) == 800000


# 4
@pytest.mark.parametrize("newest_last", [False, True])
def test_newer_file_wins_on_overlap(con, tmp_path, newest_last):
    newer, older = make_cy2025(tmp_path), make_cy2024(tmp_path)
    paths = [older, newer] if newest_last else [newer, older]
    _load(paths, con)
    # BOS 2024: cy2025 file says 19,000,000, cy2024 file says 18,000,000.
    # Newer file (by its year labels, whatever the argument order) wins: 19,000,000.
    assert _value(con, "BOS", 2024) == 19000000
    # One row per (airport, year): no duplicate BOS 2024.
    n = con.execute(
        "SELECT count(*) FROM enplanements WHERE iata = 'BOS' AND year = 2024"
    ).fetchone()[0]
    assert n == 1
    # The rule is per (airport, year): LAX is only in the older file, so it keeps
    # both of its rows from it (2024 = 30,000,000, 2023 = 29,000,000).
    assert _value(con, "LAX", 2024) == 30000000
    assert _value(con, "LAX", 2023) == 29000000
    # BOS 2023 only comes from the older file: 17,000,000.
    assert _value(con, "BOS", 2023) == 17000000
    assert _count(con) == 17


# 5
def test_faa_code_translated(con, tmp_path):
    _load([make_cy2025(tmp_path)], con)
    codes = {r[0] for r in con.execute("SELECT iata FROM enplanements").fetchall()}
    # FAA IWA = IATA AZA; the FAA code itself is never stored.
    assert "AZA" in codes
    assert "IWA" not in codes
    assert _value(con, "AZA", 2025) == 1000000
    assert _value(con, "AZA", 2024) == 900000


# 6
def test_summary_rows_dropped(con, tmp_path):
    report = _load([make_cy2025(tmp_path), make_cy2024(tmp_path)], con)
    codes = {r[0] for r in con.execute("SELECT iata FROM enplanements").fetchall()}
    # Only real airports; no summary counts (31, 522, 30) and no NULL code from blank rows.
    assert codes == {"BOS", "SFO", "AZA", "ANC", "MHT", "SNA", "LAX"}
    assert None not in codes
    # Dropped silently: the only warning is the untranslated code QQQ.
    assert len(report.warnings) == 1
    for w in report.warnings:
        assert "Large Count" not in w
        assert "Total Primary" not in w
        assert "522" not in w


# 7
def test_untranslated_code_in_warnings(con, tmp_path):
    report = _load([make_cy2025(tmp_path)], con)
    # QQQ is not in FAA_TO_IATA: not loaded (no "FAA = IATA" fallback), and named in a warning.
    assert any("QQQ" in w for w in report.warnings)
    n = con.execute("SELECT count(*) FROM enplanements WHERE iata = 'QQQ'").fetchone()[0]
    assert n == 0


# 8
def test_hub_type_kept(con, tmp_path):
    _load([make_cy2025(tmp_path)], con)

    def hub(iata):
        return con.execute(
            "SELECT hub_type FROM enplanements WHERE iata = ? AND year = 2025", [iata]
        ).fetchone()[0]

    assert hub("BOS") == "L"
    assert hub("ANC") == "M"
    assert hub("AZA") == "S"
    assert hub("SNA") == "N"
    # The FAA text 'None' means "no hub group": stored as NULL, not the string 'None'.
    assert hub("MHT") is None


# extra
def test_rerun_replaces_rows(con, tmp_path):
    path = make_cy2025(tmp_path)
    _load([path], con)
    report = _load([path], con)
    # Same 12 rows as one load, not 24.
    assert _count(con) == 12
    assert report.rows == 12
