"""Build tests/fixtures/raw/ontime_sample.zip: a tiny, made-up BTS On-Time download.

The FORMAT copies the real January 2025 download (checked 2026-10-31); the flights are made up.
  * the zip holds two files: the data CSV
    `On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_2025_1.csv`
    and `readme.html`;
  * 110 columns: the header names are in double quotes, and every line (header and
    data) ends with a trailing comma, so the 110th column has an EMPTY name;
  * LF line endings, no BOM;
  * text columns are in double quotes (`"AA"`, `"New York, NY"`, `"0659"`), an
    empty text value is `""`;
  * whole-number columns (Year, Month, airport IDs, delay groups, ...) are written
    without decimals (`2025`, `1`, `-1`);
  * measured numbers are written with two decimals (`-3.00`, `23.00`, `1.00`);
  * an empty number is written as nothing (`,,`).
  * Like the real file: a cancelled flight has no DepDel15/ArrDel15/TaxiOut/TaxiIn;
    a diverted flight has a TaxiIn but no ArrDel15; the 5 cause columns are
    filled only for flights that arrived 15+ minutes late (ArrDel15 = 1.00).
  * Palm Beach is still written `PBI`, as in the real January file.

The committed sample holds BOTH months (January and February 2025) in one CSV.
Its member is named after January, like a real download: the loader must take
the year and month from the `Year` and `Month` columns, never from a file name.

Rebuild:  .venv/bin/python -m tests.fixtures.make_ontime_sample
The zip uses a fixed file date, so a rebuild gives the same bytes.
Every flight and the hand-worked totals are listed in tests/fixtures/TINY_DATA.md
("Step 4 sample: ontime_sample.zip").
"""

import zipfile
from pathlib import Path

# The 110 column names of the real file, in order. The last one is EMPTY: every
# line of the real file ends with a trailing comma.
HEADER = [
    "Year", "Quarter", "Month", "DayofMonth", "DayOfWeek", "FlightDate",
    "Reporting_Airline", "DOT_ID_Reporting_Airline", "IATA_CODE_Reporting_Airline",
    "Tail_Number", "Flight_Number_Reporting_Airline",
    "OriginAirportID", "OriginAirportSeqID", "OriginCityMarketID", "Origin",
    "OriginCityName", "OriginState", "OriginStateFips", "OriginStateName", "OriginWac",
    "DestAirportID", "DestAirportSeqID", "DestCityMarketID", "Dest",
    "DestCityName", "DestState", "DestStateFips", "DestStateName", "DestWac",
    "CRSDepTime", "DepTime", "DepDelay", "DepDelayMinutes", "DepDel15",
    "DepartureDelayGroups", "DepTimeBlk", "TaxiOut", "WheelsOff", "WheelsOn", "TaxiIn",
    "CRSArrTime", "ArrTime", "ArrDelay", "ArrDelayMinutes", "ArrDel15",
    "ArrivalDelayGroups", "ArrTimeBlk", "Cancelled", "CancellationCode", "Diverted",
    "CRSElapsedTime", "ActualElapsedTime", "AirTime", "Flights", "Distance", "DistanceGroup",
    "CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay",
    "FirstDepTime", "TotalAddGTime", "LongestAddGTime", "DivAirportLandings",
    "DivReachedDest", "DivActualElapsedTime", "DivArrDelay", "DivDistance",
]
for _n in range(1, 6):
    HEADER += [
        f"Div{_n}Airport", f"Div{_n}AirportID", f"Div{_n}AirportSeqID", f"Div{_n}WheelsOn",
        f"Div{_n}TotalGTime", f"Div{_n}LongestGTime", f"Div{_n}WheelsOff", f"Div{_n}TailNum",
    ]
HEADER.append("")  # the trailing comma
assert len(HEADER) == 110 and HEADER[-1] == ""

# How each column is written (copied from the real file).
# Text columns: always in double quotes.
TEXT_COLUMNS = {
    "Reporting_Airline", "IATA_CODE_Reporting_Airline", "Tail_Number",
    "Flight_Number_Reporting_Airline",
    "Origin", "OriginCityName", "OriginState", "OriginStateFips", "OriginStateName",
    "Dest", "DestCityName", "DestState", "DestStateFips", "DestStateName",
    "CRSDepTime", "DepTime", "DepTimeBlk", "WheelsOff", "WheelsOn",
    "CRSArrTime", "ArrTime", "ArrTimeBlk", "CancellationCode", "FirstDepTime",
}
for _n in range(1, 6):
    TEXT_COLUMNS |= {f"Div{_n}Airport", f"Div{_n}WheelsOn", f"Div{_n}WheelsOff", f"Div{_n}TailNum"}
