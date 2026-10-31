"""Step 11 tests: the `traffic_trend`, `route_mix` and `delay_causes` tools.

What the builder must follow (names the tests rely on)
------------------------------------------------------
app/tools/trend.py, app/tools/routes.py and app/tools/delays.py, imported by
app/tools/__init__.py, so `import app.tools` registers the tools `traffic_trend`,
`route_mix` and `delay_causes`. The tests call them only through
`run_tool(con, name, settings)`.

traffic_trend (P37, P41)
* data = {"measure", "by", "series": [{"name", "airports", "points": [...]}]}.
  A point has "year", "value"; by year also "change_from_first"; by month also
  "month" (and no "change_from_first").
route_mix (P38, P39, P41)
* data = {"airport", "year", "group_by", "passengers_only", "totals",
  "long_haul_share", "international_share", "cargo_share", "groups": [rows]}.
  Row keys: group, departures, seats, passengers, departures_share, seats_share,
  passengers_share (+ airline_name by airline, + groups on the "other" row).
delay_causes (P40, P41)
* data = {"airports": [entries]}  <- the top-level key "airports" is a choice of this
  test file (P40 does not name it); it follows airport_profile (P34).
  Entry keys: iata, arriving_flights, total_delay_min, causes = {carrier, weather,
  nas, late_aircraft, security: {"minutes", "per_flight", "share"}}; by month also
  "months" = [{"month", "arriving_flights", "total_delay_min", "causes"}].

HAND-WORKED NUMBERS (tests/fixtures/TINY_DATA.md)
=================================================
Every route row is one month. Departures/seats are the same every month; only
passengers change. Months 1 and 7 in 2019, 2024, 2025.

Passenger departures per year: BOS 40 (MCO 20 + ATL 20), MHT 16, BTV 10, BHB 20,
LAX 60 (JFK 40 + MEX 20), SNA 12, ANC 40 (SEA 20 + ATL 20) + cargo SDF 50.
Seats per year: BOS 4,000, MHT 2,000, BTV 1,000, BHB 180, LAX 6,000, SNA 1,200,
ANC 4,000 (cargo 0).
Seats per flight: every passenger row 100 (1,000 / 10, 2,000 / 20, ...) except
BHB 90 / 10 = 9.

Delays (2025, months 1 and 7, the same both months; arr row flights = 100):
BOS causes per month: nas 800, carrier 600, weather 300, late_aircraft 700,
security 0 -> 2,400 per month, 4,800 per year over 200 arriving flights.
LAX per month: nas 1,000, carrier 700, weather 100, late_aircraft 800, security 10
-> 2,610 per month, 5,220 per year over 200 arriving flights.
BTV has no delay rows at all.
"""

import duckdb
import pytest

import app.tools  # noqa: F401  (must register traffic_trend, route_mix, delay_causes)
from app.db import open_airport_db
from app.measures import compute_measures
from app.tools.base import TOOLS, run_tool
from app.tools.rank import NOTE_AIRLINE, NOTE_DELAYS, NOTE_LONG_HAUL
from loader.common import create_schema

TREND_MEASURES = {
    "passengers", "departures", "seats", "load_factor", "enplanements",
    "nas_delay_per_flight", "taxi_out_min", "late_share", "cancel_rate",
}  # fmt: skip
AREA_OR_AIRPORTS = ["airports", "region", "states"]
CAUSES = ("carrier", "weather", "nas", "late_aircraft", "security")
CAUSES_NOTE = "Causes are recorded on arriving flights 15+ minutes late; per-flight minutes divide by all arriving flights."


def _about_texts(result):
    about = result["about"]
    return about["filters"] + about["missing"] + about["assumptions"] + [about["data_period"]]


def _groups(result):
    return [row["group"] for row in result["data"]["groups"]]


def _row(result, group):
    return next(row for row in result["data"]["groups"] if row["group"] == group)


def _entry(result, iata):
    return next(e for e in result["data"]["airports"] if e["iata"] == iata)


# ---------------------------------------------------------------------------
# 1. traffic_trend by year and by month
# ---------------------------------------------------------------------------


