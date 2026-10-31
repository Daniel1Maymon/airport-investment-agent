"""Step 9 tests: the name resolver, Census regions and the `find_airports` tool.

What the builder must follow (names the tests rely on)
------------------------------------------------------
app/tools/resolver.py
* `AirportMatch` with fields `iata, name, city, state, size` (read by attribute).
  `size` = the 2025 FAA hub size from `enplanements.hub_type` (P26):
  L -> "large", M -> "medium", S -> "small", N -> "non-hub"; no 2025 hub type -> None.
* `resolve_airport(con, text) -> list[AirportMatch]`, sorted by code; [] = not found.
  Rules in order, stopping at the first rule that finds something (P25):
  (1) code in our airports table, any case; (2) abbreviation LA / NYC / SF / DC
  (P5), any case -> every airport in that city; (3) exact city, any case;
  (4) exact airport name, any case; (5) part of the airport name, any case,
  only for text of 3+ characters. Spaces at the ends are ignored.
* `REGIONS: dict[str, list[str]]`: exactly the 4 US Census regions and 9
  divisions, keyed by their Census names ("New England", "Middle Atlantic", ...).
* `resolve_region(name) -> list[str]`: the states of a region, name in any case.
  An unknown region raises `ValueError`.

app/tools/find.py  (imported by app/tools/__init__.py, so `import app.tools` registers it)
* Tool `find_airports` (P27). Settings: `text` (1-100 chars), `states` (StateList),
  `region`, `size` (large/medium/small/non-hub), `near_airport` (AirportCode),
  `within_miles` (1-500, default 50).
* Result: `result["data"]["airports"]` = list of dicts with exactly the keys
  `iata, name, city, state, size` (+ `distance_mi`, 1 decimal, with `near_airport`).
  Sorted by code; by distance with `near_airport`. At most 25 rows; when more
  matched, a line in `about` (filters, missing or assumptions) gives the number
  that matched. No match -> [] and `about.missing` holds REFUSALS["airport_not_found"].
* Errors (`{"error", "allowed"}`): no filter -> allowed = the 5 filter names;
  `within_miles` without `near_airport`; unknown region -> allowed = sorted(REGIONS);
  `within_miles` outside 1-500 -> allowed = [1, 500].

app/tools/base.py
* `AirportCode`: one airport. `run_tool` turns names into codes AFTER the pydantic
  checks, only in settings typed `AirportList` or `AirportCode` (P28), never in
  `states`. 1 match -> code; 0 -> error containing REFUSALS["airport_not_found"],
  allowed = []; several -> error, allowed = the matching codes. Tool does not run.

Tiny data used (tests/fixtures/TINY_DATA.md)
--------------------------------------------
  code  city              state  hub 2025 -> size   lat     lon
  ANC   Anchorage         AK     M  medium          61.17  -149.98
  BHB   Bar Harbor        ME     N  non-hub         44.45   -68.36
  BOS   Boston            MA     L  large           42.36   -71.01
  BTV   South Burlington  VT     S  small           44.47   -73.15
  LAX   Los Angeles       CA     L  large           33.94  -118.41
  MHT   Manchester        NH     S  small           42.93   -71.44
  SNA   Santa Ana         CA     M  medium          33.68  -117.87
Names containing "International": BOS, BTV, LAX, ANC (MHT is "Regional",
BHB "Hancock County-Bar Harbor Airport", SNA "John Wayne Airport-Orange County Airport").
"""

import duckdb
import pytest
from pydantic import BaseModel

import app.tools  # noqa: F401  (must register every tool, find_airports included)
from app.db import open_airport_db
from app.refusals import REFUSALS
from app.tools.base import TOOLS, US_STATES, AirportList, StateList, ToolResult, register, run_tool
from loader.common import create_schema

FIND = "find_airports"
NOT_FOUND = REFUSALS["airport_not_found"]
ABOUT_KEYS = {"data_period", "filters", "missing", "assumptions"}
FILTER_NAMES = ["near_airport", "region", "size", "states", "text"]

