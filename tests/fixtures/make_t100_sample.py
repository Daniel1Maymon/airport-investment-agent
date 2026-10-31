"""Build tests/fixtures/raw/t100_sample.zip: a tiny, made-up BTS T-100 download.

The FORMAT copies the real 2025 download (checked 2026-10-31); the rows are made up.
  * the zip holds two files: `Documentation.csv` (field list) and
    `T_T100_SEGMENT_ALL_CARRIER.csv` (the data);
  * CRLF line endings, no BOM, no trailing comma;
  * the first 6 number columns are written with two decimals (`10.00`);
  * a carrier name with a comma is in double quotes;
  * state columns are empty for foreign airports.

Rebuild:  .venv/bin/python -m tests.fixtures.make_t100_sample
The zip uses a fixed file date, so a rebuild gives the same bytes.
Every row and the hand-worked totals are listed in tests/fixtures/TINY_DATA.md
("Step 3 sample: t100_sample.zip").
"""

import csv
import io
import zipfile
from pathlib import Path

DATA_MEMBER = "T_T100_SEGMENT_ALL_CARRIER.csv"
DOC_MEMBER = "Documentation.csv"

HEADER = [
    "DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "FREIGHT", "DISTANCE",
    "UNIQUE_CARRIER", "CARRIER_NAME", "ORIGIN", "ORIGIN_STATE_ABR", "ORIGIN_COUNTRY",
    "DEST", "DEST_STATE_ABR", "DEST_COUNTRY", "DEST_COUNTRY_NAME", "AIRCRAFT_TYPE", "YEAR", "MONTH", "CLASS",
]

# The 6 number columns written with two decimals, like the real file.
DECIMAL_COLUMNS = {"DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS", "FREIGHT", "DISTANCE"}

US = "United States"

# One tuple per row, in HEADER order:
# (sched, performed, seats, passengers, freight, distance, carrier, carrier name,
#  origin, origin state, origin country, dest, dest state, dest country, dest country name,
#  aircraft type, year, month, class)
SAMPLE_ROWS = [
    # R1-R2: JetBlue BOS <-> JFK, January
    (10, 10, 1000, 800, 0, 187, "B6", "JetBlue Airways", "BOS", "MA", "US", "JFK", "NY", "US", US, 694, 2025, 1, "F"),
    (10, 10, 1000, 900, 0, 187, "B6", "JetBlue Airways", "JFK", "NY", "US", "BOS", "MA", "US", US, 694, 2025, 1, "F"),
    # R3-R4: American LAX <-> BOS, January
    (20, 20, 3000, 2500, 0, 2611, "AA", "American Airlines Inc.", "LAX", "CA", "US", "BOS", "MA", "US", US, 622, 2025, 1, "F"),
    (20, 20, 3000, 2400, 0, 2611, "AA", "American Airlines Inc.", "BOS", "MA", "US", "LAX", "CA", "US", US, 622, 2025, 1, "F"),
    # R5: SCHEDULED 12 but PERFORMED 10; passengers AND freight
    (12, 10, 1500, 1200, 500, 372, "AS", "Alaska Airlines Inc.", "SNA", "CA", "US", "SFO", "CA", "US", US, 698, 2025, 2, "F"),
    # R6
    (10, 10, 1500, 1300, 0, 372, "AS", "Alaska Airlines Inc.", "SFO", "CA", "US", "SNA", "CA", "US", US, 698, 2025, 2, "F"),
    # R7: cargo to a FOREIGN airport (empty DEST_STATE_ABR)
    (5, 5, 0, 0, 100000, 5063, "5X", "United Parcel Service", "ANC", "AK", "US", "HKG", "", "HK", "Hong Kong", 819, 2025, 3, "G"),
    # R8: cargo FROM a foreign airport (empty ORIGIN_STATE_ABR)
    (5, 5, 0, 0, 80000, 5063, "5X", "United Parcel Service", "HKG", "", "HK", "ANC", "AK", "US", US, 819, 2025, 3, "G"),
    # R9: domestic cargo
    (4, 4, 0, 0, 40000, 1448, "FX", "Federal Express Corporation", "ANC", "AK", "US", "SEA", "WA", "US", US, 627, 2025, 3, "G"),
    # R10: carrier name with a comma (quoted in the file)
    (2, 2, 40, 30, 0, 17, "F4", "Air Charter, Inc d/b/a Air Flamenco", "CPX", "PR", "US", "VQS", "PR", "US", US, 131, 2025, 8, "F"),
    # R11-R12: two FULLY IDENTICAL rows (both must be kept)
    (8, 8, 800, 600, 0, 184, "DL", "Delta Air Lines Inc.", "BOS", "MA", "US", "LGA", "NY", "US", US, 612, 2025, 4, "F"),
    (8, 8, 800, 600, 0, 184, "DL", "Delta Air Lines Inc.", "BOS", "MA", "US", "LGA", "NY", "US", US, 612, 2025, 4, "F"),
    # R13: all-zero row, like the real Warbelow line
    (0, 0, 0, 0, 0, 0, "4W", "Warbelow", "FAI", "AK", "US", "FAI", "AK", "US", US, 194, 2025, 3, "F"),
    # R14-R15: United SFO <-> ORD, May
    (6, 6, 900, 700, 0, 1846, "UA", "United Air Lines Inc.", "SFO", "CA", "US", "ORD", "IL", "US", US, 622, 2025, 5, "F"),
    (6, 6, 900, 800, 0, 1846, "UA", "United Air Lines Inc.", "ORD", "IL", "US", "SFO", "CA", "US", US, 622, 2025, 5, "F"),
    # R16: passenger flight to a FOREIGN airport, with some freight
    (4, 4, 1000, 900, 2000, 5451, "JL", "Japan Airlines Co. Ltd.", "LAX", "CA", "US", "NRT", "", "JP", "Japan", 819, 2025, 6, "F"),
    # R17-R18: Southwest SNA <-> SJC, July
    (12, 12, 1800, 1500, 0, 236, "WN", "Southwest Airlines Co.", "SNA", "CA", "US", "SJC", "CA", "US", US, 614, 2025, 7, "F"),
    (12, 12, 1800, 1600, 0, 236, "WN", "Southwest Airlines Co.", "SJC", "CA", "US", "SNA", "CA", "US", US, 614, 2025, 7, "F"),
    # R19: seats offered but ZERO passengers (an empty positioning flight) -> not a passenger row
    (3, 3, 300, 0, 0, 1448, "AS", "Alaska Airlines Inc.", "SEA", "WA", "US", "ANC", "AK", "US", US, 698, 2025, 9, "F"),
    # R20: JetBlue BOS -> JFK, December
    (5, 5, 500, 400, 0, 187, "B6", "JetBlue Airways", "BOS", "MA", "US", "JFK", "NY", "US", US, 694, 2025, 12, "F"),
]

