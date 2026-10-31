"""The shared measure list: every per-airport number the app uses.

What it is:   Turns the raw database rows (airports, passenger counts, routes, delays)
              into the numbers the agent talks about, for each of the 679 airports.
Why we need:  This is the only place a measure is calculated. If two places calculated
              "load factor", they could slowly drift apart and give two different answers
              to the same question. With one home, the score, the tables and the chat
              answer always show the same number.
Used by:      app/tools/base.py (MEASURES, the allowed measure names).
              app/tools/rank.py, app/tools/profile.py (compute_measures, YEAR).
              app/tools/trend.py (traffic_by_period, enplanements_by_year,
              delays_by_period), app/tools/routes.py (route_groups, route_totals),
              app/tools/delays.py (delay_cause_minutes).
              app/scoring.py takes the result of compute_measures() as input (no import).
              tests: test_step06_measures.py, test_step07_scoring.py,
              test_step08_tool_base.py, test_step10_rank_profile.py,
              test_step11_trend_routes_delays.py.
              Planned: Step 12 `unmet_demand` calls monthly_missing_seats() for "what is
              the unmet demand at SFO, and why?".
Uses:         tables airports, route_traffic, airport_delays, enplanements (read only).
              No other project file.
Main parts:   YEAR - the year the measures are for (2025).
              MeasureInfo - one measure's group, plain label, unit and source table(s).
              MEASURES - measure name -> MeasureInfo; matches docs/tools.md (a test checks).
              missing_seats(passengers, seats, target_load_factor) - one month's missing
                seats, never below 0.
              compute_measures(con, long_haul_miles=3000, target_load_factor=0.85) - every
                measure for every airport: {code: {measure: value or None}}.
              monthly_missing_seats(con, iata, target_load_factor) - one airport's missing
                seats month by month, with the yearly totals.
              The same formulas for other years and months (Step 11, P36); each adds up
              a list of airports first, then works out ratios from the added parts:
              TRAFFIC_YEARS, ENPLANEMENT_YEARS - the years loaded per source.
              traffic_by_period(con, airports, by) - passengers, departures, seats,
                load_factor of passenger flights, 2019/2024/2025, by year or month.
              enplanements_by_year(con, airports) - FAA boardings, 2023-2025.
              delays_by_period(con, airports, by) - the 4 delay measures, 2025, by year
                or month.
              DISTANCE_BANDS, AIRCRAFT_SIZES - the fixed route-mix groups (P38).
              route_groups(con, iata, year, group_by, passengers_only) - one airport's
                departures, seats, passengers per group.
              route_totals(con, iata, year, passengers_only, long_haul_miles) - its totals
                and long-haul, international, cargo shares (P39).
              DELAY_CAUSES - the five delay causes.
              delay_cause_minutes(con, iata, by) - 2025 arriving-flight delay minutes by
                cause, with minutes per flight and share (P40).
Design:       docs/tools.md "The shared measure list" and "Unmet demand: how it becomes
              an amount"; docs/implementation-plan.md P2, P3, P6, P11, P12, P36-P40.

THE MEASURES, FOR EXAMPLE
  - load factor: how full the planes are (passengers / seats)
  - growth: how fast passenger numbers went up (2024->2025, 2019->2025)
  - NAS delay per flight: delay minutes caused by the air traffic system
    (NAS = National Airspace System), per arriving flight
  - taxi-out: minutes from leaving the gate to takeoff
  - departures per runway: how busy the runways are
  - long-haul share: share of passenger flights going 3,000+ miles
  - top airline share: how much the airport depends on one airline
  - missing seats: our estimate of unmet demand. Month by month, how many
    more seats were needed to keep planes at a target fullness (80-85%).

UNITS (P11): shares, growth, load factor and missing_seats_pct are fractions
(0.823 means 82.3%). Counts are plain numbers. Missing data gives None.
"""

from typing import NamedTuple

YEAR = 2025


class MeasureInfo(NamedTuple):
    """What a measure is: its group, a plain label, its unit, its source table(s)."""

    group: str
    label: str
    unit: str
    source: str