def test_trend_by_year(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"]})
    data = result["data"]
    assert data["measure"] == "passengers"
    assert data["by"] == "year"
    assert len(data["series"]) == 1
    series = data["series"][0]
    assert series["name"] == "BOS"
    assert series["airports"] == ["BOS"]
    points = series["points"]
    assert [p["year"] for p in points] == [2019, 2024, 2025]
    # BOS passengers: 2019 720*4 = 2,880; 2024 700+800+700+800 = 3,000; 2025 700+884+700+884 = 3,168
    assert [p["value"] for p in points] == pytest.approx([2880, 3000, 3168])
    # change vs 2019: 0 / 2,880 = 0; 120 / 2,880 = 0.041667; 288 / 2,880 = 0.10
    assert [p["change_from_first"] for p in points] == pytest.approx([0.0, 120 / 2880, 0.10])
    assert all("month" not in p for p in points)
    assert result["about"]["data_period"] == "2019, 2024, 2025"

    # load factor by year: 2019 2,880 / 4,000 = 0.72; 2024 3,000 / 4,000 = 0.75; 2025 3,168 / 4,000 = 0.792
    lf = run_tool(tiny_db, "traffic_trend", {"measure": "load_factor", "airports": ["BOS"]})
    assert [p["value"] for p in lf["data"]["series"][0]["points"]] == pytest.approx([0.72, 0.75, 0.792])

    # enplanements by year: 2023 19M, 2024 20M, 2025 21M; change 2025 = 2M / 19M = 0.105263
    en = run_tool(tiny_db, "traffic_trend", {"measure": "enplanements", "airports": ["BOS"]})
    en_points = en["data"]["series"][0]["points"]
    assert [p["year"] for p in en_points] == [2023, 2024, 2025]
    assert [p["value"] for p in en_points] == pytest.approx([19_000_000, 20_000_000, 21_000_000])
    assert en_points[-1]["change_from_first"] == pytest.approx(2 / 19)
    assert en["about"]["data_period"] == "2023, 2024, 2025"


def test_trend_by_month(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"], "by": "month"})
    data = result["data"]
    assert data["by"] == "month"
    points = data["series"][0]["points"]
    # time order, only months with data (1 and 7 of each year)
    assert [(p["year"], p["month"]) for p in points] == [
        (2019, 1), (2019, 7), (2024, 1), (2024, 7), (2025, 1), (2025, 7),
    ]  # fmt: skip
    # per month: 720+720 = 1,440; 1,440; 700+700 = 1,400; 800+800 = 1,600; 1,400; 884+884 = 1,768
    assert [p["value"] for p in points] == pytest.approx([1440, 1440, 1400, 1600, 1400, 1768])
    assert all("change_from_first" not in p for p in points)

    # load factor by month (2,000 seats per month): 0.72, 0.72, 0.70, 0.80, 0.70, 1,768 / 2,000 = 0.884
    lf = run_tool(tiny_db, "traffic_trend", {"measure": "load_factor", "airports": ["BOS"], "by": "month"})
    assert [p["value"] for p in lf["data"]["series"][0]["points"]] == pytest.approx(
        [0.72, 0.72, 0.70, 0.80, 0.70, 0.884]
    )


# ---------------------------------------------------------------------------
# 2. enplanements by month is refused
# ---------------------------------------------------------------------------


def test_trend_enplanements_by_month_refused(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "enplanements", "airports": ["BOS"], "by": "month"})
    assert "data" not in result
    assert "FAA counts boardings only per year" in result["error"]
    assert result["allowed"] == ["year"]


# ---------------------------------------------------------------------------
# 3. area total
# ---------------------------------------------------------------------------


def test_trend_region_total(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "region": "New England"})
    series = result["data"]["series"]
    assert len(series) == 1
    total = series[0]
    assert "New England" in total["name"]
    # every airport of ours in New England, no size filter (BHB included)
    assert set(total["airports"]) == {"BOS", "MHT", "BTV", "BHB"}
    # 2019: 2,880 + 1,200 + 700 + 90 = 4,870
    # 2024: 3,000 + 1,500 + 700 + 100 = 5,300
    # 2025: 3,168 + 1,800 + 728 + 108 = 5,804
    assert [p["value"] for p in total["points"]] == pytest.approx([4870, 5300, 5804])
    # change 2025: 934 / 4,870
    assert total["points"][-1]["change_from_first"] == pytest.approx(934 / 4870)
    # the area filter says how many airports were added up
    assert any("4" in f for f in result["about"]["filters"])

    # ratio worked out again from the added parts, not the mean of four ratios:
    # 2025: 5,804 / (4,000 + 2,000 + 1,000 + 180 = 7,180) = 0.80836  (mean of ratios would be 0.755)
    lf = run_tool(tiny_db, "traffic_trend", {"measure": "load_factor", "region": "New England"})
    assert lf["data"]["series"][0]["points"][-1]["value"] == pytest.approx(5804 / 7180)

    # states and region both given: both must match -> only BOS (MA is in New England, CA is not)
    both = run_tool(tiny_db, "traffic_trend", {"measure": "departures", "states": ["MA", "CA"], "region": "New England"})
    assert set(both["data"]["series"][0]["airports"]) == {"BOS"}
    # BOS 2025 passenger departures: 10 * 4 = 40
    assert both["data"]["series"][0]["points"][-1]["value"] == pytest.approx(40)

    # states only: CA = LAX + SNA; departures 2025 = 60 + 12 = 72
    ca = run_tool(tiny_db, "traffic_trend", {"measure": "departures", "states": ["CA"]})
    assert set(ca["data"]["series"][0]["airports"]) == {"LAX", "SNA"}
    assert ca["data"]["series"][0]["points"][-1]["value"] == pytest.approx(72)


