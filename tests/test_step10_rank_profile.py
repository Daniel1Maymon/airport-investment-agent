"""Step 10 tests: the `rank_airports` and `airport_profile` tools.

What the builder must follow (names the tests rely on)
------------------------------------------------------
app/tools/rank.py and app/tools/profile.py, both imported by app/tools/__init__.py,
so `import app.tools` registers the tools `rank_airports` and `airport_profile`.
The tests call them only through `run_tool(con, name, settings)`.

rank_airports (P30-P33, P35)
* Settings: states, region, size, sort_by (default "score"), order
  ("highest_first" / "lowest_first"), weights (D1..S4, >= 0, total 100, only with
  sort_by "score"), min_enplanements (0-10,000,000, default 100,000), top_n (1-25,
  default 10).
* data = {"sort_by", "order", "airports": [rows]}. Row keys: iata, name, city, state,
  size, national_rank, value, grade; with sort_by "score" also demand_score,
  strain_score, grades, flags, missing.

airport_profile (P34, P35)
* Setting: airports (1-5 names or codes). data = {"airports": [entries]} in the order
  asked, a repeated code once. Entry keys: iata, name, city, state, size, measures,
  final_score, demand_score, strain_score, national_rank, flags, missing, congestion.

The `about` texts are read at run time from docs/implementation-plan.md (P32, P34,
P35) and docs/tools.md ("Known limits"), not copied here.

HAND-WORKED TABLE (tiny dataset, tests/fixtures/TINY_DATA.md, 2025)
===================================================================
Size filter: enplanements 2025 >= 100,000 -> pool BOS, MHT, BTV, LAX, SNA, ANC (6).
BHB (55,000) is out. BTV has no delay rows -> pools of 5 for the delay measures.
Grade (P13) = (number lower + 1/2 x number of OTHER airports with the same value)
              / pool size x 100, 1 decimal.

measure              BOS        MHT        BTV       LAX         SNA        ANC
enplanements         21.0M      1.2M       618k      38.16M      5.1M       2.6M
  grade (6)          4/6=66.7   1/6=16.7   0         5/6=83.3    3/6=50.0   2/6=33.3
passengers           3168       1800       728       4920        1008       3456
  grade (6)          3/6=50.0   2/6=33.3   0         83.3        1/6=16.7   4/6=66.7
departures (pax)     40         16         10        60          12         40
  grade (6)          (3+.5*1)/6=58.3  33.3 0         83.3        16.7       (3+.5)/6=58.3
seats                4000       2000       1000      6000        1200       4000
  grade (6)          58.3       33.3       0         83.3        16.7       58.3
growth_short (D2)    .05        .20        .03       .06         .02        .04
  grade (6)          50.0       83.3       16.7      66.7        0          33.3
growth_long (D1)     .10        .50        .04       .025        .05        .08
  grade (6)          66.7       83.3       16.7      0           33.3       50.0
load_factor (S1)     .792       .90        .728      .82         .84        .864
  grade (6)          16.7       83.3       0         33.3        50.0       66.7
nas_delay (S2)       8          1          None      10          3          2
  grade (5)          3/5=60     0          None      4/5=80      2/5=40     1/5=20
taxi_out_min (S3)    20         12         None      22          14         16
  grade (5)          60         0          None      80          20         40
dep_per_runway (S4)  40/4=10    16/2=8     10/2=5    60/4=15     12/1=12    90/3=30
  grade (6)          2/6=33.3   1/6=16.7   0         4/6=66.7    3/6=50.0   5/6=83.3
late_share           .20        .10        None      .25         .15        .12
  grade (5)          60         0          None      80          40         20
cancel_rate          .02        .01        None      .03         .01        .02
  grade (5)          (2+.5)/5=50 (0+.5)/5=10 None    4/5=80      10         50
long_haul_share      0          0          0         0           0          .5
  grade (6)          five tie at 0: (0+.5*4)/6=33.3 each;              ANC 5/6=83.3
international_share  0          0          0         1/3         0          0
  grade (6)          zeros (0+.5*4)/6=33.3 each;                        LAX 5/6=83.3
cargo_share          0          0          0         0           0          50/90
  grade (6)          zeros 33.3 each;                                   ANC 83.3
top_airline_share    .5         1.0        1.0       2/3         1.0        .5
  grade (6)          (0+.5*1)/6=8.3  (3+.5*2)/6=66.7  66.7  2/6=33.3  66.7   8.3
missing_seats_pct    80/4000    129.41/2000 0        0           0          65.88/4000
  (85% target)       =.02       =.0647      0        0           0          =.01647
  grade (6)          4/6=66.7   5/6=83.3   zeros (0+.5*2)/6=16.7 each   3/6=50.0
  (at 80% it would be BOS .0525, MHT .125, LAX .025, SNA .05, ANC .08, BTV 0:
   order MHT, ANC, BOS, SNA, LAX, BTV - different from 85%.)

Scores (test_step07_scoring.py worked them out, default weights):
  final:  MHT 52.5, LAX 50.0, ANC 49.5, BOS 46.7, SNA 32.2, BTV 8.9 -> ranks 1..6
  demand: MHT 83.3, BOS 58.35, ANC 41.65, LAX 33.35, BTV 16.7, SNA 16.65
  strain: LAX 61.1, ANC 54.7, SNA 42.5, BOS 38.9, MHT 31.9, BTV 0.0
  flags:  MHT, ANC "planes over 85% full"; BTV "scored without delay data".
  missing: BTV [nas_delay_per_flight, taxi_out_min]; others [].
"""

import re
from pathlib import Path

import pytest

import app.tools  # noqa: F401  (must register rank_airports and airport_profile)
from app.measures import compute_measures
from app.tools.base import TOOLS, run_tool, tool_specs_for_ai

