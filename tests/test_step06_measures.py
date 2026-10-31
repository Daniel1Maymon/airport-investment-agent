"""Step 6 tests: the shared measure list (app/measures.py).

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `MEASURES: dict[str, MeasureInfo]` with every measure named in docs/tools.md
  "The shared measure list", including `score`, `demand_score`, `strain_score`
  (group "Score", calculated in Step 7; P12). Each entry has `group`, `label`,
  `unit`, `source`.
* `compute_measures(con, long_haul_miles=3000, target_load_factor=0.85)`
  -> {airport code: {measure name: value or None}} for EVERY airport in the
  `airports` table, all measures except the Score group. 2025 unless stated.
  Shares, growth, load factor and missing_seats_pct are fractions (P11).
* `missing_seats(passengers, seats, target_load_factor)` = max(0, p / t - s).
* `monthly_missing_seats(con, iata, target_load_factor)` -> dict with
  `missing_seats`, `missing_flights`, `seats_offered`, `by_month`
  (month -> {passengers, seats, departures, load_factor, missing_seats}).

Every expected value is worked out by hand from tests/fixtures/TINY_DATA.md.
"Departing passenger rows" means route_traffic rows with origin = the airport
and is_passenger true, year 2025 (months 1 and 7 in the tiny data).
"""

import re
from pathlib import Path

import duckdb
import pytest

from app.db import open_airport_db
from app.measures import (
    MEASURES,
    compute_measures,
    missing_seats,
    monthly_missing_seats,
)
from loader.common import create_schema

TOOLS_DOC = Path(__file__).resolve().parent.parent / "docs" / "tools.md"
TINY_AIRPORTS = {"BOS", "MHT", "BTV", "BHB", "LAX", "SNA", "ANC"}


def _doc_measures():
    """Parse the table under '## The shared measure list' in tools.md.

    Returns {measure name: group}. One Measure cell can hold several backticked
    names; a blank Group cell continues the group of the row above.
    """
    text = TOOLS_DOC.read_text(encoding="utf-8")
    section = text.split("## The shared measure list", 1)[1]
    section = section.split("\n## ", 1)[0]
    result = {}
    group = None
    header_seen = False
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            if header_seen and result:
                break  # the table has ended
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not header_seen:
            header_seen = True  # the "| Group | Measure | ..." header row
            continue
        if set(cells[0]) <= set("-: ") and set(cells[1]) <= set("-: "):
            continue  # the |---|---| separator row
        if cells[0]:
            group = cells[0]
        for name in re.findall(r"`([a-z_0-9]+)`", cells[1]):
            result[name] = group
    return result


@pytest.fixture
def measures(tiny_db):
    """compute_measures on the tiny data with the default settings."""
    return compute_measures(tiny_db)


# 1
def test_measure_names_match_tools_doc(tiny_db):
    doc = _doc_measures()
    # Sanity check on the parser itself, so an empty parse can't pass.
    assert "passengers" in doc and "seats" in doc and "score" in doc
    assert set(MEASURES) == set(doc)

    # The group of every measure matches the doc's Group column.
    for name, group in doc.items():
        assert MEASURES[name].group == group, name
        assert MEASURES[name].label, name
        assert MEASURES[name].unit, name
        assert MEASURES[name].source, name

    # compute_measures returns every doc measure except the Score group (P12).
    expected = {name for name, group in doc.items() if group != "Score"}
    result = compute_measures(tiny_db)
    for iata, values in result.items():
        assert set(values) == expected, iata


# 2
def test_missing_seats_math():
    # 900 / 0.80 - 1000 = 1125 - 1000 = 125
    assert missing_seats(900, 1000, 0.80) == pytest.approx(125)


# 3
def test_missing_seats_never_negative():
    # 700 / 0.85 = 823.5 seats needed; 823.5 - 1000 < 0 -> 0
    assert missing_seats(700, 1000, 0.85) == 0
    # BOS January 2025: 1400 / 0.85 = 1647 - 2000 < 0 -> 0
    assert missing_seats(1400, 2000, 0.85) == 0