MEASURES = {
    "enplanements": MeasureInfo(group="Size", label="Passengers who boarded (FAA)", unit="passengers", source="enplanements"),
    "passengers": MeasureInfo(group="Size", label="Departing passengers on passenger flights", unit="passengers", source="route_traffic"),
    "departures": MeasureInfo(group="Size", label="Departing passenger flights", unit="departures", source="route_traffic"),
    "seats": MeasureInfo(group="Size", label="Seats offered on departing passenger flights", unit="seats", source="route_traffic"),
    "growth_short": MeasureInfo(group="Growth", label="Growth in boardings, 2024 to 2025", unit="share", source="enplanements"),
    "growth_long": MeasureInfo(group="Growth", label="Growth in departing passengers, 2019 to 2025", unit="share", source="route_traffic"),
    "load_factor": MeasureInfo(group="Crowding", label="How full planes are (passengers / seats)", unit="share", source="route_traffic"),
    "nas_delay_per_flight": MeasureInfo(
        group="Crowding", label="Airspace/airport delay minutes per arriving flight", unit="minutes", source="airport_delays"
    ),
    "taxi_out_min": MeasureInfo(group="Crowding", label="Average minutes from gate to takeoff", unit="minutes", source="airport_delays"),
    "departures_per_runway": MeasureInfo(
        group="Crowding",
        label="All departures (passenger and cargo) per open runway",
        unit="departures per runway",
        source="route_traffic, airports",
    ),
    "late_share": MeasureInfo(group="Crowding", label="Share of departures 15+ minutes late", unit="share", source="airport_delays"),
    "cancel_rate": MeasureInfo(group="Crowding", label="Share of departures cancelled", unit="share", source="airport_delays"),
    "long_haul_share": MeasureInfo(
        group="Flight mix", label="Share of passenger departures that are long-haul", unit="share", source="route_traffic"
    ),
    "international_share": MeasureInfo(
        group="Flight mix", label="Share of passenger departures to another country", unit="share", source="route_traffic"
    ),
    "cargo_share": MeasureInfo(group="Flight mix", label="Share of all departures without passengers", unit="share", source="route_traffic"),
    "top_airline_share": MeasureInfo(
        group="Airline dependence", label="Share of passenger departures flown by the biggest airline", unit="share", source="route_traffic"
    ),
    "missing_seats_pct": MeasureInfo(
        group="Unmet demand", label="Missing seats as a share of seats offered", unit="share", source="route_traffic"
    ),
    "score": MeasureInfo(group="Score", label="Final score (calculated in scoring)", unit="points", source="all"),
    "demand_score": MeasureInfo(group="Score", label="Demand half of the score", unit="points", source="all"),
    "strain_score": MeasureInfo(group="Score", label="Strain half of the score", unit="points", source="all"),
}


def missing_seats(passengers, seats, target_load_factor):
    """Seats needed to bring one month down to the target load factor; never below 0."""
    return max(0.0, passengers / target_load_factor - seats)


