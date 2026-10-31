"""The shared tiny dataset: 7 made-up airports every step tests against.

Every value is written out in tests/fixtures/TINY_DATA.md, with the reason
each airport is here and the hand-worked numbers later steps rely on.

FROZEN after Step 0: later steps may add rows or airports, never change values.
"""

import duckdb

from loader.common import create_schema

YEARS = (2019, 2024, 2025)
MONTHS = (1, 7)  # January and July, in every year, for every airport

# iata, name, city, state, lat, lon, size_class, runway_count, longest_runway_ft
AIRPORTS = [
    ("BOS", "General Edward Lawrence Logan International Airport", "Boston", "MA",
     42.36, -71.01, "large", 4, 10083),
    ("MHT", "Manchester-Boston Regional Airport", "Manchester", "NH",
     42.93, -71.44, "medium", 2, 9250),
    ("BTV", "Burlington International Airport", "South Burlington", "VT",
     44.47, -73.15, "medium", 2, 8320),
    ("BHB", "Hancock County-Bar Harbor Airport", "Bar Harbor", "ME",
     44.45, -68.36, "small", 2, 5200),
    ("LAX", "Los Angeles International Airport", "Los Angeles", "CA",
     33.94, -118.41, "large", 4, 12923),
    ("SNA", "John Wayne Airport-Orange County Airport", "Santa Ana", "CA",
     33.68, -117.87, "medium", 1, 5701),
    ("ANC", "Ted Stevens Anchorage International Airport", "Anchorage", "AK",
     61.17, -149.98, "large", 3, 12400),
]

# iata: (hub_type, {year: enplanements})
ENPLANEMENTS = {
    "BOS": ("L", {2023: 19_000_000, 2024: 20_000_000, 2025: 21_000_000}),
    "MHT": ("S", {2023: 900_000, 2024: 1_000_000, 2025: 1_200_000}),
    "BTV": ("S", {2023: 580_000, 2024: 600_000, 2025: 618_000}),
    "BHB": ("N", {2023: 40_000, 2024: 50_000, 2025: 55_000}),
    "LAX": ("L", {2023: 35_000_000, 2024: 36_000_000, 2025: 38_160_000}),
    "SNA": ("M", {2023: 4_900_000, 2024: 5_000_000, 2025: 5_100_000}),
    "ANC": ("M", {2023: 2_400_000, 2024: 2_500_000, 2025: 2_600_000}),
}

# One route = one airline flying origin -> dest with one aircraft type.
# Departures, seats and freight are the same in every month and year;
# passengers are given per (year, month).
# (origin, dest, dest_country, carrier, carrier_name, aircraft_type,
#  departures, seats, freight_lbs, distance_mi, {(year, month): passengers})
ROUTES = [
    ("BOS", "MCO", "US", "B6", "JetBlue Airways", 694, 10, 1000, 0, 1121,
     {(2019, 1): 720, (2019, 7): 720, (2024, 1): 700, (2024, 7): 800,
      (2025, 1): 700, (2025, 7): 884}),
    ("BOS", "ATL", "US", "DL", "Delta Air Lines Inc.", 694, 10, 1000, 0, 946,
     {(2019, 1): 720, (2019, 7): 720, (2024, 1): 700, (2024, 7): 800,
      (2025, 1): 700, (2025, 7): 884}),
    ("MHT", "BWI", "US", "WN", "Southwest Airlines Co.", 612, 8, 1000, 0, 377,
     {(2019, 1): 600, (2019, 7): 600, (2024, 1): 750, (2024, 7): 750,
      (2025, 1): 840, (2025, 7): 960}),
    ("BTV", "ORD", "US", "AA", "American Airlines Inc.", 673, 5, 500, 0, 763,
     {(2019, 1): 350, (2019, 7): 350, (2024, 1): 350, (2024, 7): 350,
      (2025, 1): 350, (2025, 7): 378}),
    ("BHB", "BOS", "US", "9K", "Hyannis Air Service Inc. (Cape Air)", 35, 10, 90, 0, 151,
     {(2019, 1): 45, (2019, 7): 45, (2024, 1): 50, (2024, 7): 50,
      (2025, 1): 54, (2025, 7): 54}),
    ("LAX", "JFK", "US", "AA", "American Airlines Inc.", 614, 20, 2000, 0, 2475,
     {(2019, 1): 1600, (2019, 7): 1600, (2024, 1): 1600, (2024, 7): 1600,
      (2025, 1): 1640, (2025, 7): 1640}),
    ("LAX", "MEX", "MX", "AM", "Aerovias de Mexico", 694, 10, 1000, 0, 1555,
     {(2019, 1): 800, (2019, 7): 800, (2024, 1): 800, (2024, 7): 800,
      (2025, 1): 820, (2025, 7): 820}),
    ("SNA", "SJC", "US", "WN", "Southwest Airlines Co.", 612, 6, 600, 0, 342,
     {(2019, 1): 480, (2019, 7): 480, (2024, 1): 480, (2024, 7): 480,
      (2025, 1): 504, (2025, 7): 504}),
    ("ANC", "SEA", "US", "AS", "Alaska Airlines Inc.", 614, 10, 1000, 0, 1448,
     {(2019, 1): 800, (2019, 7): 800, (2024, 1): 800, (2024, 7): 800,
      (2025, 1): 864, (2025, 7): 864}),
    ("ANC", "ATL", "US", "DL", "Delta Air Lines Inc.", 622, 10, 1000, 0, 3417,
     {(2019, 1): 800, (2019, 7): 800, (2024, 1): 800, (2024, 7): 800,
      (2025, 1): 864, (2025, 7): 864}),
    # Cargo: no seats, no passengers, freight only.
    ("ANC", "SDF", "US", "5X", "United Parcel Service", 627, 25, 0, 3_000_000, 2864,
     {(y, m): 0 for y in YEARS for m in MONTHS}),
]