RANK = "rank_airports"
PROFILE = "airport_profile"

ROUND = 0.051  # tolerance for numbers rounded to 1 decimal
HALF = 0.051  # exact x.x5 halfway values: accepts either 1-decimal rounding

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "implementation-plan.md"
TOOLS_DOC = ROOT / "docs" / "tools.md"

ABOUT_KEYS = {"data_period", "filters", "missing", "assumptions"}
WEIGHT_KEYS = ["D1", "D2", "S1", "S2", "S3", "S4"]
SCORED = [
    "growth_long",
    "growth_short",
    "load_factor",
    "nas_delay_per_flight",
    "taxi_out_min",
    "departures_per_runway",
]
CONGESTION = ["departures_per_runway", "nas_delay_per_flight", "taxi_out_min", "late_share", "cancel_rate"]
NEW_ENGLAND = {"CT", "ME", "MA", "NH", "RI", "VT"}

BASE_KEYS = {"iata", "name", "city", "state", "size"}
ROW_KEYS = BASE_KEYS | {"national_rank", "value", "grade"}
SCORE_ROW_KEYS = ROW_KEYS | {"demand_score", "strain_score", "grades", "flags", "missing"}
PROFILE_KEYS = BASE_KEYS | {
    "measures",
    "final_score",
    "demand_score",
    "strain_score",
    "national_rank",
    "flags",
    "missing",
    "congestion",
}

# Hand-worked grades (see the table above), measure -> airport -> grade.
GRADES = {
    "enplanements": {"BOS": 66.7, "MHT": 16.7, "BTV": 0.0, "LAX": 83.3, "SNA": 50.0, "ANC": 33.3},
    "passengers": {"BOS": 50.0, "MHT": 33.3, "BTV": 0.0, "LAX": 83.3, "SNA": 16.7, "ANC": 66.7},
    "departures": {"BOS": 58.3, "MHT": 33.3, "BTV": 0.0, "LAX": 83.3, "SNA": 16.7, "ANC": 58.3},
    "seats": {"BOS": 58.3, "MHT": 33.3, "BTV": 0.0, "LAX": 83.3, "SNA": 16.7, "ANC": 58.3},
    "growth_short": {"BOS": 50.0, "MHT": 83.3, "BTV": 16.7, "LAX": 66.7, "SNA": 0.0, "ANC": 33.3},
    "growth_long": {"BOS": 66.7, "MHT": 83.3, "BTV": 16.7, "LAX": 0.0, "SNA": 33.3, "ANC": 50.0},
    "load_factor": {"BOS": 16.7, "MHT": 83.3, "BTV": 0.0, "LAX": 33.3, "SNA": 50.0, "ANC": 66.7},
    "nas_delay_per_flight": {"BOS": 60.0, "MHT": 0.0, "BTV": None, "LAX": 80.0, "SNA": 40.0, "ANC": 20.0},
    "taxi_out_min": {"BOS": 60.0, "MHT": 0.0, "BTV": None, "LAX": 80.0, "SNA": 20.0, "ANC": 40.0},
    "departures_per_runway": {"BOS": 33.3, "MHT": 16.7, "BTV": 0.0, "LAX": 66.7, "SNA": 50.0, "ANC": 83.3},
    "late_share": {"BOS": 60.0, "MHT": 0.0, "BTV": None, "LAX": 80.0, "SNA": 40.0, "ANC": 20.0},
    "cancel_rate": {"BOS": 50.0, "MHT": 10.0, "BTV": None, "LAX": 80.0, "SNA": 10.0, "ANC": 50.0},
    "long_haul_share": {"BOS": 33.3, "MHT": 33.3, "BTV": 33.3, "LAX": 33.3, "SNA": 33.3, "ANC": 83.3},
    "international_share": {"BOS": 33.3, "MHT": 33.3, "BTV": 33.3, "LAX": 83.3, "SNA": 33.3, "ANC": 33.3},
    "cargo_share": {"BOS": 33.3, "MHT": 33.3, "BTV": 33.3, "LAX": 33.3, "SNA": 33.3, "ANC": 83.3},
    "top_airline_share": {"BOS": 8.3, "MHT": 66.7, "BTV": 66.7, "LAX": 33.3, "SNA": 66.7, "ANC": 8.3},
    "missing_seats_pct": {"BOS": 66.7, "MHT": 83.3, "BTV": 16.7, "LAX": 16.7, "SNA": 16.7, "ANC": 50.0},
}

# Hand-worked values for BOS (TINY_DATA.md "Hand-worked numbers").
BOS_VALUES = {
    "enplanements": 21_000_000,
    "passengers": 3168,  # 700+884 + 700+884
    "departures": 40,  # 2 routes x 10 x 2 months
    "seats": 4000,
    "growth_short": 0.05,  # 1M / 20M
    "growth_long": 0.10,  # 288 / 2,880
    "load_factor": 0.792,  # 3,168 / 4,000
    "nas_delay_per_flight": 8,  # 1,600 / 200
    "taxi_out_min": 20,
    "departures_per_runway": 10,  # 40 / 4
    "late_share": 0.20,  # 40 / 200
    "cancel_rate": 0.02,  # 4 / 200
    "long_haul_share": 0.0,
    "international_share": 0.0,
    "cargo_share": 0.0,
    "top_airline_share": 0.5,  # B6 and DL tie, 20 of 40
    "missing_seats_pct": 0.02,  # 80 / 4,000 at 85%
}

FINAL = {"MHT": 52.5, "LAX": 50.0, "ANC": 49.5, "BOS": 46.7, "SNA": 32.2, "BTV": 8.9}
DEMAND = {"MHT": 83.3, "BOS": 58.35, "ANC": 41.65, "LAX": 33.35, "BTV": 16.7, "SNA": 16.65}
STRAIN = {"LAX": 61.1, "ANC": 54.7, "SNA": 42.5, "BOS": 38.9, "MHT": 31.9, "BTV": 0.0}
FULL = "planes over 85% full"
NO_DELAYS = "scored without delay data"