ROWS = {
    "ANC": {"iata": "ANC", "name": "Ted Stevens Anchorage International Airport",
            "city": "Anchorage", "state": "AK", "size": "medium"},
    "BHB": {"iata": "BHB", "name": "Hancock County-Bar Harbor Airport",
            "city": "Bar Harbor", "state": "ME", "size": "non-hub"},
    "BOS": {"iata": "BOS", "name": "General Edward Lawrence Logan International Airport",
            "city": "Boston", "state": "MA", "size": "large"},
    "BTV": {"iata": "BTV", "name": "Burlington International Airport",
            "city": "South Burlington", "state": "VT", "size": "small"},
    "LAX": {"iata": "LAX", "name": "Los Angeles International Airport",
            "city": "Los Angeles", "state": "CA", "size": "large"},
    "MHT": {"iata": "MHT", "name": "Manchester-Boston Regional Airport",
            "city": "Manchester", "state": "NH", "size": "small"},
    "SNA": {"iata": "SNA", "name": "John Wayne Airport-Orange County Airport",
            "city": "Santa Ana", "state": "CA", "size": "medium"},
}  # fmt: skip

# The US Census Bureau regions and divisions, as published
# (census.gov "Census Regions and Divisions of the United States").
CENSUS_DIVISIONS = {
    "New England": ["CT", "ME", "MA", "NH", "RI", "VT"],
    "Middle Atlantic": ["NJ", "NY", "PA"],
    "East North Central": ["IL", "IN", "MI", "OH", "WI"],
    "West North Central": ["IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South Atlantic": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"],
    "East South Central": ["AL", "KY", "MS", "TN"],
    "West South Central": ["AR", "LA", "OK", "TX"],
    "Mountain": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"],
    "Pacific": ["AK", "CA", "HI", "OR", "WA"],
}
CENSUS_REGIONS = {
    "Northeast": ["New England", "Middle Atlantic"],
    "Midwest": ["East North Central", "West North Central"],
    "South": ["South Atlantic", "East South Central", "West South Central"],
    "West": ["Mountain", "Pacific"],
}


def _resolver():
    """The Step 9 resolver module (imported here so each test fails on its own)."""
    from app.tools import resolver

    return resolver


def _codes(matches):
    return [m.iata for m in matches]


def _is_error(result):
    return isinstance(result, dict) and "error" in result and "allowed" in result


def _airports(result):
    assert not _is_error(result), result
    assert set(result) == {"data", "about"}
    assert set(result["about"]) == ABOUT_KEYS
    return result["data"]["airports"]


def _about_text(result):
    about = result["about"]
    return " ".join([about["data_period"], *about["filters"], *about["missing"], *about["assumptions"]])


# ---- the listed tests ---------------------------------------------------------


# 1
def test_code_any_case(tiny_db):
    resolve = _resolver().resolve_airport
    # The tiny data has no SFO; BOS and SNA show the same rule (1).
    assert _codes(resolve(tiny_db, "bos")) == ["BOS"]
    assert _codes(resolve(tiny_db, "Sna")) == ["SNA"]
    assert _codes(resolve(tiny_db, "  lax  ")) == ["LAX"]  # spaces at the ends ignored

    [match] = resolve(tiny_db, "bos")
    assert (match.iata, match.name, match.city, match.state, match.size) == (
        "BOS", "General Edward Lawrence Logan International Airport", "Boston", "MA", "large",
    )  # fmt: skip


# 2
def test_city(tiny_db):
    resolve = _resolver().resolve_airport
    assert _codes(resolve(tiny_db, "Santa Ana")) == ["SNA"]
    assert _codes(resolve(tiny_db, "santa ana")) == ["SNA"]
    assert _codes(resolve(tiny_db, " Santa Ana ")) == ["SNA"]
    [match] = resolve(tiny_db, "Santa Ana")
    assert match.size == "medium"  # SNA hub type 2025 = M
    # Rule 3 (city) stops the search: "Boston" is BOS's city, so MHT
    # ("Manchester-Boston Regional Airport", a name match) is not added.
    assert _codes(resolve(tiny_db, "Boston")) == ["BOS"]


# 3
def test_part_of_name(tiny_db):
    resolve = _resolver().resolve_airport
    assert _codes(resolve(tiny_db, "Logan")) == ["BOS"]
    assert _codes(resolve(tiny_db, "john wayne")) == ["SNA"]
    # BTV's city is "South Burlington", so "Burlington" is found by its name.
    assert _codes(resolve(tiny_db, "Burlington")) == ["BTV"]
    # Several matches, sorted by code.
    assert _codes(resolve(tiny_db, "International")) == ["ANC", "BOS", "BTV", "LAX"]
    # Exact full name (rule 4), any case.
    assert _codes(resolve(tiny_db, "los angeles international airport")) == ["LAX"]
    # Under 3 characters: no part-of-name search ("Lo" is in Logan, Los Angeles).
    assert resolve(tiny_db, "Lo") == []


# 4
def test_abbreviation(tiny_db):
    resolve = _resolver().resolve_airport
    # LA -> Los Angeles (P5); the only Los Angeles airport in the tiny data is LAX.
    assert "LAX" in _codes(resolve(tiny_db, "LA"))
    assert _codes(resolve(tiny_db, "LA")) == ["LAX"]
    assert _codes(resolve(tiny_db, "la")) == ["LAX"]
    [match] = resolve(tiny_db, "LA")
    assert (match.city, match.state, match.size) == ("Los Angeles", "CA", "large")


# 5
def test_not_found(tiny_db):
    resolve = _resolver().resolve_airport
    assert resolve(tiny_db, "Atlantis") == []
    assert resolve(tiny_db, "XYZ") == []  # looks like a code, but not in our list

    # Through the tool: an empty list and the "airport not found" message.
    result = run_tool(tiny_db, FIND, {"text": "Atlantis"})
    assert _airports(result) == []
    assert NOT_FOUND in result["about"]["missing"]


# 6
def test_new_england_states():
    resolver = _resolver()
    assert sorted(resolver.resolve_region("New England")) == ["CT", "MA", "ME", "NH", "RI", "VT"]
    assert sorted(resolver.resolve_region("new england")) == ["CT", "MA", "ME", "NH", "RI", "VT"]
    assert sorted(resolver.REGIONS["New England"]) == ["CT", "MA", "ME", "NH", "RI", "VT"]


# 7
def test_unknown_region_lists_regions(tiny_db):
    resolver = _resolver()
    with pytest.raises(ValueError):
        resolver.resolve_region("Atlantis")

    # The 13 names must be there before we use REGIONS as the expected list.
    assert set(resolver.REGIONS) == set(CENSUS_DIVISIONS) | set(CENSUS_REGIONS)
    result = run_tool(tiny_db, FIND, {"region": "Atlantis"})
    assert _is_error(result)
    assert result["allowed"] == sorted(resolver.REGIONS)


# 8a
def test_find_by_state(tiny_db):
    assert _airports(run_tool(tiny_db, FIND, {"states": ["CA"]})) == [ROWS["LAX"], ROWS["SNA"]]
    # Several states, lower case accepted; sorted by code: BOS, BTV, MHT.
    result = run_tool(tiny_db, FIND, {"states": ["ma", "NH", "VT"]})
    assert _airports(result) == [ROWS["BOS"], ROWS["BTV"], ROWS["MHT"]]


# 8b
def test_find_by_size(tiny_db):
    # 2025 hub types: BOS L, LAX L, SNA M, ANC M, MHT S, BTV S, BHB N.
    assert _airports(run_tool(tiny_db, FIND, {"size": "large"})) == [ROWS["BOS"], ROWS["LAX"]]
    assert _airports(run_tool(tiny_db, FIND, {"size": "medium"})) == [ROWS["ANC"], ROWS["SNA"]]
    assert _airports(run_tool(tiny_db, FIND, {"size": "small"})) == [ROWS["BTV"], ROWS["MHT"]]
    assert _airports(run_tool(tiny_db, FIND, {"size": "non-hub"})) == [ROWS["BHB"]]


# 9
def test_near_airport_within_miles(tiny_db):
    # Great-circle (haversine) distance LAX (33.94, -118.41) -> SNA (33.68, -117.87):
    #   dlat = -0.26 deg = -0.0045379 rad, dlon = 0.54 deg = 0.0094248 rad
    #   a = sin^2(dlat/2) + cos(33.94) * cos(33.68) * sin^2(dlon/2)
    #     = 0.0022689^2 + 0.82961 * 0.83213 * 0.0047124^2
    #     = 5.148e-6 + 0.69034 * 2.2207e-5 = 2.0479e-5
    #   c = 2 * asin(sqrt(a)) = 2 * 0.0045253 = 0.0090506
    #   d = 3958.8 * 0.0090506 = 35.8 miles
    # Every other tiny airport is over 2,500 miles from LAX.
    result = run_tool(tiny_db, FIND, {"near_airport": "LAX", "within_miles": 50})
    rows = _airports(result)
    assert [r["iata"] for r in rows] == ["SNA"]  # LAX itself is left out
    assert set(rows[0]) == {"iata", "name", "city", "state", "size", "distance_mi"}
    assert {k: v for k, v in rows[0].items() if k != "distance_mi"} == ROWS["SNA"]
    assert rows[0]["distance_mi"] == pytest.approx(35.8, abs=0.5)
    assert rows[0]["distance_mi"] == round(rows[0]["distance_mi"], 1)  # 1 decimal

    # 35.8 > 30, so nothing within 30 miles.
    result = run_tool(tiny_db, FIND, {"near_airport": "LAX", "within_miles": 30})
    assert _airports(result) == []
    assert NOT_FOUND in result["about"]["missing"]


# 10
def test_run_tool_turns_names_into_codes(tiny_db, name_tool):
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["Santa Ana"]})
    assert not _is_error(result), result
    assert name_tool["calls"] == 1
    assert name_tool["settings"].airports == ["SNA"]
    assert result["data"]["airports"] == ["SNA"]


