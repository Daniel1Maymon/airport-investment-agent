"""BTS T-100 loader: the `route_traffic` table (docs/data-sources.md C, docs/schema.md).

What it is:   Downloads the BTS T-100 Segment data and loads it into `route_traffic`:
              flights, seats, passengers and distance per route, airline and month.
Why we need:  Most measures come from it: passengers, seats, load factor, growth since
              2019, long-haul share, missing seats, departures per runway.
Used by:      loader/build.py. tests: test_step03_route_traffic.py,
              test_step03_code_renames.py, test_step05_build.py (through build).
Uses:         the BTS download page and the downloaded zip files; writes the
              route_traffic table. loader/common.py (CODE_RENAMES, LoadReport).
Main parts:   T100_URL - the BTS download page.
              DATA_MEMBER - the name of the data file inside the zip.
              DOWNLOAD_FIELDS - the columns we ask BTS for.
              REQUIRED_COLUMNS - the columns a file must have before loading.
              INSERT_SQL, INSERT_PARAMS - the bulk load query and its values.
              parse_hidden_fields(html) - the hidden ASP.NET form fields, name -> value.
              download_t100(year, dest_dir) - download one year as a zip.
              load_route_traffic(zip_paths, con) - replace route_traffic from the zips.
Design:       docs/data-sources.md C; docs/schema.md `route_traffic`; docs/decisions.md
              7.6; docs/implementation-plan.md P6.

The BTS page has no direct download link. It is an ASP.NET form: we GET it,
copy its hidden `__...` fields, and POST them back with the year and the
columns we want. The answer is a zip holding `Documentation.csv` and the data
file `T_T100_SEGMENT_ALL_CARRIER.csv`.

The data file is big (~570K rows, ~61 MB per year), so it is bulk-loaded by
DuckDB, not row by row. Downloaded files are untrusted: the header is checked
before loading, the file path goes to SQL as a parameter, and every value is
read as text and then cast, so a bad value stops the load instead of being
guessed. Every row is kept as downloaded (foreign airports, duplicates).
"""

import csv
import html as html_lib
import http.cookiejar
import io
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from loader.common import CODE_RENAMES, LoadReport

T100_URL = "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45"

DATA_MEMBER = "T_T100_SEGMENT_ALL_CARRIER.csv"

# The 19 columns asked for in the download (data-sources.md C).
DOWNLOAD_FIELDS = [
    "DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "FREIGHT", "DISTANCE",
    "UNIQUE_CARRIER", "CARRIER_NAME", "ORIGIN", "ORIGIN_STATE_ABR", "ORIGIN_COUNTRY",
    "DEST", "DEST_STATE_ABR", "DEST_COUNTRY", "DEST_COUNTRY_NAME", "AIRCRAFT_TYPE", "YEAR", "MONTH", "CLASS",
]

# The columns the table needs; the load stops if one is missing.
REQUIRED_COLUMNS = [
    "YEAR", "MONTH", "ORIGIN", "DEST", "DEST_COUNTRY", "UNIQUE_CARRIER", "CARRIER_NAME",
    "AIRCRAFT_TYPE", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "FREIGHT", "DISTANCE",
]

# Old -> current airport codes (decisions 7.6), as a CASE whose codes are SQL
# parameters. The {col} placeholder is filled only with ORIGIN or DEST below.
_RENAME_SQL = "CASE {col} " + "WHEN ? THEN ? " * len(CODE_RENAMES) + "ELSE {col} END"
_RENAME_PARAMS = [code for pair in CODE_RENAMES.items() for code in pair]

