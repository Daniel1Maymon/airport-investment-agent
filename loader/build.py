"""One command builds the airport database (docs/architecture.md part 1).

    python -m loader.build --raw data/raw --out airports.duckdb

Downloads what is missing, runs the four loaders in order, fills `data_sources`,
checks every table has rows, and prints a short summary. The work goes into a
temporary file that replaces `out` only when everything worked, so a failed
build never leaves a half-built database behind.
"""

import argparse
import os
from pathlib import Path

import duckdb

import loader.airports
import loader.delays
import loader.enplanements
import loader.route_traffic
from loader.airports import download_ourairports, faa_to_iata, load_airports
from loader.common import create_schema
from loader.delays import download_ontime, load_airport_delays
from loader.enplanements import download_faa, load_enplanements
from loader.route_traffic import download_t100, load_route_traffic

FAA_YEARS = [2024, 2025]
T100_YEARS = [2019, 2024, 2025]
ONTIME_YEAR = 2025
ONTIME_MONTHS = list(range(1, 13))

# table -> (source name, url); the period is "current" or the years in the table.
SOURCES = {
    "airports": ("OurAirports", loader.airports.AIRPORTS_URL),
    "enplanements": ("FAA enplanements", loader.enplanements.FAA_URL),
    "route_traffic": ("BTS T-100 Segment", loader.route_traffic.T100_URL),
    "airport_delays": ("BTS On-Time", loader.delays.ONTIME_URL),
}


def _raw_files(raw):
    """The expected raw file paths, grouped by source."""
    return {
        "ourairports": [raw / "ourairports" / "airports.csv", raw / "ourairports" / "runways.csv"],
        "faa": {y: raw / "faa" / f"arp-cy{y}-commercial-service-enplanements.xlsx" for y in FAA_YEARS},
        "t100": {y: raw / "t100" / f"t100_{y}.zip" for y in T100_YEARS},
        "ontime": {m: raw / "ontime" / f"ontime_{ONTIME_YEAR}_{m}.zip" for m in ONTIME_MONTHS},
    }


def _download_missing(raw, files):
    """Call a download function only for the files that are not there yet."""
    if not all(p.exists() for p in files["ourairports"]):
        download_ourairports(raw / "ourairports")
    missing_faa = [y for y, p in files["faa"].items() if not p.exists()]
    if missing_faa:
        download_faa(missing_faa, raw / "faa")
    for year, path in files["t100"].items():
        if not path.exists():
            download_t100(year, raw / "t100")
    for month, path in files["ontime"].items():
        if not path.exists():
            download_ontime(ONTIME_YEAR, month, raw / "ontime")


def _check_present(files):
    """Raise FileNotFoundError naming the first expected file that is missing."""
    paths = list(files["ourairports"])
    for key in ("faa", "t100", "ontime"):
        paths += list(files[key].values())
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"missing raw file: {path}")


def _remove(tmp):
    """Delete the temp database and its .wal, if there."""
    tmp.unlink(missing_ok=True)
    tmp.with_name(tmp.name + ".wal").unlink(missing_ok=True)


def write_data_sources(con, reports):
    """Replace `data_sources` with one row per source, from the load reports."""
    con.execute("DELETE FROM data_sources")
    for report in reports:
        source, url = SOURCES[report.table]
        if report.table == "airports":
            period = "current"
        else:
            years = con.execute(f"SELECT DISTINCT year FROM {report.table} ORDER BY year").fetchall()
            period = ", ".join(str(y[0]) for y in years)
        con.execute(
            "INSERT INTO data_sources VALUES (?, ?, ?, current_timestamp, ?)",
            [source, url, period, report.rows],
        )


def build(raw_dir, out_path, download=True):
    """Build the airport database from the raw files; return the 4 load reports."""
    raw, out = Path(raw_dir), Path(out_path)
    files = _raw_files(raw)
    if download:
        _download_missing(raw, files)
    _check_present(files)

    tmp = out.with_name(f"{out.stem}.tmp.duckdb")
    _remove(tmp)
    con = duckdb.connect(str(tmp))
    try:
        create_schema(con)
        airports_csv, runways_csv = files["ourairports"]
        reports = [
            load_airports(airports_csv, runways_csv, con),
            load_enplanements(list(files["faa"].values()), faa_to_iata(airports_csv), con),
            load_route_traffic(list(files["t100"].values()), con),
            load_airport_delays(list(files["ontime"].values()), con),
        ]
        write_data_sources(con, reports)
        for table in SOURCES:
            if con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0:
                raise ValueError(f"table {table} is empty after loading")
        con.close()
        os.replace(tmp, out)
    except BaseException:
        con.close()
        _remove(tmp)
        raise

    for report in reports:
        print(f"{report.table}: {report.rows} rows")
    for report in reports:
        for warning in report.warnings:
            print(f"warning ({report.table}): {warning}")
    return reports


def main():
    """Command line: python -m loader.build --raw data/raw --out airports.duckdb."""
    parser = argparse.ArgumentParser(description="Build the airport database.")
    parser.add_argument("--raw", required=True, help="folder with the raw downloads")
    parser.add_argument("--out", required=True, help="the database file to write")
    args = parser.parse_args()
    build(args.raw, args.out)


if __name__ == "__main__":
    main()