# ---- helpers -------------------------------------------------------------------


def _ok(result):
    """The result of a tool that ran; fails with the error dict otherwise."""
    assert isinstance(result, dict), result
    assert "error" not in result, result
    assert set(result) == {"data", "about"}, result
    assert set(result["about"]) == ABOUT_KEYS, result["about"]
    return result


def _rank(con, **settings):
    return _ok(run_tool(con, RANK, settings))


def _profile(con, airports):
    return _ok(run_tool(con, PROFILE, {"airports": airports}))


def _rows(result):
    return result["data"]["airports"]


def _codes(result):
    return [row["iata"] for row in _rows(result)]


def _by_code(result):
    return {row["iata"]: row for row in _rows(result)}


def _assert_error(result, allowed):
    assert isinstance(result, dict) and set(result) == {"error", "allowed"}, result
    assert isinstance(result["error"], str) and result["error"]
    assert result["allowed"] == allowed, result


def _approx(expected, tol=ROUND):
    return None if expected is None else pytest.approx(expected, abs=tol)


def _norm(text):
    """Drop markdown marks (` and *) and squeeze spaces, so doc and result compare."""
    return " ".join(text.replace("`", "").replace("*", "").split())


def _about_text(result, key):
    return _norm(" ".join(result["about"][key]))


def _plan_quotes(decision):
    """Every "quoted" text in one row of the decision table (e.g. "P35")."""
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {decision} |"):
            return re.findall(r'"([^"]+)"', line)
    raise AssertionError(f"{decision} not found in {PLAN}")


def _plan_text(decision, words, start=False):
    """The one quoted text in a decision row that contains (or, with start, begins with) `words`."""
    found = [q for q in _plan_quotes(decision) if (q.startswith(words) if start else words in q)]
    assert len(found) == 1, (decision, words, found)
    return found[0]


def _limit(keyword):
    """One bullet of tools.md "Known limits", found by its keyword."""
    text = TOOLS_DOC.read_text(encoding="utf-8")
    section = text.split("**Known limits", 1)[1].split("\n## ", 1)[0]
    bullets = [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]
    found = [b for b in bullets if keyword in b]
    assert len(found) == 1, (keyword, bullets)
    return _norm(found[0])


def _with_n(template, n=100_000):
    return template.replace("N+", f"{n:,}+")


def DATA_PERIOD():
    return _plan_text("P35", "growth from 2019")


def SIZE_FILTER(n=100_000):
    return _norm(_with_n(_plan_text("P35", "airports with N+", start=True), n))


def NATIONAL(n=100_000):
    return _norm(_with_n(_plan_text("P35", "Grades are national"), n))


def LONG_HAUL():
    return _norm(_plan_text("P35", "Long-haul"))


def TARGET_85():
    return _norm(_plan_text("P35", "85% target"))


def DELAY_LIMIT():
    return _limit("Delay measures")


def TAXI_LIMIT():
    return _limit("taxi_out_min` is")


def AIRLINE_LIMIT():
    return _limit("top_airline_share` uses")


# ---- the listed tests ------------------------------------------------------------


# 1
def test_rank_default_by_score(tiny_db):
    result = _rank(tiny_db)
    data = result["data"]
    assert data["sort_by"] == "score"
    assert data["order"] == "highest_first"

    # final scores (Step 7): MHT 52.5 > LAX 50.0 > ANC 49.5 > BOS 46.7 > SNA 32.2 > BTV 8.9;
    # BHB (55,000 boardings) is under the size filter and not listed.
    assert _codes(result) == ["MHT", "LAX", "ANC", "BOS", "SNA", "BTV"]
    rows = _by_code(result)
    for rank, code in enumerate(["MHT", "LAX", "ANC", "BOS", "SNA", "BTV"], start=1):
        row = rows[code]
        assert set(row) == SCORE_ROW_KEYS, row
        assert row["national_rank"] == rank
        assert row["value"] == _approx(FINAL[code])
        assert row["grade"] is None  # the score has no grade (P29)
        assert row["demand_score"] == _approx(DEMAND[code], HALF)
        assert row["strain_score"] == _approx(STRAIN[code])

    mht = rows["MHT"]
    assert mht["name"] == "Manchester-Boston Regional Airport"
    assert mht["city"] == "Manchester"
    assert mht["state"] == "NH"
    assert mht["size"] == "small"  # hub type S in 2025 (P26)
    # MHT grades: D1 83.3, D2 83.3, S1 83.3, S2 0, S3 0, S4 16.7
    assert set(mht["grades"]) == set(SCORED)
    for name in SCORED:
        assert mht["grades"][name] == _approx(GRADES[name]["MHT"])
    assert mht["flags"] == [FULL]  # load factor 0.90 > 0.85
    assert mht["missing"] == []

    assert rows["ANC"]["flags"] == [FULL]  # 0.864 > 0.85
    assert rows["BOS"]["flags"] == []
    # BTV has no delay rows: S2, S3 have no grade (P16)
    btv = rows["BTV"]
    assert set(btv["grades"]) == set(SCORED) - {"nas_delay_per_flight", "taxi_out_min"}
    assert btv["missing"] == ["nas_delay_per_flight", "taxi_out_min"]
    assert btv["flags"] == [NO_DELAYS]

    # about (P35): the period, the size filter, national grades, the default weights
    about = result["about"]
    assert about["data_period"] == DATA_PERIOD()
    assert _norm(about["filters"][0]) == SIZE_FILTER()
    assumptions = _about_text(result, "assumptions")
    assert NATIONAL() in assumptions
    weights = [a for a in result["about"]["assumptions"] if a.startswith("Weights:")]
    assert len(weights) == 1, result["about"]["assumptions"]
    for token in ["D1 20", "D2 20", "S1 20", "S2 15", "S3 10", "S4 15"]:
        assert token in weights[0]