FIELD_DESCRIPTIONS = {
    "DEPARTURES_SCHEDULED": "Departures Scheduled",
    "DEPARTURES_PERFORMED": "Departures Performed",
    "SEATS": "Available Seats",
    "PASSENGERS": "Non-Stop Segment Passengers Transported",
    "FREIGHT": "Non-Stop Segment Freight Transported (pounds)",
    "DISTANCE": "Distance between airports (miles)",
    "UNIQUE_CARRIER": "Unique Carrier Code",
    "CARRIER_NAME": "Carrier Name",
    "ORIGIN": "Origin Airport",
    "ORIGIN_STATE_ABR": "Origin Airport, State Code",
    "ORIGIN_COUNTRY": "Origin Airport, Country Code",
    "DEST": "Destination Airport",
    "DEST_STATE_ABR": "Destination Airport, State Code",
    "DEST_COUNTRY": "Destination Airport, Country Code",
    "DEST_COUNTRY_NAME": "Destination Airport, Country Name",
    "AIRCRAFT_TYPE": "Aircraft Type",
    "YEAR": "Year",
    "MONTH": "Month",
    "CLASS": "Service Class",
}

FIXED_DATE = (2026, 10, 31, 12, 0, 0)


def _csv_text(header, rows):
    """CSV text in the real format: CRLF, quotes only when needed, 2 decimals for the number columns."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(header)
    for row in rows:
        out = []
        for name, value in zip(header, row):
            out.append(f"{value:.2f}" if name in DECIMAL_COLUMNS else value)
        w.writerow(out)
    return buf.getvalue()


def write_t100_zip(path, rows, header=HEADER):
    """Write a zip like the BTS download: Documentation.csv first, then the data CSV.

    `rows` are tuples in `header` order. Pass a shorter `header` (and matching
    rows) to build a file with a column missing.
    """
    doc_rows = [(name, FIELD_DESCRIPTIONS.get(name, name)) for name in header]
    doc = _csv_text(["SYS_FIELD_NAME", "FIELD_DESC"], doc_rows)
    data = _csv_text(header, rows)
    path = Path(path)
    with zipfile.ZipFile(path, "w") as z:
        for member, text in ((DOC_MEMBER, doc), (DATA_MEMBER, data)):
            info = zipfile.ZipInfo(member, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
    return path


SAMPLE_PATH = Path(__file__).parent / "raw" / "t100_sample.zip"

if __name__ == "__main__":
    print(write_t100_zip(SAMPLE_PATH, SAMPLE_ROWS))
