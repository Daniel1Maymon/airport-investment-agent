"""Step 3 addition: the airport code rename (decision 7.6, 2026-10-31).

Palm Beach changed its code from PBI to DJT. BTS T-100 says PBI in every year;
the older FAA file (cy2024) says PBI; our airport list and the cy2025 FAA file
say DJT. So every loader renames old codes to current codes.

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `loader/common.py`
    - `CODE_RENAMES: dict[str, str]`, old code -> current code, holding
      `"PBI": "DJT"`. Values are 3-letter uppercase codes; a value is never also
      a key (no chained renames).
* `loader/route_traffic.py`, `load_route_traffic`: the rename is applied to
  ORIGIN and DEST of every row. Nothing else changes (row count, numbers).
* `loader/enplanements.py`, `load_enplanements`: the rename is applied to the
  FAA `Locid` BEFORE the FAA -> IATA lookup in `faa_to_iata`. So a `PBI` row is
  looked up as `DJT`, found, and loaded as `DJT`; no warning about PBI. The
  "newer file wins" rule (P7) then works on the renamed code.
* Codes that are not in `CODE_RENAMES` (BOS, JFK) are loaded as before.

All sample files are built in tmp_path with the existing writers, so they have
the real format. The existing fixtures are not changed.
"""

from pathlib import Path

import duckdb
import pytest

from loader.common import create_schema
from tests.fixtures.make_t100_sample import write_t100_zip
from tests.test_step02_enplanements import HEAD, _write_xlsx

US = "United States"

# T-100 rows in HEADER order (tests/fixtures/make_t100_sample.py):
# DEP_SCHED, DEP_PERF, SEATS, PASSENGERS, FREIGHT, DISTANCE, CARRIER, CARRIER_NAME,
# ORIGIN, ORIGIN_STATE, ORIGIN_COUNTRY, DEST, DEST_STATE, DEST_COUNTRY,
# DEST_COUNTRY_NAME, AIRCRAFT_TYPE, YEAR, MONTH, CLASS
RENAME_ROWS = [
    (10, 10, 1500, 1200, 0, 1197, "B6", "JetBlue Airways", "PBI", "FL", "US", "BOS", "MA", "US", US, 694, 2025, 1, "F"),
    (10, 10, 1500, 1300, 0, 1197, "B6", "JetBlue Airways", "BOS", "MA", "US", "PBI", "FL", "US", US, 694, 2025, 1, "F"),
    (8, 8, 1000, 700, 0, 1028, "B6", "JetBlue Airways", "PBI", "FL", "US", "JFK", "NY", "US", US, 694, 2025, 2, "F"),
    (5, 5, 500, 400, 0, 187, "B6", "JetBlue Airways", "BOS", "MA", "US", "JFK", "NY", "US", US, 694, 2025, 3, "F"),
]


@pytest.fixture
def con(tmp_path):
    """A fresh, writable DuckDB with the empty tables of schema.md part 1."""
    c = duckdb.connect(str(tmp_path / "r.duckdb"))
    create_schema(c)
    yield c
    c.close()


def _one(con, sql, params=None):
    return con.execute(sql, params or []).fetchone()


def _load_routes(tmp_path, con):
    from loader.route_traffic import load_route_traffic

    path = write_t100_zip(tmp_path / "t100_rename.zip", RENAME_ROWS)
    return load_route_traffic([Path(path)], con)


# 1
def test_code_renames_has_palm_beach():
    from loader.common import CODE_RENAMES

    assert CODE_RENAMES["PBI"] == "DJT"
    for old, new in CODE_RENAMES.items():
        assert isinstance(new, str) and len(new) == 3 and new.isalpha() and new.isupper(), new
        assert isinstance(old, str) and len(old) == 3 and old.isalpha() and old.isupper(), old
        # Never chained: a current code is never itself renamed again.
        assert new not in CODE_RENAMES


# 2 (+ 5 for T-100)
def test_route_traffic_renames_origin_and_dest(con, tmp_path):
    _load_routes(tmp_path, con)
    # No old code left on either side.
    assert _one(con, "SELECT count(*) FROM route_traffic WHERE origin = 'PBI' OR dest = 'PBI'")[0] == 0
    # DJT as origin: PBI->BOS 1,200 + PBI->JFK 700 = 1,900 passengers, 2 rows.
    assert _one(con, "SELECT count(*), sum(passengers) FROM route_traffic WHERE origin = 'DJT'") == (2, 1900)
    # DJT as dest: BOS->PBI only, 1,300 passengers.
    assert _one(con, "SELECT count(*), sum(passengers) FROM route_traffic WHERE dest = 'DJT'") == (1, 1300)
    # The renamed rows keep their numbers: DJT->BOS has 1,500 seats and 1,200 passengers.
    assert _one(
        con, "SELECT seats, passengers FROM route_traffic WHERE origin = 'DJT' AND dest = 'BOS'"
    ) == (1500, 1200)
    # Codes not in CODE_RENAMES are untouched: BOS as origin = BOS->PBI 1,300 + BOS->JFK 400 = 1,700.
    assert _one(con, "SELECT count(*), sum(passengers) FROM route_traffic WHERE origin = 'BOS'") == (2, 1700)
    # JFK as dest = PBI->JFK 700 + BOS->JFK 400 = 1,100.
    assert _one(con, "SELECT sum(passengers) FROM route_traffic WHERE dest = 'JFK'")[0] == 1100