# 2
def test_rank_region_keeps_national_grades(tiny_db):
    national = _by_code(_rank(tiny_db))
    region = _rank(tiny_db, region="New England")

    # New England airports in the national pool: MHT (rank 1), BOS (4), BTV (6).
    # BHB (ME) is under the size filter, so it is not listed.
    assert _codes(region) == ["MHT", "BOS", "BTV"]
    rows = _by_code(region)
    for code in ["MHT", "BOS", "BTV"]:
        assert rows[code]["grades"] == national[code]["grades"]
        assert rows[code]["value"] == national[code]["value"]
        assert rows[code]["national_rank"] == national[code]["national_rank"]

    # BOS keeps its national grades (pool of 6 / 5, not the 3 New England airports)
    bos = rows["BOS"]
    assert bos["national_rank"] == 4
    assert bos["value"] == _approx(46.7)
    for name in SCORED:
        assert bos["grades"][name] == _approx(GRADES[name]["BOS"])
    # e.g. S4: BOS 10 vs national pool {MHT 8, BTV 5, LAX 15, SNA 12, ANC 30}: 2 lower -> 2/6 = 33.3
    # (inside New England only it would be 2/3 = 66.7)
    assert bos["grades"]["departures_per_runway"] == _approx(33.3)

    # the same with another measure: BOS S4 grade 33.3, national rank 4 of 6
    # (S4 order: ANC 30, LAX 15, SNA 12, BOS 10, MHT 8, BTV 5)
    s4 = _by_code(_rank(tiny_db, region="New England", sort_by="departures_per_runway"))
    assert list(s4) == ["BOS", "MHT", "BTV"]
    assert s4["BOS"]["grade"] == _approx(33.3)
    assert s4["BOS"]["national_rank"] == 4
    assert s4["MHT"]["national_rank"] == 5
    assert s4["BTV"]["national_rank"] == 6

    assert any("New England" in f for f in region["about"]["filters"])


# 3
def test_rank_by_any_measure(tiny_db):
    result = _rank(tiny_db, sort_by="departures_per_runway")
    assert result["data"]["sort_by"] == "departures_per_runway"
    assert result["data"]["order"] == "highest_first"
    # S4: ANC 30, LAX 15, SNA 12, BOS 10, MHT 8, BTV 5
    assert _codes(result) == ["ANC", "LAX", "SNA", "BOS", "MHT", "BTV"]
    values = {"ANC": 30, "LAX": 15, "SNA": 12, "BOS": 10, "MHT": 8, "BTV": 5}
    for rank, row in enumerate(_rows(result), start=1):
        assert set(row) == ROW_KEYS, row  # no score fields when sort_by is not "score"
        assert row["national_rank"] == rank
        assert row["value"] == _approx(values[row["iata"]])
        assert row["grade"] == _approx(GRADES["departures_per_runway"][row["iata"]])

    # a measure with a tie: top_airline_share MHT, BTV, SNA 1.0 (tie, by code), LAX 0.667, ANC, BOS 0.5 (tie)
    tops = _rank(tiny_db, sort_by="top_airline_share")
    assert _codes(tops) == ["BTV", "MHT", "SNA", "LAX", "ANC", "BOS"]
    rows = _by_code(tops)
    assert rows["BTV"]["grade"] == _approx(66.7)  # (3 lower + 1/2 x 2 others) / 6 = 66.7
    assert rows["BOS"]["grade"] == _approx(8.3)  # (0 + 1/2 x 1) / 6 = 8.3
    assert rows["LAX"]["value"] == _approx(40 / 60, 0.001)

    # strain_score: LAX 61.1, ANC 54.7, SNA 42.5, BOS 38.9, MHT 31.9, BTV 0.0; no grade
    strain = _rank(tiny_db, sort_by="strain_score")
    assert _codes(strain) == ["LAX", "ANC", "SNA", "BOS", "MHT", "BTV"]
    for row in _rows(strain):
        assert row["value"] == _approx(STRAIN[row["iata"]])
        assert row["grade"] is None

    # demand_score: MHT 83.3, BOS 58.35, ANC 41.65, LAX 33.35, BTV 16.7, SNA 16.65
    # (SNA may round up to 16.7 = BTV; a tie goes by code, so BTV first either way)
    demand = _rank(tiny_db, sort_by="demand_score")
    assert _codes(demand) == ["MHT", "BOS", "ANC", "LAX", "BTV", "SNA"]
    for row in _rows(demand):
        assert row["value"] == _approx(DEMAND[row["iata"]], HALF)
        assert row["grade"] is None

    # every measure of the shared list can be the sort (no error, sort_by echoed)
    for name in compute_measures(tiny_db)["BOS"]:
        assert _rank(tiny_db, sort_by=name)["data"]["sort_by"] == name

    # an unknown measure is a settings error, not a crash
    bad = run_tool(tiny_db, RANK, {"sort_by": "profit"})
    assert isinstance(bad, dict) and "error" in bad and "profit" not in bad["allowed"]
    assert "load_factor" in bad["allowed"] and "score" in bad["allowed"]