# ---------------------------------------------------------------------------
# 4. delay measures are 2025 only
# ---------------------------------------------------------------------------


def test_trend_delay_measure_2025_only(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "nas_delay_per_flight", "airports": ["BOS"]})
    points = result["data"]["series"][0]["points"]
    # by year -> one 2025 point: 1,600 / 200 = 8
    assert [p["year"] for p in points] == [2025]
    assert points[0]["value"] == pytest.approx(8)
    assert result["about"]["data_period"] == "2025 (Jan–Dec)"
    assert NOTE_DELAYS in _about_texts(result)

    # by month: Jan 800 / 100 = 8, Jul 8
    monthly = run_tool(tiny_db, "traffic_trend", {"measure": "nas_delay_per_flight", "airports": ["BOS"], "by": "month"})
    m_points = monthly["data"]["series"][0]["points"]
    assert [(p["year"], p["month"]) for p in m_points] == [(2025, 1), (2025, 7)]
    assert [p["value"] for p in m_points] == pytest.approx([8, 8])

    # LAX taxi-out 22; ANC late_share 12 / 100 = 0.12 per month; LAX cancel_rate 3 / 100 = 0.03
    taxi = run_tool(tiny_db, "traffic_trend", {"measure": "taxi_out_min", "airports": ["LAX"]})
    assert taxi["data"]["series"][0]["points"][0]["value"] == pytest.approx(22)
    late = run_tool(tiny_db, "traffic_trend", {"measure": "late_share", "airports": ["ANC"], "by": "month"})
    assert [p["value"] for p in late["data"]["series"][0]["points"]] == pytest.approx([0.12, 0.12])
    cancel = run_tool(tiny_db, "traffic_trend", {"measure": "cancel_rate", "airports": ["LAX"]})
    assert cancel["data"]["series"][0]["points"][0]["value"] == pytest.approx(0.03)

    # BTV has no delay rows: its series has no points (only periods with data)
    btv = run_tool(tiny_db, "traffic_trend", {"measure": "nas_delay_per_flight", "airports": ["BTV"]})
    assert btv["data"]["series"][0]["points"] == []


# ---------------------------------------------------------------------------
# 5. route_mix by destination and by airline
# ---------------------------------------------------------------------------


def test_route_mix_by_destination(tiny_db):
    result = run_tool(tiny_db, "route_mix", {"airport": "LAX"})
    data = result["data"]
    assert data["airport"] == "LAX"
    assert data["year"] == 2025
    assert data["group_by"] == "destination"
    assert data["passengers_only"] is True
    # totals: departures 40 + 20 = 60; seats 4,000 + 2,000 = 6,000; passengers 1,640*2 + 820*2 = 4,920
    assert data["totals"] == pytest.approx({"departures": 60, "seats": 6000, "passengers": 4920})
    # by departures high -> low: JFK 40, MEX 20
    assert _groups(result) == ["JFK", "MEX"]
    jfk = _row(result, "JFK")
    assert (jfk["departures"], jfk["seats"], jfk["passengers"]) == pytest.approx((40, 4000, 3280))
    # 40 / 60, 4,000 / 6,000, 3,280 / 4,920 = 2/3 each
    assert jfk["departures_share"] == pytest.approx(2 / 3)
    assert jfk["seats_share"] == pytest.approx(2 / 3)
    assert jfk["passengers_share"] == pytest.approx(2 / 3)
    mex = _row(result, "MEX")
    assert (mex["departures"], mex["seats"], mex["passengers"]) == pytest.approx((20, 2000, 1640))
    # international: MEX 20 / 60 = 1/3; long-haul: none (JFK 2,475 < 3,000); cargo 0
    assert data["international_share"] == pytest.approx(1 / 3)
    assert data["long_haul_share"] == pytest.approx(0)
    assert data["cargo_share"] == pytest.approx(0)
    assert result["about"]["data_period"] == "2025"
    assert NOTE_LONG_HAUL in result["about"]["assumptions"]

    # BOS: ATL 20 and MCO 20 tie on departures -> by name A->Z: ATL, MCO; 2025 passengers 700+884 = 1,584
    bos = run_tool(tiny_db, "route_mix", {"airport": "BOS"})
    assert _groups(bos) == ["ATL", "MCO"]
    assert _row(bos, "ATL")["passengers"] == pytest.approx(1584)
    assert _row(bos, "ATL")["departures_share"] == pytest.approx(0.5)

    # year 2019: BOS-ATL passengers 720 + 720 = 1,440
    bos19 = run_tool(tiny_db, "route_mix", {"airport": "BOS", "year": 2019})
    assert bos19["data"]["year"] == 2019
    assert _row(bos19, "ATL")["passengers"] == pytest.approx(1440)
    assert bos19["about"]["data_period"] == "2019"