# 4
def test_missing_seats_counted_by_month(tiny_db):
    # BOS 2025 year load factor 3168 / 4000 = 79.2%, under the 85% target,
    # so a yearly calculation would give 0. By month:
    #   Jan 1400 / 0.85 = 1647.1 - 2000 < 0 -> 0
    #   Jul 1768 / 0.85 = 2080 - 2000 = 80
    result = monthly_missing_seats(tiny_db, "BOS", 0.85)
    assert result["missing_seats"] == pytest.approx(80)
    assert result["seats_offered"] == pytest.approx(4000)  # 4 rows x 1000
    by_month = result["by_month"]
    assert set(by_month) == {1, 7}
    assert by_month[1]["missing_seats"] == pytest.approx(0)
    assert by_month[7]["missing_seats"] == pytest.approx(80)
    # July: 884 + 884 = 1768 passengers, 1000 + 1000 seats, 10 + 10 departures
    assert by_month[7]["passengers"] == pytest.approx(1768)
    assert by_month[7]["seats"] == pytest.approx(2000)
    assert by_month[7]["departures"] == pytest.approx(20)
    assert by_month[7]["load_factor"] == pytest.approx(0.884)  # 1768 / 2000
    assert by_month[1]["load_factor"] == pytest.approx(0.70)  # 1400 / 2000


# 5
def test_missing_flights(tiny_db):
    # BOS: 4000 seats / 40 departures = 100 seats per flight.
    # 80%: Jul 1768 / 0.8 = 2210 - 2000 = 210 missing seats -> 210 / 100 = 2.1
    at_80 = monthly_missing_seats(tiny_db, "BOS", 0.80)
    assert at_80["missing_seats"] == pytest.approx(210)
    assert at_80["missing_flights"] == pytest.approx(2.1)
    # 85%: 80 missing seats -> 80 / 100 = 0.8
    at_85 = monthly_missing_seats(tiny_db, "BOS", 0.85)
    assert at_85["missing_flights"] == pytest.approx(0.8)


# 6
def test_missing_seats_pct(tiny_db):
    # BOS: 210 / 4000 = 0.0525 at 80%; 80 / 4000 = 0.02 at 85%
    at_80 = compute_measures(tiny_db, target_load_factor=0.80)
    assert at_80["BOS"]["missing_seats_pct"] == pytest.approx(0.0525)
    at_85 = compute_measures(tiny_db, target_load_factor=0.85)
    assert at_85["BOS"]["missing_seats_pct"] == pytest.approx(0.02)
    # The default target is 85%.
    default = compute_measures(tiny_db)
    assert default["BOS"]["missing_seats_pct"] == pytest.approx(0.02)
    # MHT at 80%: Jan 840/0.8 - 1000 = 50, Jul 960/0.8 - 1000 = 200 -> 250 / 2000
    assert at_80["MHT"]["missing_seats_pct"] == pytest.approx(0.125)
    # BTV never over target -> 0 (not None: it has seats)
    assert at_80["BTV"]["missing_seats_pct"] == pytest.approx(0)


# 7
def test_enplanements(measures):
    # FAA 2025 values
    assert measures["BOS"]["enplanements"] == pytest.approx(21_000_000)
    assert measures["BHB"]["enplanements"] == pytest.approx(55_000)
    assert measures["LAX"]["enplanements"] == pytest.approx(38_160_000)


# 8
def test_passengers_departures_seats_passenger_flights_only(measures):
    anc = measures["ANC"]
    # ANC 2025, the cargo ANC-SDF row (25 departures/month) is left out:
    # passengers (864 + 864) x 2 months = 3456
    assert anc["passengers"] == pytest.approx(3456)
    # departures (10 + 10) x 2 months = 40 (not 90)
    assert anc["departures"] == pytest.approx(40)
    # seats (1000 + 1000) x 2 months = 4000
    assert anc["seats"] == pytest.approx(4000)
    # BOS: 700 + 700 + 884 + 884 = 3168 passengers, 40 departures, 4000 seats
    assert measures["BOS"]["passengers"] == pytest.approx(3168)
    assert measures["BOS"]["departures"] == pytest.approx(40)
    assert measures["BOS"]["seats"] == pytest.approx(4000)


# 9
def test_growth_short(measures):
    # (enplanements 2025 - 2024) / 2024
    assert measures["MHT"]["growth_short"] == pytest.approx(0.20)  # 200k / 1M
    assert measures["BOS"]["growth_short"] == pytest.approx(0.05)  # 1M / 20M
    assert measures["LAX"]["growth_short"] == pytest.approx(0.06)  # 2.16M / 36M