# ---- extras: the resolver ------------------------------------------------------


def test_regions_follow_census_definition():
    resolver = _resolver()
    assert set(resolver.REGIONS) == set(CENSUS_DIVISIONS) | set(CENSUS_REGIONS)
    for division, states in CENSUS_DIVISIONS.items():
        assert sorted(resolver.REGIONS[division]) == sorted(states), division
    for region, divisions in CENSUS_REGIONS.items():
        expected = sorted(s for d in divisions for s in CENSUS_DIVISIONS[d])
        assert sorted(resolver.REGIONS[region]) == expected, region
    # Counts: Northeast 6+3=9, Midwest 5+7=12, South 9+4+4=17, West 8+5=13 -> 51.
    assert [len(resolver.REGIONS[r]) for r in ("Northeast", "Midwest", "South", "West")] == [9, 12, 17, 13]


def test_four_regions_cover_every_state_once():
    resolver = _resolver()
    together = [s for r in ("Northeast", "Midwest", "South", "West") for s in resolver.REGIONS[r]]
    assert len(together) == 51  # no state twice
    assert sorted(together) == sorted(US_STATES)  # 50 states + DC, DC in the South
    assert "DC" in resolver.REGIONS["South Atlantic"]


def test_resolve_region_any_case():
    resolver = _resolver()
    assert sorted(resolver.resolve_region("PACIFIC")) == ["AK", "CA", "HI", "OR", "WA"]
    assert sorted(resolver.resolve_region("middle atlantic")) == ["NJ", "NY", "PA"]