def test_route_mix_by_airline(tiny_db):
    result = run_tool(tiny_db, "route_mix", {"airport": "LAX", "group_by": "airline"})
    # AA 40 departures, AM 20
    assert _groups(result) == ["AA", "AM"]
    aa = _row(result, "AA")
    assert aa["airline_name"] == "American Airlines Inc."
    assert aa["departures"] == pytest.approx(40)
    assert aa["departures_share"] == pytest.approx(2 / 3)  # 40 / 60
    assert _row(result, "AM")["airline_name"] == "Aerovias de Mexico"
    assert NOTE_AIRLINE in result["about"]["assumptions"]

    # ANC with cargo: 5X 50 first, then AS 20 and DL 20 (tie -> A->Z by code or name gives AS, DL)
    anc = run_tool(tiny_db, "route_mix", {"airport": "ANC", "group_by": "airline", "passengers_only": False})
    assert _groups(anc) == ["5X", "AS", "DL"]
    assert _row(anc, "5X")["departures_share"] == pytest.approx(50 / 90)


# ---------------------------------------------------------------------------
# 6. distance bands
# ---------------------------------------------------------------------------


def test_route_mix_distance_band(tiny_db):
    # LAX: MEX 1,555 mi -> "1,000-1,999" (20); JFK 2,475 -> "2,000-2,999" (40). Natural order, not by departures.
    lax = run_tool(tiny_db, "route_mix", {"airport": "LAX", "group_by": "distance_band"})
    assert _groups(lax) == ["1,000-1,999", "2,000-2,999"]
    assert _row(lax, "2,000-2,999")["departures"] == pytest.approx(40)

    # BOS: ATL 946 -> "500-999"; MCO 1,121 -> "1,000-1,999"
    bos = run_tool(tiny_db, "route_mix", {"airport": "BOS", "group_by": "distance_band"})
    assert _groups(bos) == ["500-999", "1,000-1,999"]

    # MHT: BWI 377 -> "under 500"
    mht = run_tool(tiny_db, "route_mix", {"airport": "MHT", "group_by": "distance_band"})
    assert _groups(mht) == ["under 500"]
    assert _row(mht, "under 500")["departures_share"] == pytest.approx(1.0)

    # ANC with cargo: SEA 1,448 -> 1,000-1,999 (20); SDF 2,864 -> 2,000-2,999 (50); ATL 3,417 -> 3,000+ (20)
    anc = run_tool(tiny_db, "route_mix", {"airport": "ANC", "group_by": "distance_band", "passengers_only": False})
    assert _groups(anc) == ["1,000-1,999", "2,000-2,999", "3,000+"]
    assert [r["departures"] for r in anc["data"]["groups"]] == pytest.approx([20, 50, 20])
    # shares: 20/90, 50/90, 20/90
    assert [r["departures_share"] for r in anc["data"]["groups"]] == pytest.approx([20 / 90, 50 / 90, 20 / 90])

    # the bands are fixed: long_haul_miles does not move them
    moved = run_tool(
        tiny_db,
        "route_mix",
        {"airport": "ANC", "group_by": "distance_band", "passengers_only": False, "long_haul_miles": 2000},
    )
    assert _groups(moved) == ["1,000-1,999", "2,000-2,999", "3,000+"]


# ---------------------------------------------------------------------------
# 7. aircraft size edges (own DuckDB, P42)
# ---------------------------------------------------------------------------