def test_rank_ascending(tiny_db):
    result = _rank(tiny_db, sort_by="departures_per_runway", order="lowest_first")
    assert result["data"]["order"] == "lowest_first"
    # S4 low -> high: BTV 5, MHT 8, BOS 10, SNA 12, LAX 15, ANC 30
    assert _codes(result) == ["BTV", "MHT", "BOS", "SNA", "LAX", "ANC"]
    # grades do not depend on the order: higher value -> higher grade (P29)
    rows = _by_code(result)
    assert rows["BTV"]["grade"] == _approx(0.0)
    assert rows["ANC"]["grade"] == _approx(83.3)
    # national_rank is always counted from the HIGHEST value (P33), whatever the order:
    # high -> low ANC 1, LAX 2, SNA 3, BOS 4, MHT 5, BTV 6; listed low -> high = the same ranks backwards
    assert [r["national_rank"] for r in _rows(result)] == [6, 5, 4, 3, 2, 1]

    # ties go by code A->Z in both orders: cancel_rate low -> high
    # MHT .01 = SNA .01, ANC .02 = BOS .02, LAX .03; BTV has no value
    cancel = _rank(tiny_db, sort_by="cancel_rate", order="lowest_first")
    assert _codes(cancel) == ["MHT", "SNA", "ANC", "BOS", "LAX"]
    # national_rank from the highest, ties by code A->Z: LAX .03 = 1, ANC .02 = 2, BOS .02 = 3,
    # MHT .01 = 4, SNA .01 = 5 (checked per airport, so the tie listing order doesn't matter here)
    assert {r["iata"]: r["national_rank"] for r in _rows(cancel)} == {"LAX": 1, "ANC": 2, "BOS": 3, "MHT": 4, "SNA": 5}

    # score, low -> high: BTV 8.9, SNA 32.2, BOS 46.7, ANC 49.5, LAX 50.0, MHT 52.5
    score = _rank(tiny_db, order="lowest_first")
    assert _codes(score) == ["BTV", "SNA", "BOS", "ANC", "LAX", "MHT"]
    # national_rank = ScoredAirport.rank (best first): MHT 1, LAX 2, ANC 3, BOS 4, SNA 5, BTV 6
    assert [r["national_rank"] for r in _rows(score)] == [6, 5, 4, 3, 2, 1]

    # an airport whose final_score is None is last in BOTH orders (P22, P32):
    # weights {"S2": 100} -> final = NAS grade: LAX 80, BOS 60, SNA 40, ANC 20, MHT 0, BTV None
    high = _rank(tiny_db, weights={"S2": 100})
    assert _codes(high) == ["LAX", "BOS", "SNA", "ANC", "MHT", "BTV"]
    assert _by_code(high)["BTV"]["value"] is None
    low = _rank(tiny_db, weights={"S2": 100}, order="lowest_first")
    assert _codes(low) == ["MHT", "ANC", "SNA", "BOS", "LAX", "BTV"]
    # ranks from the highest, None last: LAX 1, BOS 2, SNA 3, ANC 4, MHT 5, BTV 6
    assert [r["national_rank"] for r in _rows(high)] == [1, 2, 3, 4, 5, 6]
    assert [r["national_rank"] for r in _rows(low)] == [5, 4, 3, 2, 1, 6]

    bad = run_tool(tiny_db, RANK, {"order": "up"})
    assert isinstance(bad, dict) and "error" in bad
    assert sorted(bad["allowed"]) == ["highest_first", "lowest_first"]


# 4
def test_rank_top_n(tiny_db):
    result = _rank(tiny_db, top_n=2)
    assert _codes(result) == ["MHT", "LAX"]  # the 2 best scores
    assert [r["national_rank"] for r in _rows(result)] == [1, 2]
    # 6 airports pass the size filter; 2 are shown
    template = _plan_text("P32", "matched; only the first")
    expected = _norm(template.replace("N airports", "6 airports").replace("`top_n`", "2"))
    assert expected in _about_text(result, "missing")

    # default top_n is 10: all 6 shown, no "only the first" note
    full = _rank(tiny_db)
    assert len(_rows(full)) == 6
    assert "only the first" not in _about_text(full, "missing")

    # exactly 6 with top_n 6: nothing left out, no note
    assert "only the first" not in _about_text(_rank(tiny_db, top_n=6), "missing")

    _assert_error(run_tool(tiny_db, RANK, {"top_n": 26}), [1, 25])
    _assert_error(run_tool(tiny_db, RANK, {"top_n": 0}), [1, 25])


# 5
def test_rank_custom_weights(tiny_db):
    # weights {"D1": 50, "D2": 50}: final = (D1 grade + D2 grade) / 2
    #   MHT (83.3+83.3)/2 = 83.3; BOS (66.7+50)/2 = 58.35; ANC (50+33.3)/2 = 41.65;
    #   LAX (0+66.7)/2 = 33.35; BTV (16.7+16.7)/2 = 16.7; SNA (33.3+0)/2 = 16.65
    # (SNA may round to 16.7 = BTV; the tie goes by code: BTV first either way)
    result = _rank(tiny_db, weights={"D1": 50, "D2": 50})
    assert result["data"]["sort_by"] == "score"
    assert _codes(result) == ["MHT", "BOS", "ANC", "LAX", "BTV", "SNA"]
    rows = _by_code(result)
    for rank, code in enumerate(["MHT", "BOS", "ANC", "LAX", "BTV", "SNA"], start=1):
        assert rows[code]["value"] == _approx(DEMAND[code], HALF)
        assert rows[code]["national_rank"] == rank  # ScoredAirport.rank under these weights
        # demand half: D1, D2 weights 50/50 -> same as the default 20/20 (P18)
        assert rows[code]["demand_score"] == _approx(DEMAND[code], HALF)
        # strain half: S1..S4 weights total 0 -> None (P18)
        assert rows[code]["strain_score"] is None
    # BOS moves from national rank 4 (default) to 2
    assert rows["BOS"]["national_rank"] == 2

    # the weights in force are stated
    weights = [a for a in result["about"]["assumptions"] if a.startswith("Weights:")]
    assert len(weights) == 1, result["about"]["assumptions"]
    assert "D1 50" in weights[0] and "D2 50" in weights[0]

    # keys left out count as 0: {"S4": 100} -> final = S4 grade: ANC 83.3, LAX 66.7, SNA 50, BOS 33.3, MHT 16.7, BTV 0
    s4 = _rank(tiny_db, weights={"S4": 100})
    assert _codes(s4) == ["ANC", "LAX", "SNA", "BOS", "MHT", "BTV"]
    assert _by_code(s4)["ANC"]["value"] == _approx(83.3)