def test_resolver_sql_text_is_harmless(tiny_db):
    resolve = _resolver().resolve_airport
    assert resolve(tiny_db, "x'; DROP TABLE airports; --") == []
    assert resolve(tiny_db, "%%%") == []  # not a wildcard that matches every name
    assert resolve(tiny_db, "___") == []
    assert tiny_db.execute("SELECT COUNT(*) FROM airports").fetchone()[0] == 7


# ---- extras: find_airports -------------------------------------------------------


def test_find_airports_is_registered():
    assert FIND in TOOLS


def test_find_by_region(tiny_db):
    # New England: BHB (ME), BOS (MA), BTV (VT), MHT (NH); sorted by code.
    assert [r["iata"] for r in _airports(run_tool(tiny_db, FIND, {"region": "New England"}))] == [
        "BHB", "BOS", "BTV", "MHT",
    ]  # fmt: skip
    # Pacific (any case): AK, CA -> ANC, LAX, SNA.
    assert [r["iata"] for r in _airports(run_tool(tiny_db, FIND, {"region": "pacific"}))] == [
        "ANC", "LAX", "SNA",
    ]  # fmt: skip
    assert [r["iata"] for r in _airports(run_tool(tiny_db, FIND, {"region": "West"}))] == ["ANC", "LAX", "SNA"]