def _edge_db(tmp_path):
    """A small DuckDB with only the seat-size edge rows (P42).

    TST, 2025, month 1 (seats / departures = seats per flight):
      R1  99 / 1   =  99 -> regional       passengers 90
      R2  300 / 3  = 100 -> single-aisle   passengers 270
      R3  916 / 4  = 229 -> single-aisle   passengers 800
      R4  1150 / 5 = 230 -> wide-body      passengers 1,000
      R5  0 seats, 6 departures -> cargo   passengers 0, freight 50,000
    NOR is an airport with no route rows at all.
    """
    path = tmp_path / "edges.duckdb"
    con = duckdb.connect(str(path))
    create_schema(con)
    con.executemany(
        "INSERT INTO airports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("TST", "Test Edge Airport", "Testville", "KS", 38.0, -97.0, "medium", 2, 9000),
            ("NOR", "No Routes Airport", "Norville", "KS", 39.0, -98.0, "small", 1, 5000),
        ],
    )
    con.executemany(
        "INSERT INTO enplanements VALUES (?, ?, ?, ?)",
        [("TST", 2025, 500_000, "S"), ("NOR", 2025, 200_000, "N")],
    )
    # year, month, origin, dest, dest_country, carrier, carrier_name, aircraft_type,
    # departures, seats, passengers, freight_lbs, distance_mi, is_passenger
    con.executemany(
        "INSERT INTO route_traffic VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (2025, 1, "TST", "AAA", "US", "XA", "Edge Air A", 1, 1, 99, 90, 0.0, 400.0, True),
            (2025, 1, "TST", "BBB", "US", "XA", "Edge Air A", 2, 3, 300, 270, 0.0, 600.0, True),
            (2025, 1, "TST", "CCC", "US", "XB", "Edge Air B", 3, 4, 916, 800, 0.0, 1200.0, True),
            (2025, 1, "TST", "DDD", "US", "XB", "Edge Air B", 4, 5, 1150, 1000, 0.0, 2500.0, True),
            (2025, 1, "TST", "EEE", "US", "XC", "Edge Cargo", 5, 6, 0, 0, 50_000.0, 900.0, False),
        ],
    )
    con.close()
    return open_airport_db(path)


def test_route_mix_aircraft_size_edges(tmp_path):
    con = _edge_db(tmp_path)
    try:
        result = run_tool(con, "route_mix", {"airport": "TST", "group_by": "aircraft_size", "passengers_only": False})
        # natural order regional -> single-aisle -> wide-body -> cargo
        assert _groups(result) == ["regional", "single-aisle", "wide-body", "cargo"]
        regional = _row(result, "regional")
        # only R1 (99 per flight)
        assert (regional["departures"], regional["seats"], regional["passengers"]) == pytest.approx((1, 99, 90))
        single = _row(result, "single-aisle")
        # R2 (100) + R3 (229): departures 3 + 4 = 7, seats 300 + 916 = 1,216, passengers 270 + 800 = 1,070
        assert (single["departures"], single["seats"], single["passengers"]) == pytest.approx((7, 1216, 1070))
        wide = _row(result, "wide-body")
        # only R4 (230)
        assert (wide["departures"], wide["seats"], wide["passengers"]) == pytest.approx((5, 1150, 1000))
        cargo = _row(result, "cargo")
        assert (cargo["departures"], cargo["seats"], cargo["passengers"]) == pytest.approx((6, 0, 0))
        # totals: departures 1 + 7 + 5 + 6 = 19; seats 99 + 1,216 + 1,150 = 2,465; passengers 90 + 1,070 + 1,000 = 2,160
        assert result["data"]["totals"] == pytest.approx({"departures": 19, "seats": 2465, "passengers": 2160})
        assert single["departures_share"] == pytest.approx(7 / 19)
        assert cargo["departures_share"] == pytest.approx(6 / 19)
        assert result["data"]["cargo_share"] == pytest.approx(6 / 19)

        # passengers only: no cargo group; departures 1 + 7 + 5 = 13
        pax = run_tool(con, "route_mix", {"airport": "TST", "group_by": "aircraft_size"})
        assert _groups(pax) == ["regional", "single-aisle", "wide-body"]
        assert pax["data"]["totals"]["departures"] == pytest.approx(13)
        assert _row(pax, "single-aisle")["departures_share"] == pytest.approx(7 / 13)
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 8. long_haul_miles
# ---------------------------------------------------------------------------


def test_route_mix_long_haul_setting(tiny_db):
    # default 3,000: ANC-ATL 3,417 -> 20 of 40 passenger departures = 0.5
    default = run_tool(tiny_db, "route_mix", {"airport": "ANC"})
    assert default["data"]["long_haul_share"] == pytest.approx(0.5)
    assert NOTE_LONG_HAUL in default["about"]["assumptions"]

    # 1,448: lower edge included -> SEA (1,448) and ATL both count: 40 / 40 = 1.0
    low = run_tool(tiny_db, "route_mix", {"airport": "ANC", "long_haul_miles": 1448})
    assert low["data"]["long_haul_share"] == pytest.approx(1.0)
    # 1,449: SEA no longer counts -> 20 / 40 = 0.5
    edge = run_tool(tiny_db, "route_mix", {"airport": "ANC", "long_haul_miles": 1449})
    assert edge["data"]["long_haul_share"] == pytest.approx(0.5)
    # 3,500: none (ATL 3,417 < 3,500) -> 0
    high = run_tool(tiny_db, "route_mix", {"airport": "ANC", "long_haul_miles": 3500})
    assert high["data"]["long_haul_share"] == pytest.approx(0)

    # the note is stated with the long_haul_miles in force
    two = run_tool(tiny_db, "route_mix", {"airport": "ANC", "long_haul_miles": 2000})
    assert any("2,000" in a or "2000" in a for a in two["about"]["assumptions"])

    # out of range -> [500, 6000]
    bad = run_tool(tiny_db, "route_mix", {"airport": "ANC", "long_haul_miles": 400})
    assert "data" not in bad
    assert bad["allowed"] == [500, 6000]