def test_rank_bad_weights_are_settings_errors(tiny_db):
    # P30: checked in the settings model -> an error the AI sees, never a crash
    for weights in (
        {"D1": 50},  # total 50, not 100
        {"D1": 60, "D2": 60},  # total 120
        {"D9": 100},  # unknown key
        {"D1": -10, "D2": 110},  # negative value
    ):
        _assert_error(run_tool(tiny_db, RANK, {"weights": weights}), WEIGHT_KEYS)


# 6
def test_weights_only_with_score(tiny_db):
    weights = {"D1": 50, "D2": 50}
    for sort_by in ("load_factor", "demand_score", "strain_score", "missing_seats_pct"):
        _assert_error(run_tool(tiny_db, RANK, {"sort_by": sort_by, "weights": weights}), ["score"])
    # with sort_by "score" (given or by default) the weights are fine
    assert _codes(_rank(tiny_db, sort_by="score", weights=weights))[0] == "MHT"
    assert _codes(_rank(tiny_db, weights=weights))[0] == "MHT"


# 7
def test_rank_by_missing_seats_uses_85(tiny_db):
    result = _rank(tiny_db, sort_by="missing_seats_pct")
    # at 85%: MHT 129.41/2000 = .0647, BOS 80/4000 = .02, ANC 65.88/4000 = .01647,
    #         BTV, LAX, SNA 0 (tie, by code)
    # (at 80% the order would be MHT .125, ANC .08, BOS .0525, SNA .05, LAX .025, BTV 0)
    assert _codes(result) == ["MHT", "BOS", "ANC", "BTV", "LAX", "SNA"]
    rows = _by_code(result)
    assert rows["MHT"]["value"] == pytest.approx(129.4118 / 2000, abs=1e-5)  # (960/0.85 - 1000) / 2000
    assert rows["BOS"]["value"] == pytest.approx(0.02, abs=1e-6)  # (1768/0.85 - 2000) / 4000; 0.0525 at 80%
    assert rows["ANC"]["value"] == pytest.approx(2 * (1728 / 0.85 - 2000) / 4000, abs=1e-6)
    assert rows["LAX"]["value"] == pytest.approx(0.0, abs=1e-9)  # 2460/0.85 = 2894.1 < 3000; 0.025 at 80%
    assert rows["SNA"]["value"] == pytest.approx(0.0, abs=1e-9)  # 504/0.85 = 592.9 < 600; 0.05 at 80%
    for code, row in rows.items():
        assert row["grade"] == _approx(GRADES["missing_seats_pct"][code])
    # MHT 5/6 = 83.3, BOS 4/6 = 66.7, ANC 3/6 = 50, zeros (0 + 1/2 x 2) / 6 = 16.7
    assert [r["national_rank"] for r in _rows(result)] == [1, 2, 3, 4, 5, 6]

    assert TARGET_85() in _about_text(result, "assumptions")


# 8
def test_rank_about_lists_filters_and_missing(tiny_db):
    # late_share, New England: BOS .20, MHT .10; BTV has no delay data -> not listed
    result = _rank(tiny_db, region="New England", sort_by="late_share")
    assert _codes(result) == ["BOS", "MHT"]
    rows = _by_code(result)
    assert rows["BOS"]["grade"] == _approx(60.0)  # pool of 5: 3 lower (MHT .10, ANC .12, SNA .15) -> 3/5
    assert rows["BOS"]["national_rank"] == 2  # national late_share order: LAX, BOS, SNA, ANC, MHT
    assert rows["MHT"]["national_rank"] == 5

    about = result["about"]
    assert about["data_period"] == DATA_PERIOD()
    filters = [_norm(f) for f in about["filters"]]
    assert filters[0] == SIZE_FILTER()
    assert any("New England" in f for f in filters[1:])

    template = _plan_text("P32", "have no value for")
    expected = _norm(template.replace("N airport(s)", "1 airport(s)").replace("for X", "for late_share"))
    assert expected in _about_text(result, "missing")  # BTV

    assumptions = _about_text(result, "assumptions")
    assert NATIONAL() in assumptions
    assert DELAY_LIMIT() in assumptions  # late_share is a delay measure
    assert TAXI_LIMIT() not in assumptions  # taxi_out_min is not shown
    assert LONG_HAUL() not in assumptions
    assert TARGET_85() not in assumptions
    assert AIRLINE_LIMIT() not in assumptions
    assert not any(a.startswith("Weights:") for a in about["assumptions"])  # only with score

    # score: the six scored measures are shown -> delay and taxi-out limits, and the weights
    score = _about_text(_rank(tiny_db), "assumptions")
    assert DELAY_LIMIT() in score and TAXI_LIMIT() in score
    assert LONG_HAUL() not in score and AIRLINE_LIMIT() not in score

    # each measure brings its own note
    assert LONG_HAUL() in _about_text(_rank(tiny_db, sort_by="long_haul_share"), "assumptions")
    assert AIRLINE_LIMIT() in _about_text(_rank(tiny_db, sort_by="top_airline_share"), "assumptions")
    taxi = _about_text(_rank(tiny_db, sort_by="taxi_out_min"), "assumptions")
    assert TAXI_LIMIT() in taxi and DELAY_LIMIT() in taxi

    # states + size filters are listed; all must match (P27)
    # small (hub S): MHT, BTV; states MA, NH -> MHT only
    both = _rank(tiny_db, states=["MA", "NH"], size="small")
    assert _codes(both) == ["MHT"]
    both_filters = " ".join(both["about"]["filters"])
    assert "MA" in both_filters and "NH" in both_filters and "small" in both_filters

    # nothing left -> empty list and the P32 message
    empty = _rank(tiny_db, states=["TX"])
    assert _rows(empty) == []
    assert _norm(_plan_text("P32", "No airport matches")) in _about_text(empty, "missing")


