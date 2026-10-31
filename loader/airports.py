"""OurAirports loader: the `airports` table (docs/data-sources.md A, docs/schema.md).

Downloaded files are untrusted: we keep only the fields we need, cut names to
100 characters (P4), and pass file paths to SQL as parameters, never as text.
"""

import csv
from pathlib import Path

import httpx

from loader.common import LoadReport

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"

NAME_MAX = 100  # P4

LOAD_SQL = """
INSERT INTO airports
SELECT
    a.iata_code,
    substr(a.name, 1, ?),
    a.municipality,
    substr(a.iso_region, 4),
    TRY_CAST(a.latitude_deg AS DOUBLE),
    TRY_CAST(a.longitude_deg AS DOUBLE),
    CASE a.type
        WHEN 'large_airport' THEN 'large'
        WHEN 'medium_airport' THEN 'medium'
        ELSE 'small'
    END,
    r.runway_count,
    r.longest_runway_ft
FROM read_csv(?, all_varchar = true) AS a
LEFT JOIN (
    SELECT airport_ident,
           count(*) AS runway_count,
           max(TRY_CAST(length_ft AS INTEGER)) AS longest_runway_ft
    FROM read_csv(?, all_varchar = true)
    WHERE closed = '0'
    GROUP BY airport_ident
) AS r ON r.airport_ident = a.ident
WHERE a.iso_country = 'US'
  AND a.scheduled_service = 'yes'
  AND coalesce(a.iata_code, '') <> ''
"""


def download_ourairports(dest_dir):
    """Download airports.csv and runways.csv into dest_dir; return both paths."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for url in (AIRPORTS_URL, RUNWAYS_URL):
        path = dest / url.rsplit("/", 1)[1]
        response = httpx.get(url, timeout=120, follow_redirects=True)
        response.raise_for_status()
        path.write_bytes(response.content)
        paths.append(path)
    return paths[0], paths[1]


def load_airports(airports_csv, runways_csv, con) -> LoadReport:
    """Replace the contents of the `airports` table from the two CSV files."""
    con.execute("DELETE FROM airports")
    con.execute(LOAD_SQL, [NAME_MAX, str(airports_csv), str(runways_csv)])
    rows = con.execute("SELECT count(*) FROM airports").fetchone()[0]
    return LoadReport(table="airports", rows=rows, warnings=[])


def faa_to_iata(airports_csv) -> dict[str, str]:
    """FAA code (`local_code`) -> IATA code, for US airports that have both."""
    table = {}
    with open(airports_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            faa, iata = row["local_code"].strip(), row["iata_code"].strip()
            if row["iso_country"] == "US" and faa and iata:
                table[faa] = iata
    return table