# ---------------------------------------------------------------------------
# 9. with cargo
# ---------------------------------------------------------------------------


def test_route_mix_with_cargo(tiny_db):
    result = run_tool(tiny_db, "route_mix", {"airport": "ANC", "passengers_only": False})
    data = result["data"]
    assert data["passengers_only"] is False
    # totals: departures 20 + 20 + 50 = 90; seats 2,000 + 2,000 + 0 = 4,000; passengers 1,728 + 1,728 + 0 = 3,456
    assert data["totals"] == pytest.approx({"departures": 90, "seats": 4000, "passengers": 3456})
    # SDF 50 first, then ATL 20 and SEA 20 (tie -> A->Z)
    assert _groups(result) == ["SDF", "ATL", "SEA"]
    sdf = _row(result, "SDF")
    assert (sdf["departures"], sdf["seats"], sdf["passengers"]) == pytest.approx((50, 0, 0))
    assert sdf["departures_share"] == pytest.approx(50 / 90)
    assert sdf["seats_share"] == pytest.approx(0)  # 0 / 4,000
    assert sdf["passengers_share"] == pytest.approx(0)  # 0 / 3,456
    assert _row(result, "ATL")["seats_share"] == pytest.approx(0.5)  # 2,000 / 4,000
    # long-haul over departures in scope: ATL 20 / 90 (SDF 2,864 < 3,000)
    assert data["long_haul_share"] == pytest.approx(20 / 90)
    assert data["international_share"] == pytest.approx(0)
    # cargo share is always cargo / all departures: 50 / 90 = 0.5556
    assert data["cargo_share"] == pytest.approx(50 / 90)

    # passengers only: cargo_share is still 50 / 90; SDF is not a group
    pax = run_tool(tiny_db, "route_mix", {"airport": "ANC"})
    assert pax["data"]["cargo_share"] == pytest.approx(50 / 90)
    assert _groups(pax) == ["ATL", "SEA"]
    assert pax["data"]["totals"]["departures"] == pytest.approx(40)


# ---------------------------------------------------------------------------
# 10. shares total 1 (100%)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings",
    [
        {"airport": "BOS"},
        {"airport": "LAX", "group_by": "country"},
        {"airport": "LAX", "group_by": "airline"},
        {"airport": "ANC", "group_by": "distance_band", "passengers_only": False},
        {"airport": "ANC", "group_by": "aircraft_size", "passengers_only": False},
        {"airport": "ANC", "passengers_only": False, "top_n": 1},
        {"airport": "LAX", "top_n": 1},
    ],
)
def test_route_mix_shares_total_100(tiny_db, settings):
    result = run_tool(tiny_db, "route_mix", settings)
    groups = result["data"]["groups"]
    assert groups
    assert sum(r["departures_share"] for r in groups) == pytest.approx(1.0)
    assert sum(r["seats_share"] for r in groups) == pytest.approx(1.0)
    assert sum(r["passengers_share"] for r in groups) == pytest.approx(1.0)
    totals = result["data"]["totals"]
    assert sum(r["departures"] for r in groups) == pytest.approx(totals["departures"])


# ---------------------------------------------------------------------------
# 11-13. delay_causes
# ---------------------------------------------------------------------------