def test_all_filters_must_match(tiny_db):
    # states CA, MA  AND  New England -> only MA -> BOS.
    result = run_tool(tiny_db, FIND, {"states": ["CA", "MA"], "region": "New England"})
    assert _airports(result) == [ROWS["BOS"]]
    # "International" names: ANC, BOS, BTV, LAX; in CA -> LAX.
    result = run_tool(tiny_db, FIND, {"text": "International", "states": ["CA"]})
    assert _airports(result) == [ROWS["LAX"]]
    # New England AND small -> BTV, MHT.
    result = run_tool(tiny_db, FIND, {"region": "New England", "size": "small"})
    assert _airports(result) == [ROWS["BTV"], ROWS["MHT"]]
    # Nothing in both -> empty with the message.
    result = run_tool(tiny_db, FIND, {"states": ["CA"], "region": "New England"})
    assert _airports(result) == []
    assert NOT_FOUND in result["about"]["missing"]


def test_find_by_text_uses_resolver(tiny_db):
    assert _airports(run_tool(tiny_db, FIND, {"text": "Santa Ana"})) == [ROWS["SNA"]]
    assert _airports(run_tool(tiny_db, FIND, {"text": "LA"})) == [ROWS["LAX"]]
    assert _airports(run_tool(tiny_db, FIND, {"text": "Boston"})) == [ROWS["BOS"]]
    # Several matches are all returned, sorted by code.
    result = run_tool(tiny_db, FIND, {"text": "International"})
    assert [r["iata"] for r in _airports(result)] == ["ANC", "BOS", "BTV", "LAX"]


def test_states_setting_is_never_resolved(tiny_db):
    # "LA" in `states` is Louisiana (no tiny airport), not Los Angeles.
    result = run_tool(tiny_db, FIND, {"states": ["LA"]})
    assert _airports(result) == []
    assert NOT_FOUND in result["about"]["missing"]


def test_no_filter_is_an_error(tiny_db):
    result = run_tool(tiny_db, FIND, {})
    assert _is_error(result)
    assert sorted(result["allowed"]) == FILTER_NAMES


def test_within_miles_without_near_airport_is_an_error(tiny_db):
    assert FIND in TOOLS  # else the "no such tool" error would pass this test
    result = run_tool(tiny_db, FIND, {"states": ["CA"], "within_miles": 50})
    assert _is_error(result)
    assert "within_miles" in result["error"] or "near_airport" in result["error"]


def test_setting_limits(tiny_db):
    for miles in (0, 501):
        result = run_tool(tiny_db, FIND, {"near_airport": "LAX", "within_miles": miles})
        assert _is_error(result), miles
        assert result["allowed"] == [1, 500]
    assert not _is_error(run_tool(tiny_db, FIND, {"near_airport": "LAX", "within_miles": 1}))
    assert not _is_error(run_tool(tiny_db, FIND, {"near_airport": "LAX", "within_miles": 500}))

    assert _is_error(run_tool(tiny_db, FIND, {"text": ""}))
    assert _is_error(run_tool(tiny_db, FIND, {"text": "x" * 101}))
    assert not _is_error(run_tool(tiny_db, FIND, {"text": "x" * 100}))

    result = run_tool(tiny_db, FIND, {"size": "huge"})
    assert _is_error(result)
    assert sorted(result["allowed"]) == ["large", "medium", "non-hub", "small"]


def test_near_airport_default_50_and_sorted_by_distance(tiny_db):
    # Haversine from BOS (42.36, -71.01), same working as test 9:
    #   MHT (42.93, -71.44): about 45.0 miles
    #   BTV (44.47, -73.15): about 181.1 miles
    #   BHB (44.45, -68.36): about 196.3 miles
    #   LAX, SNA about 2,600; ANC about 3,370.
    # No within_miles -> 50 -> only MHT.
    rows = _airports(run_tool(tiny_db, FIND, {"near_airport": "BOS"}))
    assert [r["iata"] for r in rows] == ["MHT"]
    assert rows[0]["distance_mi"] == pytest.approx(45.0, abs=0.5)
    # 40 miles: MHT (45) is out.
    assert _airports(run_tool(tiny_db, FIND, {"near_airport": "BOS", "within_miles": 40})) == []
    # 500 miles: sorted by distance (MHT, BTV, BHB), not by code (BHB, BTV, MHT).
    rows = _airports(run_tool(tiny_db, FIND, {"near_airport": "BOS", "within_miles": 500}))
    assert [r["iata"] for r in rows] == ["MHT", "BTV", "BHB"]
    assert rows[1]["distance_mi"] == pytest.approx(181.1, abs=0.5)
    assert rows[2]["distance_mi"] == pytest.approx(196.3, abs=0.5)