# One row per airport. Each CTE is a set-based total over all airports; the
# airports table is the base so every airport appears, with NULL for no data.
# The `?` parameters are listed in order in compute_measures.
_MEASURES_SQL = """
WITH
pax AS (
    SELECT origin AS iata,
           SUM(passengers)::DOUBLE AS passengers,
           SUM(departures)::DOUBLE AS departures,
           SUM(seats)::DOUBLE AS seats,
           SUM(CASE WHEN distance_mi >= ? THEN departures ELSE 0 END)::DOUBLE AS long_haul_deps,
           SUM(CASE WHEN dest_country <> 'US' THEN departures ELSE 0 END)::DOUBLE AS intl_deps
    FROM route_traffic
    WHERE year = ? AND is_passenger
    GROUP BY origin
),
all_deps AS (
    SELECT origin AS iata,
           SUM(departures)::DOUBLE AS departures,
           SUM(CASE WHEN NOT is_passenger THEN departures ELSE 0 END)::DOUBLE AS cargo_deps
    FROM route_traffic
    WHERE year = ?
    GROUP BY origin
),
pax_2019 AS (
    SELECT origin AS iata, SUM(passengers)::DOUBLE AS passengers
    FROM route_traffic
    WHERE year = 2019 AND is_passenger
    GROUP BY origin
),
by_month AS (
    SELECT origin AS iata, month,
           SUM(passengers)::DOUBLE AS passengers,
           SUM(seats)::DOUBLE AS seats
    FROM route_traffic
    WHERE year = ? AND is_passenger
    GROUP BY origin, month
),
missing AS (
    SELECT iata, SUM(GREATEST(0, passengers / ? - seats)) AS missing_seats
    FROM by_month
    GROUP BY iata
),
by_carrier AS (
    SELECT origin AS iata, carrier, SUM(departures)::DOUBLE AS departures
    FROM route_traffic
    WHERE year = ? AND is_passenger
    GROUP BY origin, carrier
),
top_carrier AS (
    SELECT iata, MAX(departures) AS departures FROM by_carrier GROUP BY iata
),
delays AS (
    SELECT iata,
           SUM(CASE WHEN direction = 'arr' THEN nas_delay_min END)::DOUBLE AS nas_min,
           SUM(CASE WHEN direction = 'arr' THEN flights END)::DOUBLE AS arr_flights,
           SUM(CASE WHEN direction = 'dep' THEN flights END)::DOUBLE AS dep_flights,
           SUM(CASE WHEN direction = 'dep' THEN cancelled END)::DOUBLE AS dep_cancelled,
           SUM(CASE WHEN direction = 'dep' THEN delayed_15 END)::DOUBLE AS dep_late,
           SUM(CASE WHEN direction = 'dep' AND avg_taxi_min IS NOT NULL
                    THEN avg_taxi_min * (flights - cancelled) END) AS taxi_weighted,
           SUM(CASE WHEN direction = 'dep' AND avg_taxi_min IS NOT NULL
                    THEN flights - cancelled END)::DOUBLE AS taxi_flights
    FROM airport_delays
    WHERE year = ?
    GROUP BY iata
),
enpl AS (
    SELECT iata,
           MAX(CASE WHEN year = ? THEN enplanements END)::DOUBLE AS now,
           MAX(CASE WHEN year = ? - 1 THEN enplanements END)::DOUBLE AS before
    FROM enplanements
    GROUP BY iata
)
SELECT
    a.iata,
    enpl.now AS enplanements,
    pax.passengers,
    pax.departures,
    pax.seats,
    (enpl.now - enpl.before) / NULLIF(enpl.before, 0) AS growth_short,
    (pax.passengers - pax_2019.passengers) / NULLIF(pax_2019.passengers, 0) AS growth_long,
    pax.passengers / NULLIF(pax.seats, 0) AS load_factor,
    delays.nas_min / NULLIF(delays.arr_flights, 0) AS nas_delay_per_flight,
    delays.taxi_weighted / NULLIF(delays.taxi_flights, 0) AS taxi_out_min,
    all_deps.departures / NULLIF(a.runway_count, 0) AS departures_per_runway,
    delays.dep_late / NULLIF(delays.dep_flights, 0) AS late_share,
    delays.dep_cancelled / NULLIF(delays.dep_flights, 0) AS cancel_rate,
    pax.long_haul_deps / NULLIF(pax.departures, 0) AS long_haul_share,
    pax.intl_deps / NULLIF(pax.departures, 0) AS international_share,
    all_deps.cargo_deps / NULLIF(all_deps.departures, 0) AS cargo_share,
    top_carrier.departures / NULLIF(pax.departures, 0) AS top_airline_share,
    missing.missing_seats / NULLIF(pax.seats, 0) AS missing_seats_pct
FROM airports a
LEFT JOIN pax ON pax.iata = a.iata
LEFT JOIN all_deps ON all_deps.iata = a.iata
LEFT JOIN pax_2019 ON pax_2019.iata = a.iata
LEFT JOIN missing ON missing.iata = a.iata
LEFT JOIN top_carrier ON top_carrier.iata = a.iata
LEFT JOIN delays ON delays.iata = a.iata
LEFT JOIN enpl ON enpl.iata = a.iata
ORDER BY a.iata
"""


def _num(value):
    """A database value as a float, keeping None (and 0) as they are."""
    return None if value is None else float(value)


def compute_measures(con, long_haul_miles=3000, target_load_factor=0.85):
    """Every measure (except the Score group) for every airport, for 2025.

    Returns {airport code: {measure name: value or None}}.
    """
    params = [
        long_haul_miles, YEAR,  # pax
        YEAR,  # all_deps
        YEAR,  # by_month
        target_load_factor,  # missing
        YEAR,  # by_carrier
        YEAR,  # delays
        YEAR, YEAR,  # enpl
    ]
    cursor = con.execute(_MEASURES_SQL, params)
    names = [col[0] for col in cursor.description][1:]
    return {row[0]: {name: _num(v) for name, v in zip(names, row[1:])} for row in cursor.fetchall()}