def test_delay_causes_minutes_and_per_flight(tiny_db):
    result = run_tool(tiny_db, "delay_causes", {"airports": ["BOS", "LAX"]})
    assert [e["iata"] for e in result["data"]["airports"]] == ["BOS", "LAX"]

    bos = _entry(result, "BOS")
    assert bos["arriving_flights"] == pytest.approx(200)  # 100 per month * 2
    assert bos["total_delay_min"] == pytest.approx(4800)  # (800+600+300+700+0) * 2
    causes = bos["causes"]
    assert set(causes) == set(CAUSES)
    # minutes = per month * 2; per_flight = minutes / 200; share = minutes / 4,800
    expected_bos = {
        "nas": (1600, 8, 1600 / 4800),
        "carrier": (1200, 6, 0.25),
        "weather": (600, 3, 0.125),
        "late_aircraft": (1400, 7, 1400 / 4800),
        "security": (0, 0, 0),
    }
    for cause, (minutes, per_flight, share) in expected_bos.items():
        assert causes[cause]["minutes"] == pytest.approx(minutes), cause
        assert causes[cause]["per_flight"] == pytest.approx(per_flight), cause
        assert causes[cause]["share"] == pytest.approx(share), cause

    lax = _entry(result, "LAX")
    assert lax["arriving_flights"] == pytest.approx(200)
    assert lax["total_delay_min"] == pytest.approx(5220)  # (1,000+700+100+800+10) * 2
    expected_lax = {
        "nas": (2000, 10, 2000 / 5220),
        "carrier": (1400, 7, 1400 / 5220),
        "weather": (200, 1, 200 / 5220),
        "late_aircraft": (1600, 8, 1600 / 5220),
        "security": (20, 0.1, 20 / 5220),
    }
    for cause, (minutes, per_flight, share) in expected_lax.items():
        assert lax["causes"][cause]["minutes"] == pytest.approx(minutes), cause
        assert lax["causes"][cause]["per_flight"] == pytest.approx(per_flight), cause
        assert lax["causes"][cause]["share"] == pytest.approx(share), cause

    assert result["about"]["data_period"] == "2025 (Jan–Dec)"
    texts = _about_texts(result)
    assert NOTE_DELAYS in texts
    assert CAUSES_NOTE in texts


def test_delay_causes_by_month(tiny_db):
    result = run_tool(tiny_db, "delay_causes", {"airports": ["BOS"], "by": "month"})
    months = _entry(result, "BOS")["months"]
    assert [m["month"] for m in months] == [1, 7]
    for m in months:
        assert m["arriving_flights"] == pytest.approx(100)
        assert m["total_delay_min"] == pytest.approx(2400)  # 800+600+300+700+0
        assert m["causes"]["nas"]["minutes"] == pytest.approx(800)
        assert m["causes"]["nas"]["per_flight"] == pytest.approx(8)  # 800 / 100
        assert m["causes"]["weather"]["share"] == pytest.approx(0.125)  # 300 / 2,400
        assert m["causes"]["late_aircraft"]["per_flight"] == pytest.approx(7)  # 700 / 100


def test_delay_causes_no_data_says_missing(tiny_db):
    result = run_tool(tiny_db, "delay_causes", {"airports": ["BTV", "BOS"]})
    # BTV stays in the list, in the order asked
    assert [e["iata"] for e in result["data"]["airports"]] == ["BTV", "BOS"]
    btv = _entry(result, "BTV")
    assert btv["arriving_flights"] is None
    assert btv["total_delay_min"] is None
    causes = btv["causes"]
    if causes is not None:
        for cause in CAUSES:
            assert causes[cause] is None or all(v is None for v in causes[cause].values()), cause
    assert "BTV has no delay data for 2025." in result["about"]["missing"]
    assert NOTE_DELAYS in _about_texts(result)
    # BOS is unaffected
    assert _entry(result, "BOS")["total_delay_min"] == pytest.approx(4800)


# ---------------------------------------------------------------------------
# Extra tests: errors, names, "other" row, consistency with compute_measures
# ---------------------------------------------------------------------------


def test_tools_registered():
    for name in ("traffic_trend", "route_mix", "delay_causes"):
        assert name in TOOLS


def test_trend_unknown_measure_refused(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "growth_long", "airports": ["BOS"]})
    assert "data" not in result
    assert set(result["allowed"]) == TREND_MEASURES
    assert len(result["allowed"]) == 9


def test_trend_airports_and_area_both_or_neither_refused(tiny_db):
    both = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"], "states": ["MA"]})
    assert "data" not in both
    assert sorted(both["allowed"]) == AREA_OR_AIRPORTS

    neither = run_tool(tiny_db, "traffic_trend", {"measure": "passengers"})
    assert "data" not in neither
    assert sorted(neither["allowed"]) == AREA_OR_AIRPORTS

    with_region = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"], "region": "New England"})
    assert sorted(with_region["allowed"]) == AREA_OR_AIRPORTS


def test_trend_several_airports_names_and_repeats(tiny_db):
    # order asked, "Santa Ana" -> SNA, "lax" repeats LAX -> shown once
    result = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["LAX", "Santa Ana", "lax"]})
    series = result["data"]["series"]
    assert [s["name"] for s in series] == ["LAX", "SNA"]
    # SNA 2025: 504 * 2 = 1,008; change vs 2019 960: 48 / 960 = 0.05
    sna = series[1]["points"]
    assert sna[-1]["value"] == pytest.approx(1008)
    assert sna[-1]["change_from_first"] == pytest.approx(0.05)
    # LAX 2024 same as 2019 (4,800): change 0
    assert series[0]["points"][1]["change_from_first"] == pytest.approx(0)


