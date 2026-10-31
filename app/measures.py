"""The shared measure list: every per-airport number the app uses.

What it is:   Turns the raw database rows (airports, passenger counts, routes, delays)
              into the numbers the agent talks about, for each of the 679 airports.
Why we need:  This is the only place a measure is calculated. If two places calculated
              "load factor", they could slowly drift apart and give two different answers
              to the same question. With one home, the score, the tables and the chat
              answer always show the same number.
Used by:      app/tools/base.py (MEASURES, the allowed measure names).
              app/scoring.py takes the result of compute_measures() as input (no import).
              tests: test_step06_measures.py, test_step07_scoring.py,
              test_step08_tool_base.py.
              Planned: the Steps 10-12 tools call compute_measures() to rank and compare
              airports; Step 12 `unmet_demand` calls monthly_missing_seats() for "what is
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
Design:       docs/tools.md "The shared measure list" and "Unmet demand: how it becomes
              an amount"; docs/implementation-plan.md P2, P3, P6, P11, P12.

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