def test_rank_min_enplanements_changes_the_pool(tiny_db):
    # min 1,000,000: BTV (618,000) leaves the pool -> 5 airports graded
    # S4 pool {MHT 8, BOS 10, SNA 12, LAX 15, ANC 30}: BOS 1/5 = 20, ANC 4/5 = 80
    result = _rank(tiny_db, sort_by="departures_per_runway", min_enplanements=1_000_000)
    assert _codes(result) == ["ANC", "LAX", "SNA", "BOS", "MHT"]
    rows = _by_code(result)
    assert rows["BOS"]["grade"] == _approx(20.0)
    assert rows["ANC"]["grade"] == _approx(80.0)
    assert rows["MHT"]["grade"] == _approx(0.0)
    about = result["about"]
    assert _norm(about["filters"][0]) == SIZE_FILTER(1_000_000)
    assert NATIONAL(1_000_000) in _about_text(result, "assumptions")

    _assert_error(run_tool(tiny_db, RANK, {"min_enplanements": -1}), [0, 10_000_000])
    _assert_error(run_tool(tiny_db, RANK, {"min_enplanements": 10_000_001}), [0, 10_000_000])


# 9
def test_profile_one_to_five_airports(tiny_db):
    two = _profile(tiny_db, ["LAX", "SNA"])
    assert [e["iata"] for e in two["data"]["airports"]] == ["LAX", "SNA"]
    # in the order asked
    assert [e["iata"] for e in _profile(tiny_db, ["SNA", "LAX"])["data"]["airports"]] == ["SNA", "LAX"]
    # one airport
    assert [e["iata"] for e in _profile(tiny_db, ["BOS"])["data"]["airports"]] == ["BOS"]
    # five airports
    five = ["ANC", "BOS", "MHT", "LAX", "SNA"]
    assert [e["iata"] for e in _profile(tiny_db, five)["data"]["airports"]] == five
    # a repeated airport is shown once ("Boston" resolves to BOS, P25 rule 3)
    assert [e["iata"] for e in _profile(tiny_db, ["BOS", "bos", "Boston"])["data"]["airports"]] == ["BOS"]

    # 0 or 6 airports -> settings error with the limits
    _assert_error(run_tool(tiny_db, PROFILE, {"airports": []}), [1, 5])
    _assert_error(run_tool(tiny_db, PROFILE, {"airports": five + ["BTV"]}), [1, 5])

    entry = two["data"]["airports"][1]
    assert set(entry) == PROFILE_KEYS, entry
    assert entry["name"] == "John Wayne Airport-Orange County Airport"
    assert entry["city"] == "Santa Ana"
    assert entry["state"] == "CA"
    assert entry["size"] == "medium"  # hub type M


def test_profile_accepts_a_name(tiny_db):
    # "Santa Ana" is a city (P25 rule 3) -> SNA, turned into a code before the tool runs (P28)
    result = _profile(tiny_db, ["Santa Ana"])
    assert [e["iata"] for e in result["data"]["airports"]] == ["SNA"]
    # unknown name -> not-found error, the tool does not run
    _assert_error(run_tool(tiny_db, PROFILE, {"airports": ["Atlantis"]}), [])


# 10
def test_profile_has_every_measure_with_grade(tiny_db):
    result = _profile(tiny_db, ["BOS", "BTV"])
    bos, btv = result["data"]["airports"]
    measure_names = set(compute_measures(tiny_db)["BOS"])
    assert set(bos["measures"]) == measure_names
    assert set(btv["measures"]) == measure_names

    for name in measure_names:
        cell = bos["measures"][name]
        assert set(cell) == {"value", "grade"}
        assert cell["value"] == pytest.approx(BOS_VALUES[name], abs=1e-6), name
        assert cell["grade"] == _approx(GRADES[name]["BOS"]), name
        # BTV: delay measures have no value and no grade
        assert btv["measures"][name]["grade"] == _approx(GRADES[name]["BTV"]), name
    for name in ("nas_delay_per_flight", "taxi_out_min", "late_share", "cancel_rate"):
        assert btv["measures"][name]["value"] is None

    # the score part comes from ScoredAirport (default weights)
    assert bos["final_score"] == _approx(46.7)
    assert bos["demand_score"] == _approx(58.35, HALF)
    assert bos["strain_score"] == _approx(38.9)
    assert bos["national_rank"] == 4
    assert bos["flags"] == []
    assert bos["missing"] == []
    assert btv["final_score"] == _approx(8.9)
    assert btv["national_rank"] == 6
    assert btv["flags"] == [NO_DELAYS]
    assert btv["missing"] == ["nas_delay_per_flight", "taxi_out_min"]

    # about (P35): every measure is shown, so every note is there
    about = result["about"]
    assert about["data_period"] == DATA_PERIOD()
    assert _norm(about["filters"][0]) == SIZE_FILTER()
    assumptions = _about_text(result, "assumptions")
    for note in (NATIONAL(), LONG_HAUL(), TARGET_85(), DELAY_LIMIT(), TAXI_LIMIT(), AIRLINE_LIMIT()):
        assert note in assumptions