def test_route_mix_by_country(tiny_db):
    result = run_tool(tiny_db, "route_mix", {"airport": "LAX", "group_by": "country"})
    # US 40 (JFK), MX 20 (MEX)
    assert _groups(result) == ["US", "MX"]
    assert _row(result, "MX")["departures_share"] == pytest.approx(1 / 3)  # 20 / 60


def test_route_mix_other_row(tiny_db):
    # LAX top_n 1: JFK, then "other" = MEX (1 group): 20 departures, 2,000 seats, 1,640 passengers
    lax = run_tool(tiny_db, "route_mix", {"airport": "LAX", "top_n": 1})
    assert _groups(lax) == ["JFK", "other"]
    other = _row(lax, "other")
    assert other["groups"] == 1
    assert (other["departures"], other["seats"], other["passengers"]) == pytest.approx((20, 2000, 1640))
    assert other["departures_share"] == pytest.approx(1 / 3)  # 20 / 60

    # ANC with cargo, top_n 1: SDF, then "other" = ATL + SEA (2 groups): 40 departures, 4,000 seats
    anc = run_tool(tiny_db, "route_mix", {"airport": "ANC", "passengers_only": False, "top_n": 1})
    assert _groups(anc) == ["SDF", "other"]
    anc_other = _row(anc, "other")
    assert anc_other["groups"] == 2
    assert anc_other["departures"] == pytest.approx(40)
    assert anc_other["seats_share"] == pytest.approx(1.0)  # 4,000 / 4,000

    # exactly top_n groups -> no "other" row
    bos = run_tool(tiny_db, "route_mix", {"airport": "BOS", "top_n": 2})
    assert _groups(bos) == ["ATL", "MCO"]


def test_route_mix_accepts_a_name(tiny_db):
    result = run_tool(tiny_db, "route_mix", {"airport": "Santa Ana"})
    assert result["data"]["airport"] == "SNA"
    assert _groups(result) == ["SJC"]


def test_route_mix_no_departures_says_missing(tmp_path):
    con = _edge_db(tmp_path)
    try:
        result = run_tool(con, "route_mix", {"airport": "NOR"})
        data = result["data"]
        assert data["groups"] == []
        assert data["long_haul_share"] is None
        assert data["international_share"] is None
        assert data["cargo_share"] is None
        assert "No departures from NOR in 2025." in result["about"]["missing"]
    finally:
        con.close()


def test_route_mix_consistent_with_compute_measures(tiny_db):
    measures = compute_measures(tiny_db)
    for iata in ("ANC", "LAX", "BOS"):
        data = run_tool(tiny_db, "route_mix", {"airport": iata})["data"]
        for name in ("long_haul_share", "international_share", "cargo_share"):
            assert data[name] == pytest.approx(measures[iata][name]), (iata, name)


def test_trend_2025_consistent_with_compute_measures(tiny_db):
    measures = compute_measures(tiny_db)
    for name in ("passengers", "departures", "seats", "load_factor", "nas_delay_per_flight", "taxi_out_min"):
        result = run_tool(tiny_db, "traffic_trend", {"measure": name, "airports": ["ANC"]})
        last = result["data"]["series"][0]["points"][-1]
        assert last["year"] == 2025
        assert last["value"] == pytest.approx(measures["ANC"][name]), name


def test_delay_causes_consistent_with_compute_measures(tiny_db):
    measures = compute_measures(tiny_db)
    result = run_tool(tiny_db, "delay_causes", {"airports": ["BOS", "LAX", "ANC"]})
    for iata in ("BOS", "LAX", "ANC"):
        nas = _entry(result, iata)["causes"]["nas"]["per_flight"]
        assert nas == pytest.approx(measures[iata]["nas_delay_per_flight"]), iata


# ---------------------------------------------------------------------------
# Real data
# ---------------------------------------------------------------------------


@pytest.mark.realdata
def test_real_anchorage_long_haul_share(real_db):
    pax = run_tool(real_db, "route_mix", {"airport": "ANC"})
    # about 2.8% of passenger departures (measured 0.02764)
    assert pax["data"]["long_haul_share"] == pytest.approx(0.0276, abs=0.002)
    with_cargo = run_tool(real_db, "route_mix", {"airport": "ANC", "passengers_only": False})
    # about 31% with cargo (measured 0.3103)
    assert with_cargo["data"]["long_haul_share"] == pytest.approx(0.31, abs=0.005)