# 10
def test_growth_long(measures):
    # T-100 departing passengers (2025 - 2019) / 2019
    assert measures["MHT"]["growth_long"] == pytest.approx(0.50)  # 600 / 1200
    assert measures["BOS"]["growth_long"] == pytest.approx(0.10)  # 288 / 2880
    assert measures["LAX"]["growth_long"] == pytest.approx(0.025)  # 120 / 4800
    # ANC: cargo row has 0 passengers either way: 256 / 3200 = 0.08
    assert measures["ANC"]["growth_long"] == pytest.approx(0.08)


# 11
def test_load_factor(measures):
    # 2025 passengers / seats, departing passenger rows
    assert measures["BOS"]["load_factor"] == pytest.approx(0.792)  # 3168 / 4000
    assert measures["MHT"]["load_factor"] == pytest.approx(0.90)  # 1800 / 2000
    assert measures["BHB"]["load_factor"] == pytest.approx(0.60)  # 108 / 180
    # ANC: the cargo row (0 seats) must not change it: 3456 / 4000 = 0.864
    assert measures["ANC"]["load_factor"] == pytest.approx(0.864)


# 12
def test_nas_delay_per_flight_uses_arrivals(measures):
    # NAS minutes on arr rows / arr flights, both months
    assert measures["BOS"]["nas_delay_per_flight"] == pytest.approx(8)  # 1600 / 200
    assert measures["LAX"]["nas_delay_per_flight"] == pytest.approx(10)  # 2000 / 200
    # BHB has rows with 0 NAS minutes -> 0, not None: 0 / 20
    assert measures["BHB"]["nas_delay_per_flight"] == pytest.approx(0)
    assert measures["BHB"]["nas_delay_per_flight"] is not None


# 13
def test_taxi_out_uses_departures(measures):
    # dep avg_taxi_min (taxi-out), not arr (taxi-in): BOS 20 not 8, LAX 22 not 10
    assert measures["BOS"]["taxi_out_min"] == pytest.approx(20)
    assert measures["LAX"]["taxi_out_min"] == pytest.approx(22)
    assert measures["SNA"]["taxi_out_min"] == pytest.approx(14)


# 14
def test_departures_per_runway_counts_cargo(measures):
    # ANC all 2025 departures: (10 + 10 + 25 cargo) x 2 months = 90; 90 / 3 = 30
    assert measures["ANC"]["departures_per_runway"] == pytest.approx(30)
    assert measures["BOS"]["departures_per_runway"] == pytest.approx(10)  # 40 / 4
    assert measures["SNA"]["departures_per_runway"] == pytest.approx(12)  # 12 / 1


# 15
def test_late_share(measures):
    # dep delayed_15 / dep flights: BOS 40 / 200 = 0.20 (arr would give 0.22)
    assert measures["BOS"]["late_share"] == pytest.approx(0.20)
    assert measures["LAX"]["late_share"] == pytest.approx(0.25)  # 50 / 200


def test_cancel_rate(measures):
    # dep cancelled / dep flights
    assert measures["BOS"]["cancel_rate"] == pytest.approx(0.02)  # 4 / 200
    assert measures["LAX"]["cancel_rate"] == pytest.approx(0.03)  # 6 / 200
    assert measures["BHB"]["cancel_rate"] == pytest.approx(0)  # 0 / 20


# 16
def test_long_haul_share(measures):
    # ANC: ATL route (3417 mi) 20 of 40 passenger departures = 0.5;
    # the cargo SDF route (2864 mi) is not a passenger departure.
    assert measures["ANC"]["long_haul_share"] == pytest.approx(0.5)
    # LAX: JFK is 2475 mi, MEX 1555 mi -> 0
    assert measures["LAX"]["long_haul_share"] == pytest.approx(0)
    assert measures["BOS"]["long_haul_share"] == pytest.approx(0)


def test_long_haul_threshold_adjustable(tiny_db):
    # 2000 miles (no route is exactly 2000):
    # LAX: JFK 2475 counts, MEX 1555 doesn't -> 40 of 60 = 0.6667
    # ANC: ATL 3417 counts, SEA 1448 doesn't -> 40 of 80 = 0.5
    at_2000 = compute_measures(tiny_db, long_haul_miles=2000)
    assert at_2000["LAX"]["long_haul_share"] == pytest.approx(40 / 60)
    assert at_2000["ANC"]["long_haul_share"] == pytest.approx(0.5)
    # 3500 miles: ANC's ATL 3417 no longer counts -> 0
    at_3500 = compute_measures(tiny_db, long_haul_miles=3500)
    assert at_3500["ANC"]["long_haul_share"] == pytest.approx(0)