def test_near_airport_accepts_a_name(tiny_db):
    # "Santa Ana" -> SNA; LAX is 35.8 miles away (test 9).
    rows = _airports(run_tool(tiny_db, FIND, {"near_airport": "Santa Ana"}))
    assert [r["iata"] for r in rows] == ["LAX"]
    rows = _airports(run_tool(tiny_db, FIND, {"near_airport": "lax"}))
    assert [r["iata"] for r in rows] == ["SNA"]


def test_near_airport_unknown_or_unclear(tiny_db):
    result = run_tool(tiny_db, FIND, {"near_airport": "Atlantis"})
    assert _is_error(result)
    assert NOT_FOUND in result["error"]
    assert result["allowed"] == []

    result = run_tool(tiny_db, FIND, {"near_airport": "International"})
    assert _is_error(result)
    assert result["allowed"] == ["ANC", "BOS", "BTV", "LAX"]


# ---- extras: a separate small database for the 25-row cap and missing sizes ----


def _custom_db(path, airports, enplanements):
    """Build a small airport database with only `airports` and `enplanements` rows."""
    con = duckdb.connect(str(path))
    try:
        create_schema(con)
        con.executemany("INSERT INTO airports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", airports)
        if enplanements:
            con.executemany("INSERT INTO enplanements VALUES (?, ?, ?, ?)", enplanements)
    finally:
        con.close()
    return open_airport_db(path)


def test_more_than_25_matches_capped_with_note(tmp_path):
    # 30 made-up TX airports: TAA ... TAZ (26), TBA ... TBD (4).
    codes = [f"T{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(30)]
    airports = [(c, f"Test Airport {c}", "Testville", "TX", 30.0, -97.0, "small", 1, 5000) for c in codes]
    enplanements = [(c, 2025, 200_000, "S") for c in codes]
    con = _custom_db(tmp_path / "many.duckdb", airports, enplanements)
    try:
        result = run_tool(con, FIND, {"states": ["TX"]})
        rows = _airports(result)
        assert len(rows) == 25
        assert [r["iata"] for r in rows] == sorted(codes)[:25]  # TAA ... TAY
        # `about` says that more matched, with the number: 30.
        assert "30" in _about_text(result)
    finally:
        con.close()


def test_size_filter_drops_airports_without_2025_hub_type(tmp_path):
    airports = [
        (c, f"Test Airport {c}", "Testville", "TX", 30.0, -97.0, "large", 1, 5000)
        for c in ("XXA", "XXB", "XXC", "XXD")
    ]
    enplanements = [
        ("XXA", 2025, 5_000_000, "L"),  # large in 2025
        ("XXB", 2024, 5_000_000, "L"),  # large only in 2024 -> no 2025 size
        ("XXD", 2024, 200_000, "S"),    # small in 2024 ...
        ("XXD", 2025, 5_000_000, "L"),  # ... large in 2025: 2025 counts
        # XXC: no enplanement rows at all -> no size
    ]  # fmt: skip
    con = _custom_db(tmp_path / "sizes.duckdb", airports, enplanements)
    try:
        rows = _airports(run_tool(con, FIND, {"states": ["TX"]}))
        assert {r["iata"]: r["size"] for r in rows} == {"XXA": "large", "XXB": None, "XXC": None, "XXD": "large"}

        result = run_tool(con, FIND, {"states": ["TX"], "size": "large"})
        assert [r["iata"] for r in _airports(result)] == ["XXA", "XXD"]
        assert result["about"]["missing"]  # says airports with no size were left out

        resolve = _resolver().resolve_airport
        [match] = resolve(con, "XXC")
        assert match.size is None
    finally:
        con.close()


# ---- extras: names in any tool's settings (P28) ---------------------------------

NAME_TOOL = "name_test_tool"


class _NameSettings(BaseModel):
    """Settings of a test-only tool with every kind of setting P28 talks about."""

    airports: AirportList = ["BOS"]
    states: StateList | None = None


@pytest.fixture
def name_tool():
    """Register the test-only tool; restore TOOLS exactly as it was afterwards.

    `airport` (one airport, AirportCode) is added here, inside the fixture, so a
    missing AirportCode fails only the tests that use this fixture.
    """
    from app.tools.base import AirportCode

    class _Settings(_NameSettings):
        airport: AirportCode | None = None

    saved = dict(TOOLS)
    state = {"calls": 0, "settings": None}

    @register(NAME_TOOL, "Echoes the airports it was given (test only).", _Settings)
    def _name_test_tool(con, settings):
        state["calls"] += 1
        state["settings"] = settings
        return ToolResult(data={"airports": list(settings.airports)})

    yield state
    TOOLS.clear()
    TOOLS.update(saved)


def test_names_and_codes_mixed(tiny_db, name_tool):
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["bos", "LA", "Burlington", "Santa Ana"]})
    assert not _is_error(result), result
    assert name_tool["settings"].airports == ["BOS", "LAX", "BTV", "SNA"]


