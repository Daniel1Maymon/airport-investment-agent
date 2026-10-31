"""BTS On-Time loader: the `airport_delays` table (docs/data-sources.md D, docs/schema.md).

What it is:   Downloads the BTS On-Time monthly files and stores totals per airport,
              month and direction in the `airport_delays` table.
Why we need:  Delays, delay causes, taxi times and cancellations come from here.
Used by:      loader/build.py. tests: test_step04_delays.py, test_step05_build.py
              (through build).
Uses:         the downloaded On-Time zip files; the airports table (to keep only our
              airports); writes the airport_delays table.
              loader/common.py (CODE_RENAMES, LoadReport).
Main parts:   ONTIME_URL - the download address.
              REQUIRED_COLUMNS - the columns a file must have before anything changes.
              INSERT_SQL, INSERT_PARAMS - the one GROUP BY query that fills the table,
                and its values.
              download_ontime(year, month, dest_dir) - download one month as a zip.
              load_airport_delays(zip_paths, con) - replace airport_delays from the zips.
Design:       docs/data-sources.md D; docs/schema.md `airport_delays`;
              docs/decisions.md 7.6.

The On-Time files list every single flight of the larger US airlines: about
540K flights (~240 MB of CSV) per month. We only need totals, so each month is
reduced while loading to one row per airport x month x direction: `dep` for the
flights leaving the airport (its `Origin`), `arr` for the flights arriving
(its `Dest`). The reduction is one GROUP BY in DuckDB, not a Python loop.

Rules:
* `flights` counts every flight, cancelled and diverted ones included.
* `delayed_15` uses DepDel15 on `dep` rows and ArrDel15 on `arr` rows.
* `avg_taxi_min` is the average TaxiOut (dep) or TaxiIn (arr) over the flights
  that have a value; cancelled flights have none and are skipped.
* The five cause columns are sums on `arr` rows (0 if no flight had causes);
  BTS records causes only for late arrivals, so they are empty on `dep` rows.
* Codes go through CODE_RENAMES (PBI -> DJT, decisions 7.6) before the filter.
  Only airports in the `airports` table are kept; each side of a flight is
  checked on its own.

Downloaded files are untrusted: the header is checked before anything changes,
the file path goes to SQL as a parameter, and values are read as text and then
cast, so a bad value stops the load instead of being guessed.
"""

import csv
import io
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from loader.common import CODE_RENAMES, LoadReport

ONTIME_URL = (
    "https://www.transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)

# The columns the table needs; the load stops if one is missing.
REQUIRED_COLUMNS = [
    "Year", "Month", "Origin", "Dest", "Cancelled", "DepDel15", "ArrDel15", "TaxiOut", "TaxiIn",
    "NASDelay", "CarrierDelay", "WeatherDelay", "LateAircraftDelay", "SecurityDelay",
]

# Old -> current airport codes (decisions 7.6), as a CASE whose codes are SQL
# parameters. The {col} placeholder is filled only with Origin or Dest below.
_RENAME_SQL = "CASE {col} " + "WHEN ? THEN ? " * len(CODE_RENAMES) + "ELSE {col} END"
_RENAME_PARAMS = [code for pair in CODE_RENAMES.items() for code in pair]

# Every value is read as text and then cast; numbers look like `1.00`.
INSERT_SQL = """
INSERT INTO airport_delays
WITH f AS (
    SELECT
        CAST(Year AS INTEGER)               AS year,
        CAST(Month AS INTEGER)              AS month,
        {origin}                            AS origin,
        {dest}                              AS dest,
        CAST(Cancelled AS DOUBLE) = 1       AS cancelled,
        CAST(DepDel15 AS DOUBLE) = 1        AS dep_del15,
        CAST(ArrDel15 AS DOUBLE) = 1        AS arr_del15,
        CAST(TaxiOut AS DOUBLE)             AS taxi_out,
        CAST(TaxiIn AS DOUBLE)              AS taxi_in,
        CAST(NASDelay AS DOUBLE)            AS nas,
        CAST(CarrierDelay AS DOUBLE)        AS carrier,
        CAST(WeatherDelay AS DOUBLE)        AS weather,
        CAST(LateAircraftDelay AS DOUBLE)   AS late_aircraft,
        CAST(SecurityDelay AS DOUBLE)       AS security
    FROM read_csv(?, header = true, all_varchar = true)
)
SELECT origin, year, month, 'dep', count(*),
       count(*) FILTER (WHERE cancelled), count(*) FILTER (WHERE dep_del15),
       avg(taxi_out), NULL, NULL, NULL, NULL, NULL
FROM f
WHERE origin IN (SELECT iata FROM airports)
GROUP BY origin, year, month
UNION ALL
SELECT dest, year, month, 'arr', count(*),
       count(*) FILTER (WHERE cancelled), count(*) FILTER (WHERE arr_del15),
       avg(taxi_in),
       coalesce(sum(nas), 0), coalesce(sum(carrier), 0), coalesce(sum(weather), 0),
       coalesce(sum(late_aircraft), 0), coalesce(sum(security), 0)
FROM f
WHERE dest IN (SELECT iata FROM airports)
GROUP BY dest, year, month
""".format(origin=_RENAME_SQL.format(col="Origin"), dest=_RENAME_SQL.format(col="Dest"))
INSERT_PARAMS = _RENAME_PARAMS + _RENAME_PARAMS  # origin CASE, then dest CASE


def download_ontime(year, month, dest_dir) -> Path:
    """Download one month of On-Time data to dest_dir/ontime_{year}_{month}.zip.

    If the file is already there, it is returned without downloading again.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    year, month = int(year), int(month)
    path = dest / f"ontime_{year}_{month}.zip"
    if path.exists():
        return path
    tmp = path.with_name(path.name + ".part")
    request = urllib.request.Request(
        ONTIME_URL.format(year=year, month=month), headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out)
        if not zipfile.is_zipfile(tmp):
            raise ValueError(f"BTS sent something that is not a zip for {year}-{month}")
        _csv_member(tmp)  # raises if the zip holds no CSV
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _csv_member(zip_path) -> str:
    """The name of the one data file in the zip, found by its `.csv` ending."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if len(names) != 1:
        raise ValueError(f"{Path(zip_path).name}: expected one .csv file, found {len(names)}")
    return names[0]


def _check_header(zip_path: Path) -> str:
    """Return the CSV member name; raise if its header lacks a required column."""
    member = _csv_member(zip_path)
    with zipfile.ZipFile(zip_path) as z, z.open(member) as f:
        header = next(csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")), [])
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{zip_path.name}: required column(s) missing: {', '.join(missing)}")
    return member


def load_airport_delays(zip_paths, con) -> LoadReport:
    """Replace the contents of `airport_delays` with the totals of the On-Time zips."""
    zip_paths = [Path(p) for p in zip_paths]
    members = [_check_header(p) for p in zip_paths]  # all files checked before anything changes

    with tempfile.TemporaryDirectory() as tmp:
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM airport_delays")
            for i, (p, member) in enumerate(zip(zip_paths, members)):
                csv_path = Path(tmp) / f"{i}.csv"
                with zipfile.ZipFile(p) as z, z.open(member) as src, open(csv_path, "wb") as out:
                    shutil.copyfileobj(src, out)
                con.execute(INSERT_SQL, INSERT_PARAMS + [str(csv_path)])
                csv_path.unlink()
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    rows = con.execute("SELECT count(*) FROM airport_delays").fetchone()[0]
    return LoadReport(table="airport_delays", rows=rows, warnings=[])