# Whole numbers: no quotes, no decimals. FlightDate (2025-01-01) is also unquoted.
INT_COLUMNS = {
    "Year", "Quarter", "Month", "DayofMonth", "DayOfWeek", "DOT_ID_Reporting_Airline",
    "OriginAirportID", "OriginAirportSeqID", "OriginCityMarketID", "OriginWac",
    "DestAirportID", "DestAirportSeqID", "DestCityMarketID", "DestWac",
    "DepartureDelayGroups", "ArrivalDelayGroups", "DistanceGroup", "DivAirportLandings",
}
for _n in range(1, 6):
    INT_COLUMNS |= {f"Div{_n}AirportID", f"Div{_n}AirportSeqID"}
# Every other named column is a measured number written with two decimals.

# Airport facts used in the rows (IDs made up in the real style).
AIRPORTS = {
    #       ID     seq ID    market  city                   state fips name           wac
    "JFK": (12478, 1247805, 31703, "New York, NY", "NY", "36", "New York", 22),
    "LAX": (12892, 1289208, 32575, "Los Angeles, CA", "CA", "06", "California", 91),
    "BOS": (10721, 1072102, 30721, "Boston, MA", "MA", "25", "Massachusetts", 13),
    "PBI": (14027, 1402702, 33991, "West Palm Beach/Palm Beach, FL", "FL", "12", "Florida", 33),
    "PSE": (14113, 1411302, 34113, "Ponce, PR", "PR", "72", "Puerto Rico", 3),
    "LAS": (12889, 1288903, 32211, "Las Vegas, NV", "NV", "32", "Nevada", 85),
}
AIRLINES = {"AA": 19805, "B6": 20409, "DL": 19790}

# (origin, dest) -> (distance in miles, scheduled minutes in the air and on the ground)
ROUTES = {
    ("JFK", "LAX"): (2475, 381), ("LAX", "JFK"): (2475, 326),
    ("JFK", "BOS"): (187, 75), ("BOS", "JFK"): (187, 80),
    ("LAX", "BOS"): (2611, 330), ("BOS", "LAX"): (2611, 390),
    ("PSE", "JFK"): (1617, 240), ("JFK", "PSE"): (1617, 245),
    ("PBI", "JFK"): (1028, 165), ("JFK", "PBI"): (1028, 175),
    ("PBI", "BOS"): (1197, 190), ("BOS", "PBI"): (1197, 200),
}

# The 28 sample flights. One tuple per flight:
# (id, month, day, airline, flight no, origin, dest, kind, dep delay, arr delay,
#  taxi out, taxi in, causes)
#   kind: "ok" (flew normally), "cancelled" (with its cancellation code), "diverted"
#   causes: (carrier, weather, NAS, security, late aircraft) minutes; only for
#   flights that arrived 15+ minutes late. They add up to the arrival delay.
# Cancelled flights have no delays and no taxi times. The diverted flight has a
# taxi-in (it did reach its destination later) but no arrival delay, like the real file.
FLIGHTS = [
    # ---- January 2025 ----
    ("F1", 1, 2, "AA", "1", "JFK", "LAX", "ok", -3, -7, 20, 10, None),
    ("F2", 1, 3, "AA", "1", "JFK", "LAX", "ok", 0, -5, 30, 6, None),
    ("F3", 1, 4, "AA", "1", "JFK", "LAX", "ok", 110, 120, 40, 8, (100, 0, 20, 0, 0)),
    ("F4", 1, 5, "AA", "1", "JFK", "LAX", ("cancelled", "A"), None, None, None, None, None),
    ("F5", 1, 6, "B6", "601", "JFK", "BOS", "ok", -2, -4, 10, 4, None),
    ("F6", 1, 7, "B6", "602", "BOS", "JFK", "ok", 5, 30, 25, 12, (0, 0, 30, 0, 0)),
    ("F7", 1, 8, "B6", "602", "BOS", "JFK", ("cancelled", "B"), None, None, None, None, None),
    ("F8", 1, 9, "AA", "2", "LAX", "JFK", "ok", -1, -10, 18, 9, None),
    ("F9", 1, 10, "AA", "2", "LAX", "JFK", "diverted", 2, None, 14, 15, None),
    ("F10", 1, 11, "DL", "301", "LAX", "BOS", "ok", 70, 80, 22, 7, (0, 50, 10, 5, 15)),
    ("F11", 1, 12, "B6", "701", "PSE", "JFK", "ok", 0, -2, 12, 11, None),
    ("F12", 1, 13, "B6", "702", "JFK", "PSE", "ok", 50, 60, 35, 5, (60, 0, 0, 0, 0)),
    ("F13", 1, 14, "B6", "801", "PBI", "JFK", "ok", -4, -6, 16, 13, None),
    ("F14", 1, 15, "B6", "802", "JFK", "PBI", "ok", 10, 40, 24, 6, (0, 0, 0, 0, 40)),
    ("F15", 1, 16, "B6", "901", "BOS", "LAX", "ok", 0, 3, 20, 10, None),
    # ---- February 2025 ----
    ("F16", 2, 2, "AA", "1", "JFK", "LAX", "ok", 1, -3, 25, 5, None),
    ("F17", 2, 3, "AA", "1", "JFK", "LAX", ("cancelled", "C"), None, None, None, None, None),
    ("F18", 2, 4, "AA", "1", "JFK", "LAX", "ok", 85, 90, 45, 15, (0, 0, 60, 0, 30)),
    ("F19", 2, 5, "AA", "2", "LAX", "JFK", "ok", -5, -8, 15, 7, None),
    ("F20", 2, 6, "AA", "2", "LAX", "JFK", "ok", 3, 0, 17, 9, None),
    ("F21", 2, 7, "B6", "602", "BOS", "JFK", "ok", -2, -1, 19, 11, None),
    ("F22", 2, 8, "B6", "601", "JFK", "BOS", "ok", 20, 10, 20, 3, None),
    ("F23", 2, 9, "B6", "601", "JFK", "BOS", ("cancelled", "A"), None, None, None, None, None),
    ("F24", 2, 10, "B6", "701", "PSE", "JFK", "ok", 8, 25, 10, 20, (0, 25, 0, 0, 0)),
    ("F25", 2, 11, "B6", "811", "PBI", "BOS", "ok", 0, 2, 14, 8, None),
    ("F26", 2, 12, "B6", "812", "BOS", "PBI", ("cancelled", "B"), None, None, None, None, None),
    ("F27", 2, 13, "DL", "302", "BOS", "LAX", "ok", 40, 45, 30, 10, (45, 0, 0, 0, 0)),
    ("F28", 2, 14, "AA", "2", "LAX", "JFK", ("cancelled", "A"), None, None, None, None, None),
]