_MONTHLY_SQL = """
SELECT month,
       SUM(passengers)::DOUBLE AS passengers,
       SUM(seats)::DOUBLE AS seats,
       SUM(departures)::DOUBLE AS departures
FROM route_traffic
WHERE year = ? AND is_passenger AND origin = ?
GROUP BY month
ORDER BY month
"""


def monthly_missing_seats(con, iata, target_load_factor):
    """Missing seats month by month for one airport in 2025, and the yearly totals.

    Returns {missing_seats, missing_flights, seats_offered, by_month}, where
    by_month is month -> {passengers, seats, departures, load_factor, missing_seats}.
    missing_flights = missing seats / average seats per departing passenger flight.
    """
    rows = con.execute(_MONTHLY_SQL, [YEAR, iata]).fetchall()
    by_month = {}
    for month, passengers, seats, departures in rows:
        by_month[int(month)] = {
            "passengers": passengers,
            "seats": seats,
            "departures": departures,
            "load_factor": passengers / seats if seats else None,
            "missing_seats": missing_seats(passengers, seats, target_load_factor),
        }
    total_missing = sum(m["missing_seats"] for m in by_month.values())
    seats_offered = sum(m["seats"] for m in by_month.values())
    departures = sum(m["departures"] for m in by_month.values())
    seats_per_flight = seats_offered / departures if departures else None
    return {
        "missing_seats": total_missing,
        "missing_flights": total_missing / seats_per_flight if seats_per_flight else None,
        "seats_offered": seats_offered,
        "by_month": by_month,
    }


# ---------------------------------------------------------------------------
# Step 11: the same formulas for other years, by month, for groups of airports
# (P36). Each query takes a list of airport codes as one `?` parameter, so an
# area total is the same query as one airport: counts are added first, and
# ratios are worked out again from the added parts.
# ---------------------------------------------------------------------------

TRAFFIC_YEARS = (2019, 2024, 2025)
ENPLANEMENT_YEARS = (2023, 2024, 2025)

# The GROUP BY is chosen from this fixed dict by a checked setting ("year" or
# "month"), never from user text. Grouping (not a bare SUM) means a period with
# no rows gives no row, so only periods with data come back.
_PERIOD_GROUPS = {"year": "year", "month": "year, month"}

_TRAFFIC_SQL = """
SELECT year, {month} AS month,
       SUM(passengers)::DOUBLE AS passengers,
       SUM(departures)::DOUBLE AS departures,
       SUM(seats)::DOUBLE AS seats
FROM route_traffic
WHERE list_contains(?::INTEGER[], year) AND is_passenger AND list_contains(?::VARCHAR[], origin)
GROUP BY {group}
ORDER BY {group}
"""

_ENPLANEMENTS_SQL = """
SELECT year, SUM(enplanements)::DOUBLE AS enplanements
FROM enplanements
WHERE list_contains(?::INTEGER[], year) AND list_contains(?::VARCHAR[], iata)
GROUP BY year
ORDER BY year
"""

_DELAY_SQL = """
SELECT year, {month} AS month,
       SUM(CASE WHEN direction = 'arr' THEN nas_delay_min END)::DOUBLE AS nas_min,
       SUM(CASE WHEN direction = 'arr' THEN flights END)::DOUBLE AS arr_flights,
       SUM(CASE WHEN direction = 'dep' THEN flights END)::DOUBLE AS dep_flights,
       SUM(CASE WHEN direction = 'dep' THEN cancelled END)::DOUBLE AS dep_cancelled,
       SUM(CASE WHEN direction = 'dep' THEN delayed_15 END)::DOUBLE AS dep_late,
       SUM(CASE WHEN direction = 'dep' AND avg_taxi_min IS NOT NULL
                THEN avg_taxi_min * (flights - cancelled) END) AS taxi_weighted,
       SUM(CASE WHEN direction = 'dep' AND avg_taxi_min IS NOT NULL
                THEN flights - cancelled END)::DOUBLE AS taxi_flights
FROM airport_delays
WHERE year = ? AND list_contains(?::VARCHAR[], iata)
GROUP BY {group}
ORDER BY {group}
"""