# 11
def test_profile_congestion_measures_and_strain_score(tiny_db):
    lax, sna = _profile(tiny_db, ["LAX", "SNA"])["data"]["airports"]
    expected = {
        # LAX: S4 60/4 = 15 (4/6 = 66.7), NAS 10 (4/5 = 80), taxi 22 (80), late .25 (80), cancel .03 (80)
        "LAX": {
            "departures_per_runway": (15, 66.7),
            "nas_delay_per_flight": (10, 80.0),
            "taxi_out_min": (22, 80.0),
            "late_share": (0.25, 80.0),
            "cancel_rate": (0.03, 80.0),
        },
        # SNA: S4 12/1 = 12 (3/6 = 50), NAS 3 (2/5 = 40), taxi 14 (1/5 = 20), late .15 (40),
        #      cancel .01 (tie with MHT: (0 + 1/2) / 5 = 10)
        "SNA": {
            "departures_per_runway": (12, 50.0),
            "nas_delay_per_flight": (3, 40.0),
            "taxi_out_min": (14, 20.0),
            "late_share": (0.15, 40.0),
            "cancel_rate": (0.01, 10.0),
        },
    }
    for entry in (lax, sna):
        congestion = entry["congestion"]
        assert set(congestion) == {"measures", "strain_score"}
        assert list(congestion["measures"]) == CONGESTION
        for name, (value, grade) in expected[entry["iata"]].items():
            cell = congestion["measures"][name]
            assert set(cell) == {"value", "grade"}
            assert cell["value"] == pytest.approx(value, abs=1e-6), name
            assert cell["grade"] == _approx(grade), name
            assert cell == entry["measures"][name]  # same numbers as the full measure list
        # the summary is the strain half of the score (decisions 7.18)
        assert congestion["strain_score"] == entry["strain_score"]
    # strain: LAX (20*33.3 + 15*80 + 10*80 + 15*66.7)/60 = 61.1; SNA (20*50 + 15*40 + 10*20 + 15*50)/60 = 42.5
    assert lax["congestion"]["strain_score"] == _approx(61.1)
    assert sna["congestion"]["strain_score"] == _approx(42.5)


# 12
def test_profile_small_airport_has_measures_but_no_score(tiny_db):
    result = _profile(tiny_db, ["BHB", "BOS"])
    bhb, bos = result["data"]["airports"]
    assert set(bhb) == PROFILE_KEYS
    assert bhb["size"] == "non-hub"  # hub type N
    # BHB keeps its values (TINY_DATA.md): 55,000 boardings, load 108/180 = .6, S4 20/2 = 10,
    # NAS 0/20 = 0, taxi 10, D1 18/90 = .2, D2 5,000/50,000 = .1, late 2/20 = .1, cancel 0
    values = {
        "enplanements": 55_000,
        "load_factor": 0.6,
        "departures_per_runway": 10,
        "nas_delay_per_flight": 0,
        "taxi_out_min": 10,
        "growth_long": 0.2,
        "growth_short": 0.1,
        "late_share": 0.1,
        "cancel_rate": 0.0,
    }
    for name, value in values.items():
        assert bhb["measures"][name]["value"] == pytest.approx(value, abs=1e-6), name
    # ... but under the size filter: no grade, no score, no rank
    for name, cell in bhb["measures"].items():
        assert cell["grade"] is None, name
    assert bhb["final_score"] is None
    assert bhb["demand_score"] is None
    assert bhb["strain_score"] is None
    assert bhb["national_rank"] is None
    assert bhb["flags"] == []
    assert bhb["missing"] == []
    assert bhb["congestion"]["strain_score"] is None
    for name in CONGESTION:
        assert bhb["congestion"]["measures"][name]["grade"] is None
    assert bhb["congestion"]["measures"]["departures_per_runway"]["value"] == pytest.approx(10)

    # BOS beside it is still graded nationally (BHB is not in the pool)
    assert bos["measures"]["departures_per_runway"]["grade"] == _approx(33.3)
    assert bos["national_rank"] == 4

    template = _plan_text("P34", "fewer than")
    assert _norm(template) in _about_text(result, "missing")
    # BOS alone: no such note
    assert "fewer than" not in _about_text(_profile(tiny_db, ["BOS"]), "missing")


# ---- extra checks ------------------------------------------------------------------


def test_both_tools_registered():
    assert RANK in TOOLS
    assert PROFILE in TOOLS
    names = [spec["function"]["name"] for spec in tool_specs_for_ai()]
    assert RANK in names and PROFILE in names


# ---- real data -----------------------------------------------------------------------


@pytest.mark.realdata
def test_real_new_england_ranking(real_db):
    result = _rank(real_db, region="New England")
    rows = _rows(result)
    assert rows, result["about"]
    assert all(row["state"] in NEW_ENGLAND for row in rows)
    ranks = [row["national_rank"] for row in rows]
    assert ranks == sorted(ranks)  # the list keeps the national order
    print("\nNew England ranking (score):")
    for row in rows:
        print(
            f"  #{row['national_rank']:>3} {row['iata']} {row['state']} {row['size']}: score {row['value']}, "
            f"demand {row['demand_score']}, strain {row['strain_score']}, flags {row['flags']}, "
            f"missing {row['missing']}"
        )
    print("  about:", result["about"])


@pytest.mark.realdata
def test_real_lax_vs_sna_profile(real_db):
    result = _profile(real_db, ["LAX", "SNA"])
    entries = result["data"]["airports"]
    assert [e["iata"] for e in entries] == ["LAX", "SNA"]
    print("\nLAX vs SNA profile:")
    for entry in entries:
        assert set(entry) == PROFILE_KEYS
        print(
            f"  {entry['iata']} {entry['name']} ({entry['size']}): rank {entry['national_rank']}, "
            f"score {entry['final_score']}, strain {entry['strain_score']}, flags {entry['flags']}"
        )
        for name, cell in entry["congestion"]["measures"].items():
            print(f"    {name}: {cell['value']} (grade {cell['grade']})")
    print("  about:", result["about"])