# 3
def test_route_traffic_rename_keeps_totals(con, tmp_path):
    report = _load_routes(tmp_path, con)
    # Rename changes codes only: 4 rows in, 4 rows out.
    # Passengers 1,200 + 1,300 + 700 + 400 = 3,600; seats 1,500 + 1,500 + 1,000 + 500 = 4,500.
    assert report.rows == 4
    assert _one(con, "SELECT count(*), sum(passengers), sum(seats) FROM route_traffic") == (4, 3600, 4500)
    # Everything that touched PBI now touches DJT: 1,200 + 1,300 + 700 = 3,200 passengers, 3 rows.
    assert _one(
        con, "SELECT count(*), sum(passengers) FROM route_traffic WHERE origin = 'DJT' OR dest = 'DJT'"
    ) == (3, 3200)


# Enplanements samples: same format as the Step 2 tests.
# cy2024 file (CY 24, CY 23):  PBI M 3,000,000 (2024)  2,800,000 (2023)
#                              BOS L 18,000,000         17,000,000
# cy2025 file (CY 25, CY 24):  DJT M 3,300,000 (2025)  3,100,000 (2024)  <- 2024 differs
#                              BOS L 20,000,000         19,000,000
CY2024_RENAME = [
    (1, "NE", "MA", "BOS", "Boston", "General Edward Lawrence Logan International", "P", "L", 18000000, 17000000, 0.0588),
    (2, "SO", "FL", "PBI", "West Palm Beach", "Palm Beach International", "P", "M", 3000000, 2800000, 0.0714),
]
CY2025_RENAME = [
    (1, "NE", "MA", "BOS", "Boston", "General Edward Lawrence Logan International", "P", "L", 20000000, 19000000, 0.0526),
    (2, "SO", "FL", "DJT", "West Palm Beach", "Palm Beach International", "P", "M", 3300000, 3100000, 0.0645),
]

# Built from OurAirports: has DJT, not PBI.
FAA_TO_IATA_RENAME = {"DJT": "DJT", "BOS": "BOS"}


def _value(con, iata, year):
    row = _one(con, "SELECT enplanements FROM enplanements WHERE iata = ? AND year = ?", [iata, year])
    return None if row is None else row[0]


# 4 (+ 5 for FAA)
def test_enplanements_renames_before_translation(con, tmp_path):
    from loader.enplanements import load_enplanements

    older = _write_xlsx(
        tmp_path / "arp-cy2024-commercial-service-enplanements.xlsx",
        HEAD + ["CY 24 Enplanements", "CY 23 Enplanements", "% Change"],
        CY2024_RENAME,
    )
    newer = _write_xlsx(
        tmp_path / "arp-cy2025-commercial-service-enplanements.xlsx",
        HEAD + ["CY 25 Enplanements", "CY 24 Enplanements", "% Change"],
        CY2025_RENAME,
    )
    report = load_enplanements([Path(older), Path(newer)], FAA_TO_IATA_RENAME, con)

    # No PBI rows, and no warning about PBI (it was renamed, then found as DJT).
    assert _one(con, "SELECT count(*) FROM enplanements WHERE iata = 'PBI'")[0] == 0
    assert not any("PBI" in w for w in report.warnings)
    # DJT 2023 only comes from the older file's PBI row: 2,800,000.
    assert _value(con, "DJT", 2023) == 2800000
    # DJT 2024: older file (as PBI) 3,000,000 vs newer file 3,100,000 -> newer wins (P7): 3,100,000.
    assert _value(con, "DJT", 2024) == 3100000
    assert _one(con, "SELECT count(*) FROM enplanements WHERE iata = 'DJT' AND year = 2024")[0] == 1
    # DJT 2025 from the newer file: 3,300,000.
    assert _value(con, "DJT", 2025) == 3300000
    # BOS is not renamed: 2023 17,000,000 (older), 2024 19,000,000 (newer wins), 2025 20,000,000.
    assert _value(con, "BOS", 2023) == 17000000
    assert _value(con, "BOS", 2024) == 19000000
    assert _value(con, "BOS", 2025) == 20000000
    # 2 airports x 3 years = 6 rows.
    assert report.rows == 6
    assert _one(con, "SELECT count(*) FROM enplanements")[0] == 6