def test_name_not_found_stops_the_tool(tiny_db, name_tool):
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["BOS", "Atlantis"]})
    assert _is_error(result)
    assert NOT_FOUND in result["error"]
    assert result["allowed"] == []
    assert name_tool["calls"] == 0


def test_unclear_name_lists_matching_codes(tiny_db, name_tool):
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["International"]})
    assert _is_error(result)
    assert result["allowed"] == ["ANC", "BOS", "BTV", "LAX"]
    assert name_tool["calls"] == 0


def test_pydantic_checks_come_before_names(tiny_db, name_tool):
    # 6 items: the count check (P24) answers first, not "airport not found".
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["Atlantis"] * 6})
    assert _is_error(result)
    assert result["allowed"] == [1, 5]
    assert name_tool["calls"] == 0


def test_states_not_resolved_in_other_tools(tiny_db, name_tool):
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["BOS"], "states": ["LA"]})
    assert not _is_error(result), result
    assert name_tool["settings"].states == ["LA"]  # Louisiana stays Louisiana


def test_airport_code_setting_resolves_one_airport(tiny_db, name_tool):
    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["BOS"], "airport": "Santa Ana"})
    assert not _is_error(result), result
    assert name_tool["settings"].airport == "SNA"

    result = run_tool(tiny_db, NAME_TOOL, {"airports": ["BOS"], "airport": "International"})
    assert _is_error(result)
    assert result["allowed"] == ["ANC", "BOS", "BTV", "LAX"]


def test_all_p5_abbreviations(tmp_path):
    # P5: NYC -> New York, SF -> San Francisco, DC -> Washington, LA -> Los Angeles;
    # every airport in that city is returned, sorted by code.
    airports = [
        ("LGA", "LaGuardia Airport", "New York", "NY", 40.78, -73.87, "large", 2, 7003),
        ("JFK", "John F Kennedy International Airport", "New York", "NY", 40.64, -73.78, "large", 4, 14511),
        ("SFO", "San Francisco International Airport", "San Francisco", "CA", 37.62, -122.38, "large", 4, 11870),
        ("DCA", "Ronald Reagan Washington National Airport", "Washington", "DC", 38.85, -77.04, "large", 3, 7169),
        ("BUR", "Bob Hope Airport", "Burbank", "CA", 34.20, -118.36, "medium", 2, 6886),
    ]  # fmt: skip
    con = _custom_db(tmp_path / "abbrev.duckdb", airports, [])
    try:
        resolve = _resolver().resolve_airport
        assert _codes(resolve(con, "nyc")) == ["JFK", "LGA"]  # two airports, sorted by code
        assert _codes(resolve(con, "NYC")) == ["JFK", "LGA"]
        assert _codes(resolve(con, "sf")) == ["SFO"]
        assert _codes(resolve(con, "DC")) == ["DCA"]
        assert _codes(resolve(con, "sfo")) == ["SFO"]  # the plan's example for rule 1
        assert resolve(con, "LA") == []  # no Los Angeles airport here (BUR is in Burbank)
    finally:
        con.close()