CAUSE_COLUMNS = ["CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay"]
FIXED_DATE = (2026, 10, 31, 12, 0, 0)
DEP_HHMM = 700  # every flight is scheduled to leave at 07:00 (made up)
README = (
    "<HTML>\n<HEAD>\n\t<TITLE> readme.html </TITLE>\n</HEAD>\n<BODY>\n"
    "\t<P>Made-up sample for tests. The real file explains the On-Time columns here.</P>\n"
    "</BODY>\n</HTML>\n"
)


def member_name(year, month):
    """The CSV name inside a real download, e.g. ..._2025_1.csv (month without a leading zero)."""
    return f"On_Time_Reporting_Carrier_On_Time_Performance_(1987_present)_{year}_{month}.csv"


def _clock(minutes_after_midnight):
    m = minutes_after_midnight % (24 * 60)
    return f"{m // 60:02d}{m % 60:02d}"


def _block(minutes_after_midnight):
    h = (minutes_after_midnight % (24 * 60)) // 60
    return f"{h:02d}00-{h:02d}59"


def _group(delay):
    """BTS delay group: 15-minute steps, from -2 up to 12."""
    return max(-2, min(12, delay // 15))


def flight_row(flight, year=2025):
    """All column values of one flight as a dict (None = empty)."""
    fid, month, day, airline, number, origin, dest, kind, dep_d, arr_d, t_out, t_in, causes = flight
    cancelled = isinstance(kind, tuple)
    diverted = kind == "diverted"
    distance, sched = ROUTES[(origin, dest)]
    dep_at = DEP_HHMM // 100 * 60 + DEP_HHMM % 100
    arr_at = dep_at + sched
    r = dict.fromkeys(HEADER)
    r.update({
        "Year": year, "Quarter": (month - 1) // 3 + 1, "Month": month, "DayofMonth": day,
        "DayOfWeek": (day % 7) + 1, "FlightDate": f"{year}-{month:02d}-{day:02d}",
        "Reporting_Airline": airline, "DOT_ID_Reporting_Airline": AIRLINES[airline],
        "IATA_CODE_Reporting_Airline": airline, "Tail_Number": f"N{100 + int(fid[1:])}XX",
        "Flight_Number_Reporting_Airline": number,
        "CRSDepTime": _clock(dep_at), "DepTimeBlk": _block(dep_at),
        "CRSArrTime": _clock(arr_at), "ArrTimeBlk": _block(arr_at),
        "Cancelled": 1 if cancelled else 0, "CancellationCode": kind[1] if cancelled else "",
        "Diverted": 1 if diverted else 0,
        "CRSElapsedTime": sched, "Flights": 1, "Distance": distance,
        "DistanceGroup": min(11, distance // 250 + 1), "FirstDepTime": "",
        "DivAirportLandings": 1 if diverted else 0,
    })
    for side, code in (("Origin", origin), ("Dest", dest)):
        aid, seq, market, city, state, fips, state_name, wac = AIRPORTS[code]
        r.update({
            f"{side}AirportID": aid, f"{side}AirportSeqID": seq, f"{side}CityMarketID": market,
            side: code, f"{side}CityName": city, f"{side}State": state,
            f"{side}StateFips": fips, f"{side}StateName": state_name, f"{side}Wac": wac,
        })
    for n in range(1, 6):
        for col in ("Airport", "WheelsOn", "WheelsOff", "TailNum"):
            r[f"Div{n}{col}"] = ""
    if cancelled:
        # No departure, no taxi, no arrival: only text columns get "".
        r.update({"DepTime": "", "WheelsOff": "", "WheelsOn": "", "ArrTime": ""})
        return r
    off_at = dep_at + dep_d
    r.update({
        "DepTime": _clock(off_at), "DepDelay": dep_d, "DepDelayMinutes": max(0, dep_d),
        "DepDel15": 1 if dep_d >= 15 else 0, "DepartureDelayGroups": _group(dep_d),
        "TaxiOut": t_out, "WheelsOff": _clock(off_at + t_out),
    })
    if diverted:
        # Like the real diverted flight: it landed elsewhere first (LAS), then reached
        # its destination 2 hours late. It has a taxi-in, but NO arrival delay values.
        landed = arr_at + 120
        r.update({
            "ArrTime": _clock(landed), "WheelsOn": _clock(landed - t_in), "TaxiIn": t_in,
            "DivReachedDest": 1, "DivActualElapsedTime": sched + 118, "DivArrDelay": 120,
            "DivDistance": 0, "Div1Airport": "LAS", "Div1AirportID": AIRPORTS["LAS"][0],
            "Div1AirportSeqID": AIRPORTS["LAS"][1], "Div1WheelsOn": _clock(dep_at + 200),
            "Div1TotalGTime": 39, "Div1LongestGTime": 29, "Div1WheelsOff": _clock(dep_at + 239),
            "Div1TailNum": r["Tail_Number"],
        })
        return r
    landed = arr_at + arr_d
    elapsed = sched + arr_d - dep_d
    r.update({
        "ArrTime": _clock(landed), "WheelsOn": _clock(landed - t_in), "TaxiIn": t_in,
        "ArrDelay": arr_d, "ArrDelayMinutes": max(0, arr_d), "ArrDel15": 1 if arr_d >= 15 else 0,
        "ArrivalDelayGroups": _group(arr_d),
        "ActualElapsedTime": elapsed, "AirTime": elapsed - t_out - t_in,
    })
    if causes is not None:
        assert arr_d >= 15 and sum(causes) == arr_d, fid  # causes add up to the arrival delay
        r.update(dict(zip(CAUSE_COLUMNS, causes)))
    return r


def _cell(name, value):
    if name in TEXT_COLUMNS:
        return f'"{value if value is not None else ""}"'
    if value is None:
        return ""
    if name in INT_COLUMNS or name == "FlightDate":
        return str(value)
    return f"{value:.2f}"


def csv_text(rows, header=HEADER):
    """CSV text in the real format: quoted header names, LF, trailing comma on every line."""
    lines = [",".join(f'"{h}"' if h else "" for h in header)]
    for r in rows:
        lines.append(",".join(_cell(h, r.get(h)) if h else "" for h in header))
    return "\n".join(lines) + "\n"


def write_ontime_zip(path, flights, year=2025, month=1, header=HEADER, readme_first=False):
    """Write a zip like the BTS download: the data CSV, then readme.html.

    `flights` are tuples like FLIGHTS. The CSV member is named after `year` and
    `month`. Pass a shorter `header` to build a file with a column missing, and
    `readme_first=True` to put readme.html before the CSV.
    """
    data = csv_text([flight_row(f, year) for f in flights], header)
    members = [(member_name(year, month), data), ("readme.html", README)]
    if readme_first:
        members.reverse()
    path = Path(path)
    with zipfile.ZipFile(path, "w") as z:
        for member, text in members:
            info = zipfile.ZipInfo(member, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode("utf-8"))
    return path


SAMPLE_PATH = Path(__file__).parent / "raw" / "ontime_sample.zip"

if __name__ == "__main__":
    print(write_ontime_zip(SAMPLE_PATH, FLIGHTS, 2025, 1))