# Every value is read as text; numbers are written like `10.00`, so the count
# columns go through DOUBLE before BIGINT. DEPARTURES_PERFORMED, not scheduled (P6).
INSERT_SQL = """
INSERT INTO route_traffic
SELECT
    CAST(YEAR AS INTEGER),
    CAST(MONTH AS INTEGER),
    {origin},
    {dest},
    DEST_COUNTRY,
    UNIQUE_CARRIER,
    CARRIER_NAME,
    CAST(AIRCRAFT_TYPE AS INTEGER),
    CAST(CAST(DEPARTURES_PERFORMED AS DOUBLE) AS BIGINT),
    CAST(CAST(SEATS AS DOUBLE) AS BIGINT),
    CAST(CAST(PASSENGERS AS DOUBLE) AS BIGINT),
    CAST(FREIGHT AS DOUBLE),
    CAST(DISTANCE AS DOUBLE),
    CAST(PASSENGERS AS DOUBLE) > 0
FROM read_csv(?, header = true, all_varchar = true)
""".format(origin=_RENAME_SQL.format(col="ORIGIN"), dest=_RENAME_SQL.format(col="DEST"))
INSERT_PARAMS = _RENAME_PARAMS + _RENAME_PARAMS  # origin CASE, then dest CASE

_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_NAME_ATTR = re.compile(r'\bname\s*=\s*"([^"]*)"', re.IGNORECASE)
_VALUE_ATTR = re.compile(r'\bvalue\s*=\s*"([^"]*)"', re.IGNORECASE)


def parse_hidden_fields(html: str) -> dict:
    """Return the hidden ASP.NET fields (inputs named `__...`) as name -> value.

    Raises ValueError if the page has no `__VIEWSTATE` field: the BTS page changed.
    """
    fields = {}
    for tag in _INPUT_TAG.findall(html):
        name = _NAME_ATTR.search(tag)
        if not name or not name.group(1).startswith("__"):
            continue
        value = _VALUE_ATTR.search(tag)
        fields[name.group(1)] = html_lib.unescape(value.group(1)) if value else ""
    if "__VIEWSTATE" not in fields:
        raise ValueError("BTS form page has no __VIEWSTATE field; the page format has changed")
    return fields


def download_t100(year, dest_dir) -> Path:
    """Download one year of T-100 Segment (All Carriers) to dest_dir/t100_{year}.zip."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"t100_{int(year)}.zip"
    tmp = path.with_name(path.name + ".part")

    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    page = opener.open(T100_URL, timeout=60).read().decode("utf-8", "replace")
    form = dict(
        parse_hidden_fields(page),
        cboGeography="All", cboYear=str(int(year)), cboPeriod="All",
        chkDownloadZip="on", btnDownload="Download",
    )
    form.update({f: "on" for f in DOWNLOAD_FIELDS})
    request = urllib.request.Request(T100_URL, data=urllib.parse.urlencode(form).encode())
    try:
        with opener.open(request, timeout=600) as response, open(tmp, "wb") as out:
            shutil.copyfileobj(response, out)
        if not zipfile.is_zipfile(tmp):
            raise ValueError(f"BTS sent something that is not a zip for {year}; the page may have changed")
        with zipfile.ZipFile(tmp) as z:
            if DATA_MEMBER not in z.namelist():
                raise ValueError(f"BTS zip for {year} has no {DATA_MEMBER}")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def _check_header(zip_path: Path):
    """Raise if the zip has no data file or its header lacks a required column."""
    with zipfile.ZipFile(zip_path) as z:
        if DATA_MEMBER not in z.namelist():
            raise ValueError(f"{zip_path.name} has no {DATA_MEMBER}")
        with z.open(DATA_MEMBER) as f:
            header = next(csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")), [])
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"{zip_path.name}: required column(s) missing: {', '.join(missing)}")


def load_route_traffic(zip_paths, con) -> LoadReport:
    """Replace the contents of `route_traffic` with every row of the T-100 zips."""
    zip_paths = [Path(p) for p in zip_paths]
    for p in zip_paths:
        _check_header(p)  # all files checked before anything is changed

    with tempfile.TemporaryDirectory() as tmp:
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM route_traffic")
            for i, p in enumerate(zip_paths):
                csv_path = Path(tmp) / f"{i}.csv"
                with zipfile.ZipFile(p) as z, z.open(DATA_MEMBER) as src, open(csv_path, "wb") as out:
                    shutil.copyfileobj(src, out)
                con.execute(INSERT_SQL, INSERT_PARAMS + [str(csv_path)])
                csv_path.unlink()
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    rows = con.execute("SELECT count(*) FROM route_traffic").fetchone()[0]
    return LoadReport(table="route_traffic", rows=rows, warnings=[])