def _ratio(top, bottom):
    """top / bottom, or None when either is missing or bottom is 0 (as NULLIF in SQL)."""
    return None if top is None or not bottom else top / bottom


def _period_sql(template, by):
    group = _PERIOD_GROUPS[by]  # KeyError for anything but "year" / "month"
    return template.format(group=group, month="month" if by == "month" else "NULL")


def traffic_by_period(con, airports, by="year"):
    """Passengers, departures, seats and load_factor of departing passenger flights,
    added up over `airports`, for 2019, 2024 and 2025, by year or by month.

    Returns a list in time order of {year, month (None by year), passengers,
    departures, seats, load_factor}; only periods with data.
    """
    rows = con.execute(_period_sql(_TRAFFIC_SQL, by), [list(TRAFFIC_YEARS), list(airports)]).fetchall()
    return [
        {
            "year": int(year),
            "month": None if month is None else int(month),
            "passengers": _num(passengers),
            "departures": _num(departures),
            "seats": _num(seats),
            "load_factor": _ratio(passengers, seats),
        }
        for year, month, passengers, departures, seats in rows
    ]


def enplanements_by_year(con, airports):
    """FAA boardings added up over `airports`, for 2023-2025 (the FAA counts per year only).

    Returns a list in year order of {year, enplanements}; only years with data.
    """
    rows = con.execute(_ENPLANEMENTS_SQL, [list(ENPLANEMENT_YEARS), list(airports)]).fetchall()
    return [{"year": int(year), "enplanements": _num(value)} for year, value in rows]


def delays_by_period(con, airports, by="year"):
    """The 4 delay measures for 2025 over `airports`, by year (one row) or by month.

    Same formulas as compute_measures: nas_delay_per_flight = NAS minutes / arriving
    flights; taxi_out_min weighted by flights not cancelled on departure rows;
    late_share and cancel_rate over departing flights. Parts are added first.
    Returns a list in time order of {year, month (None by year), nas_delay_per_flight,
    taxi_out_min, late_share, cancel_rate}; [] when there are no delay rows.
    """
    rows = con.execute(_period_sql(_DELAY_SQL, by), [YEAR, list(airports)]).fetchall()
    return [
        {
            "year": int(year),
            "month": None if month is None else int(month),
            "nas_delay_per_flight": _ratio(nas, arr),
            "taxi_out_min": _ratio(taxi_w, taxi_f),
            "late_share": _ratio(late, dep),
            "cancel_rate": _ratio(cancelled, dep),
        }
        for year, month, nas, arr, dep, cancelled, late, taxi_w, taxi_f in rows
    ]


# Route mix (P38, P39). The group key is chosen from this fixed dict by a checked
# setting, never from user text.
DISTANCE_BANDS = ("under 500", "500-999", "1,000-1,999", "2,000-2,999", "3,000+")
AIRCRAFT_SIZES = ("regional", "single-aisle", "wide-body", "cargo")
_ROUTE_GROUP_KEYS = {
    "destination": "dest",
    "country": "dest_country",
    "airline": "carrier",
    "distance_band": """CASE WHEN distance_mi < 500 THEN 'under 500'
                             WHEN distance_mi < 1000 THEN '500-999'
                             WHEN distance_mi < 2000 THEN '1,000-1,999'
                             WHEN distance_mi < 3000 THEN '2,000-2,999'
                             ELSE '3,000+' END""",
    # Per data row: that row's seats / departures (not the group's).
    "aircraft_size": """CASE WHEN seats = 0 THEN 'cargo'
                             WHEN departures = 0 THEN NULL
                             WHEN seats / departures < 100 THEN 'regional'
                             WHEN seats / departures < 230 THEN 'single-aisle'
                             ELSE 'wide-body' END""",
}

_ROUTE_GROUPS_SQL = """
SELECT grp, MAX(carrier_name) AS carrier_name,
       SUM(departures)::DOUBLE AS departures,
       SUM(seats)::DOUBLE AS seats,
       SUM(passengers)::DOUBLE AS passengers
FROM (
    SELECT {key} AS grp, carrier_name, departures, seats, passengers
    FROM route_traffic
    WHERE year = ? AND origin = ? AND (is_passenger OR NOT ?)
) AS t
WHERE grp IS NOT NULL
GROUP BY grp
"""

