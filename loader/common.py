"""Shared loader code: the airport tables and the report every loader returns.

The tables are exactly those of docs/schema.md part 1. Primary keys yes,
foreign keys no (decisions 7.7). `route_traffic` has no primary key because
BTS can report the same combination twice.
"""

from dataclasses import dataclass, field

# Old airport code -> current code, applied by every loader to every airport
# code it reads. Palm Beach changed PBI to DJT; BTS T-100 and the older FAA
# file still say PBI (decisions 7.6). Add a rename only with evidence like this.
CODE_RENAMES = {"PBI": "DJT"}

SCHEMA_SQL = """
CREATE TABLE airports (
    iata              VARCHAR PRIMARY KEY,
    name              VARCHAR,
    city              VARCHAR,
    state             VARCHAR,
    lat               DOUBLE,
    lon               DOUBLE,
    size_class        VARCHAR,
    runway_count      INTEGER,
    longest_runway_ft INTEGER
);

CREATE TABLE enplanements (
    iata         VARCHAR,
    year         INTEGER,
    enplanements BIGINT,
    hub_type     VARCHAR,
    PRIMARY KEY (iata, year)
);

CREATE TABLE route_traffic (
    year          INTEGER,
    month         INTEGER,
    origin        VARCHAR,
    dest          VARCHAR,
    dest_country  VARCHAR,
    carrier       VARCHAR,
    carrier_name  VARCHAR,
    aircraft_type INTEGER,
    departures    BIGINT,
    seats         BIGINT,
    passengers    BIGINT,
    freight_lbs   DOUBLE,
    distance_mi   DOUBLE,
    is_passenger  BOOLEAN
);

CREATE TABLE airport_delays (
    iata                    VARCHAR,
    year                    INTEGER,
    month                   INTEGER,
    direction               VARCHAR,
    flights                 BIGINT,
    cancelled               BIGINT,
    delayed_15              BIGINT,
    avg_taxi_min            DOUBLE,
    nas_delay_min           DOUBLE,
    carrier_delay_min       DOUBLE,
    weather_delay_min       DOUBLE,
    late_aircraft_delay_min DOUBLE,
    security_delay_min      DOUBLE,
    PRIMARY KEY (iata, year, month, direction)
);

CREATE TABLE data_sources (
    source    VARCHAR PRIMARY KEY,
    url       VARCHAR,
    period    VARCHAR,
    loaded_at TIMESTAMP,
    row_count BIGINT
);
"""


def create_schema(con):
    """Create the 5 empty airport tables on an open DuckDB connection."""
    con.execute(SCHEMA_SQL)


@dataclass
class LoadReport:
    """What every loader returns: which table, how many rows, any warnings."""

    table: str
    rows: int
    warnings: list[str] = field(default_factory=list)