# 17
def test_international_share(measures):
    # LAX: MEX (MX) 10 of 30 passenger departures = 1/3
    assert measures["LAX"]["international_share"] == pytest.approx(1 / 3)
    # ANC: long-haul but domestic -> 0
    assert measures["ANC"]["international_share"] == pytest.approx(0)


def test_cargo_share(measures):
    # ANC: cargo 25 x 2 = 50 of 90 departures = 0.5556
    assert measures["ANC"]["cargo_share"] == pytest.approx(50 / 90)
    assert measures["BOS"]["cargo_share"] == pytest.approx(0)


# 18
def test_top_airline_share(measures):
    # LAX: AA 40 of 60 passenger departures
    assert measures["LAX"]["top_airline_share"] == pytest.approx(40 / 60)
    # BOS: B6 and DL tie, 20 of 40
    assert measures["BOS"]["top_airline_share"] == pytest.approx(0.5)
    # ANC: AS and DL tie at 20 of 40 passenger departures; the cargo 5X (50) is
    # not a passenger airline, so it is not "the biggest airline" here.
    assert measures["ANC"]["top_airline_share"] == pytest.approx(0.5)
    assert measures["MHT"]["top_airline_share"] == pytest.approx(1.0)


# 19
def test_no_delay_data_gives_none(measures):
    # BTV has no airport_delays rows at all.
    btv = measures["BTV"]
    assert btv["nas_delay_per_flight"] is None
    assert btv["taxi_out_min"] is None
    assert btv["late_share"] is None
    assert btv["cancel_rate"] is None
    # Its other measures are still there: 728 / 1000
    assert btv["load_factor"] == pytest.approx(0.728)


# 20
def test_no_runways_gives_none(tmp_path):
    # P3: an airport with no runway data (runway_count NULL) gets None, not 0
    # and not an error. The tiny data has no such airport, so build one here.
    path = tmp_path / "norunway.duckdb"
    con = duckdb.connect(str(path))
    create_schema(con)
    con.execute(
        "INSERT INTO airports VALUES "
        "('XYZ', 'Test Field', 'Testville', 'ME', 44.0, -70.0, 'small', NULL, NULL)"
    )
    for month in (1, 7):
        con.execute(
            "INSERT INTO route_traffic VALUES "
            "(2025, ?, 'XYZ', 'BOS', 'US', 'WN', 'Southwest Airlines Co.', 612, "
            "5, 500, 400, 0, 200, true)",
            [month],
        )
    con.close()

    ro = open_airport_db(path)
    try:
        result = compute_measures(ro)
    finally:
        ro.close()
    assert result["XYZ"]["departures_per_runway"] is None
    # The route data is still used: 400 x 2 / (500 x 2) = 0.8
    assert result["XYZ"]["load_factor"] == pytest.approx(0.8)


def test_compute_measures_returns_every_airport(measures):
    # Every airport in the airports table, BHB included (size filter is Step 7).
    assert set(measures) == TINY_AIRPORTS


# Real-data checks (skipped when airports.duckdb is missing)


@pytest.mark.realdata
def test_real_sfo_load_factor(real_db):
    # docs/tools.md: SFO planes 82.3% full in 2025, 89.5% in June
    result = compute_measures(real_db)
    assert result["SFO"]["load_factor"] == pytest.approx(0.823, abs=0.001)
    monthly = monthly_missing_seats(real_db, "SFO", 0.85)
    assert monthly["by_month"][6]["load_factor"] == pytest.approx(0.895, abs=0.001)


@pytest.mark.realdata
def test_real_anc_long_haul_share(real_db):
    # Anchorage long-haul share of passenger departures about 2.8%
    result = compute_measures(real_db)
    assert result["ANC"]["long_haul_share"] == pytest.approx(0.028, abs=0.003)


@pytest.mark.realdata
def test_real_sfo_missing_seats(real_db):
    # docs/tools.md: SFO 2025 about 150,000 at 85% and 1,063,000 at 80%
    at_85 = monthly_missing_seats(real_db, "SFO", 0.85)
    at_80 = monthly_missing_seats(real_db, "SFO", 0.80)
    assert at_85["missing_seats"] == pytest.approx(150_000, rel=0.01)
    assert at_80["missing_seats"] == pytest.approx(1_063_000, rel=0.01)