# Delays: 2025, months 1 and 7, the same values in both months.
# iata: (flights, dep_cancelled, dep_delayed_15, taxi_out,
#        arr_cancelled, arr_delayed_15, taxi_in,
#        nas, carrier, weather, late_aircraft, security)   # minutes per month
# BTV has no delay rows on purpose.
DELAYS = {
    "BOS": (100, 2, 20, 20.0, 2, 22, 8.0, 800, 600, 300, 700, 0),
    "MHT": (100, 1, 10, 12.0, 1, 10, 5.0, 100, 400, 100, 300, 0),
    "BHB": (10, 0, 1, 10.0, 0, 1, 4.0, 0, 10, 20, 0, 0),
    "LAX": (100, 3, 25, 22.0, 3, 26, 10.0, 1000, 700, 100, 800, 10),
    "SNA": (100, 1, 15, 14.0, 1, 16, 6.0, 300, 500, 50, 400, 0),
    "ANC": (100, 2, 12, 16.0, 2, 14, 7.0, 200, 300, 600, 300, 0),
}

LOADED_AT = "2026-10-31 12:00:00"

# source, url, period, table it fills
SOURCES = [
    ("OurAirports",
     "https://davidmegginson.github.io/ourairports-data/airports.csv",
     "current", "airports"),
    ("FAA enplanements",
     "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/"
     "passenger/arp-cy2025-commercial-service-enplanements.xlsx",
     "2023, 2024, 2025", "enplanements"),
    ("BTS T-100 Segment",
     "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45",
     "2019, 2024, 2025", "route_traffic"),
    ("BTS On-Time",
     "https://www.transtats.bts.gov/PREZIP/"
     "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{YEAR}_{MONTH}.zip",
     "2025", "airport_delays"),
]


def _route_rows():
    rows = []
    for (origin, dest, country, carrier, carrier_name, aircraft,
         departures, seats, freight, distance, passengers) in ROUTES:
        for year in YEARS:
            for month in MONTHS:
                pax = passengers[(year, month)]
                rows.append((year, month, origin, dest, country, carrier, carrier_name,
                             aircraft, departures, seats, pax, freight, distance, pax > 0))
    return rows


def _delay_rows():
    rows = []
    for iata, (flights, dep_canc, dep_late, taxi_out, arr_canc, arr_late, taxi_in,
               nas, carrier, weather, late_ac, security) in DELAYS.items():
        for month in MONTHS:
            rows.append((iata, 2025, month, "dep", flights, dep_canc, dep_late, taxi_out,
                         None, None, None, None, None))
            rows.append((iata, 2025, month, "arr", flights, arr_canc, arr_late, taxi_in,
                         nas, carrier, weather, late_ac, security))
    return rows


def build_tiny_db(path):
    """Build the tiny airport database at `path` (the file must not exist yet)."""
    con = duckdb.connect(str(path))
    try:
        create_schema(con)
        con.executemany("INSERT INTO airports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", AIRPORTS)
        con.executemany(
            "INSERT INTO enplanements VALUES (?, ?, ?, ?)",
            [(iata, year, value, hub)
             for iata, (hub, by_year) in ENPLANEMENTS.items()
             for year, value in by_year.items()],
        )
        con.executemany(
            "INSERT INTO route_traffic VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _route_rows(),
        )
        con.executemany(
            "INSERT INTO airport_delays VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            _delay_rows(),
        )
        for source, url, period, table in SOURCES:
            count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            con.execute(
                "INSERT INTO data_sources VALUES (?, ?, ?, CAST(? AS TIMESTAMP), ?)",
                [source, url, period, LOADED_AT, count],
            )
    finally:
        con.close()