_ROUTE_TOTALS_SQL = """
SELECT COALESCE(SUM(CASE WHEN is_passenger OR NOT ? THEN departures END), 0)::DOUBLE AS departures,
       COALESCE(SUM(CASE WHEN is_passenger OR NOT ? THEN seats END), 0)::DOUBLE AS seats,
       COALESCE(SUM(CASE WHEN is_passenger OR NOT ? THEN passengers END), 0)::DOUBLE AS passengers,
       SUM(CASE WHEN (is_passenger OR NOT ?) AND distance_mi >= ? THEN departures ELSE 0 END)::DOUBLE AS long_haul,
       SUM(CASE WHEN (is_passenger OR NOT ?) AND dest_country <> 'US' THEN departures ELSE 0 END)::DOUBLE AS intl,
       SUM(departures)::DOUBLE AS all_departures,
       SUM(CASE WHEN NOT is_passenger THEN departures ELSE 0 END)::DOUBLE AS cargo
FROM route_traffic
WHERE year = ? AND origin = ?
"""


def route_groups(con, iata, year, group_by, passengers_only=True):
    """One airport's departures in `year` split into groups (P38), unsorted.

    `passengers_only` keeps only passenger-flight rows. Returns a list of {group,
    carrier_name, departures, seats, passengers}; rows with 0 departures are left
    out of the aircraft_size grouping (no seats per flight).
    """
    sql = _ROUTE_GROUPS_SQL.format(key=_ROUTE_GROUP_KEYS[group_by])
    rows = con.execute(sql, [year, iata, passengers_only]).fetchall()
    return [
        {"group": grp, "carrier_name": name, "departures": _num(d), "seats": _num(s), "passengers": _num(p)}
        for grp, name, d, s, p in rows
    ]


def route_totals(con, iata, year, passengers_only=True, long_haul_miles=3000):
    """One airport's departing totals in `year` and its flight-mix shares (P39).

    Returns {departures, seats, passengers, long_haul_share, international_share,
    cargo_share}. The first two shares are over the departures in scope (passenger
    flights only, or all with `passengers_only=False`); cargo_share is always cargo /
    all departures, as in compute_measures. Shares are None when there are no departures.
    """
    scope = [passengers_only] * 4 + [long_haul_miles, passengers_only]
    deps, seats, pax, long_haul, intl, all_deps, cargo = con.execute(
        _ROUTE_TOTALS_SQL, [*scope, year, iata]
    ).fetchone()
    return {
        "departures": deps,
        "seats": seats,
        "passengers": pax,
        "long_haul_share": _ratio(long_haul, deps),
        "international_share": _ratio(intl, deps),
        "cargo_share": _ratio(cargo, all_deps),
    }


# The five causes, in the column order of _CAUSES_SQL.
DELAY_CAUSES = ("carrier", "weather", "nas", "late_aircraft", "security")

_CAUSES_SQL = """
SELECT {month} AS month,
       SUM(flights)::DOUBLE AS flights,
       SUM(carrier_delay_min)::DOUBLE, SUM(weather_delay_min)::DOUBLE, SUM(nas_delay_min)::DOUBLE,
       SUM(late_aircraft_delay_min)::DOUBLE, SUM(security_delay_min)::DOUBLE
FROM airport_delays
WHERE year = ? AND iata = ? AND direction = 'arr'
GROUP BY {group}
ORDER BY {group}
"""


def delay_cause_minutes(con, iata, by="year"):
    """One airport's 2025 delay minutes by cause, on arriving flights (P40).

    Returns a list in time order (one entry by year, one per month by month) of
    {month (None by year), arriving_flights, total_delay_min, causes}, where causes is
    {cause: {minutes, per_flight, share}}: per_flight = minutes / all arriving flights
    (cancelled included, as nas_delay_per_flight); share = minutes / total delay
    minutes. [] when the airport has no delay rows.
    """
    result = []
    for month, flights, *minutes in con.execute(_period_sql(_CAUSES_SQL, by), [YEAR, iata]).fetchall():
        known = [m for m in minutes if m is not None]
        total = sum(known) if known else None
        result.append(
            {
                "month": None if month is None else int(month),
                "arriving_flights": flights,
                "total_delay_min": total,
                "causes": {
                    cause: {"minutes": m, "per_flight": _ratio(m, flights), "share": _ratio(m, total)}
                    for cause, m in zip(DELAY_CAUSES, minutes)
                },
            }
        )
    return result
