"""Answer-quality fixes, round 1 (P75-P79): score parts, grade levels, unmet months, measure label, prompt lines.

What the builder must follow (names the tests rely on)
------------------------------------------------------
Fix A (P75) score parts
* Every rank_airports row (every sort_by) and every airport_profile entry gets
  `demand_points` and `strain_points`: {measure name: points}.
  points of measure m in a half = grade_m * w_m / (sum of w over the half's measures
  the airport HAS a grade for), rounded to 1 decimal like the scores.
  Weights = the ones used: custom weights for rank_airports with sort_by "score",
  else the default weights (also for a rank by a measure, so the LAX row of a
  load_factor ranking has the same points as the LAX row of the score ranking).
  A measure with no grade is left out; no graded measure or total weight 0 -> {}.
  An airport with no score (profile of an airport under the size filter) -> {} for both.
* The `about` assumptions of rank_airports and airport_profile hold the P75 line. The
  test reads it from docs/implementation-plan.md: the P75 row must quote it in double
  quotes, starting with "demand_points / strain_points =".
Fix B (P76) grade levels
* `grade_level(grade)` in app/tools/base.py: >= 67 "high", <= 33 "low", else "middle",
  None -> None.
* airport_profile cells (measures and congestion.measures) = {"value", "grade", "level"}.
* rank_airports: every row gets `level` (level of the row's `grade`, None when no grade);
  rows that have `grades` (sort_by "score") also get `levels` = {measure: level} with the
  same keys as `grades`.
* unmet_demand why.runway_and_taxi cells = {"value", "grade", "level"}.
* NOTE_GRADES (app/tools/rank.py) ends with the P76 sentence. The P76 row must quote
  it in double quotes, starting with "level = high".
Fix C (P77) unmet months
* Each estimate gets `months_over_target` ([{"month", "load_factor", "missing_seats"}]
  for months with missing_seats > 0, month order) and `annual_vs_target` (one sentence,
  format in the spec; the case "load factor not known" can't be reached with the tiny
  dataset, so it is not tested here).
Fix D (P78) measure label
* rank_airports data gets `measure_label`: MEASURES[sort_by].label; for "score"
  "Final score (demand 40% + strain 60% by default)" with no custom weights, else
  "Final score (demand {d}% + strain {s}%)" with the half totals written with :g
  (50, not 50.0), and never "by default" for custom weights.
Fix E (P79) prompt lines
* The six new "how to work" lines are plain "- " bullets under "## Rules in the system
  prompt" in docs/agent.md (no numbers: test_step14 counts the numbered rules; no
  backticks), each copied word for word into SYSTEM_PROMPT.

HAND-WORKED GRADES (tiny dataset; full table in tests/test_step10_rank_profile.py)
=================================================================================
         growth_long D1  growth_short D2  load_factor S1  nas_delay S2  taxi_out S3  dep_per_runway S4
BOS      66.7            50.0             16.7            60.0          60.0         33.3
MHT      83.3            83.3             83.3            0.0           0.0          16.7
BTV      16.7            16.7             0.0             None          None         0.0
LAX      0.0             66.7             33.3            80.0          80.0         66.7
SNA      33.3            0.0              50.0            40.0          20.0         50.0
ANC      50.0            33.3             66.7            20.0          40.0         83.3
Default weights: D1 20, D2 20 (demand total 40); S1 20, S2 15, S3 10, S4 15 (strain total 60).
Scores: demand MHT 83.3, BOS 58.35, ANC 41.65, LAX 33.35, BTV 16.7, SNA 16.65;
        strain LAX 61.1, ANC 54.7, SNA 42.5, BOS 38.9, MHT 31.9, BTV 0.0.

Monthly load factors (TINY_DATA.md): BOS Jan .70 Jul .884 year .792; MHT Jan .84 Jul .96
year .90; BTV Jan .70 Jul .756 year .728; LAX Jan .82 Jul .82 year .82.
"""

import re
from pathlib import Path

import pytest

import app.tools  # noqa: F401  (registers the tools)
from app.agent.prompt import SYSTEM_PROMPT
from app.measures import MEASURES
from app.tools.base import run_tool

RANK = "rank_airports"
PROFILE = "airport_profile"
UNMET = "unmet_demand"

ROUND = 0.051  # a value rounded to 1 decimal is within 0.05 of the exact value
ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "implementation-plan.md"
AGENT_MD = ROOT / "docs" / "agent.md"

DEMAND = ["growth_long", "growth_short"]
STRAIN = ["load_factor", "nas_delay_per_flight", "taxi_out_min", "departures_per_runway"]
SCORED = DEMAND + STRAIN

# Hand-worked grades (table above).
GRADES = {
    "BOS": {"growth_long": 66.7, "growth_short": 50.0, "load_factor": 16.7, "nas_delay_per_flight": 60.0,
            "taxi_out_min": 60.0, "departures_per_runway": 33.3},
    "MHT": {"growth_long": 83.3, "growth_short": 83.3, "load_factor": 83.3, "nas_delay_per_flight": 0.0,
            "taxi_out_min": 0.0, "departures_per_runway": 16.7},
    "BTV": {"growth_long": 16.7, "growth_short": 16.7, "load_factor": 0.0, "nas_delay_per_flight": None,
            "taxi_out_min": None, "departures_per_runway": 0.0},
    "LAX": {"growth_long": 0.0, "growth_short": 66.7, "load_factor": 33.3, "nas_delay_per_flight": 80.0,
            "taxi_out_min": 80.0, "departures_per_runway": 66.7},
    "SNA": {"growth_long": 33.3, "growth_short": 0.0, "load_factor": 50.0, "nas_delay_per_flight": 40.0,
            "taxi_out_min": 20.0, "departures_per_runway": 50.0},
    "ANC": {"growth_long": 50.0, "growth_short": 33.3, "load_factor": 66.7, "nas_delay_per_flight": 20.0,
            "taxi_out_min": 40.0, "departures_per_runway": 83.3},
}  # fmt: skip
DEMAND_SCORE = {"MHT": 83.3, "BOS": 58.35, "ANC": 41.65, "LAX": 33.35, "BTV": 16.7, "SNA": 16.65}
STRAIN_SCORE = {"LAX": 61.1, "ANC": 54.7, "SNA": 42.5, "BOS": 38.9, "MHT": 31.9, "BTV": 0.0}

# Default-weight points, worked out by hand: grade * weight / half total.
POINTS = {
    "LAX": {
        # demand total 20 + 20 = 40
        "demand": {"growth_long": 0.0, "growth_short": 33.35},  # 0*20/40; 66.7*20/40 = 33.35
        # strain total 20 + 15 + 10 + 15 = 60
        "strain": {
            "load_factor": 11.1,  # 33.3*20/60 = 11.1
            "nas_delay_per_flight": 20.0,  # 80*15/60 = 20.0
            "taxi_out_min": 13.333,  # 80*10/60 = 13.33
            "departures_per_runway": 16.675,  # 66.7*15/60 = 16.675
        },  # sum 61.108 -> strain_score 61.1
    },
    "MHT": {
        "demand": {"growth_long": 41.65, "growth_short": 41.65},  # 83.3*20/40 each; sum 83.3
        "strain": {
            "load_factor": 27.767,  # 83.3*20/60
            "nas_delay_per_flight": 0.0,
            "taxi_out_min": 0.0,
            "departures_per_runway": 4.175,  # 16.7*15/60
        },  # sum 31.94 -> strain 31.9; load_factor is the biggest reason
    },
    "BOS": {
        "demand": {"growth_long": 33.35, "growth_short": 25.0},  # 66.7*20/40; 50*20/40
        "strain": {
            "load_factor": 5.567,  # 16.7*20/60
            "nas_delay_per_flight": 15.0,  # 60*15/60
            "taxi_out_min": 10.0,  # 60*10/60
            "departures_per_runway": 8.325,  # 33.3*15/60
        },  # sum 38.89 -> strain 38.9
    },
    "BTV": {
        "demand": {"growth_long": 8.35, "growth_short": 8.35},  # 16.7*20/40 each
        # S2, S3 have no grade: left out, strain total = 20 + 15 = 35 -> 0*20/35, 0*15/35
        "strain": {"load_factor": 0.0, "departures_per_runway": 0.0},
    },
}

# The six prompt lines of P79, found in docs/agent.md by one keyword each.
PROMPT_KEYWORDS = [
    "level word",
    "demand_points and strain_points",
    "annual_vs_target",
    '"only"',
    "no tool returned",
    "earlier tool result",
]


# ---- helpers -------------------------------------------------------------------


def _ok(result):
    assert isinstance(result, dict) and "error" not in result, result
    return result


def _rank(con, **settings):
    return _ok(run_tool(con, RANK, settings))


def _rows(result):
    return {row["iata"]: row for row in result["data"]["airports"]}


def _profile(con, airports):
    return {e["iata"]: e for e in _ok(run_tool(con, PROFILE, {"airports": airports}))["data"]["airports"]}


def _unmet(con, airports, **settings):
    return {e["iata"]: e for e in _ok(run_tool(con, UNMET, {"airports": airports, **settings}))["data"]["airports"]}


def _grade_level():
    from app.tools.base import grade_level

    return grade_level


def _norm(text):
    return " ".join(text.replace("`", "").replace("*", "").split())


def _plan_quote(decision, start):
    """The one double-quoted text in a decision row that begins with `start`."""
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {decision} |"):
            found = [q for q in re.findall(r'"([^"]+)"', line) if q.startswith(start)]
            assert len(found) == 1, (decision, start, found)
            return found[0]
    raise AssertionError(f"{decision} row not found in {PLAN}")


def POINTS_LINE():
    return _plan_quote("P75", "demand_points / strain_points =")


def LEVEL_SENTENCE():
    return _plan_quote("P76", "level = high")


def _assert_points(actual, expected):
    """Same keys; each value within rounding of the hand value and rounded to 1 decimal."""
    assert set(actual) == set(expected), (actual, expected)
    for name, value in expected.items():
        assert actual[name] == pytest.approx(value, abs=ROUND), (name, actual[name], value)
        assert round(actual[name], 1) == pytest.approx(actual[name], abs=1e-9), (name, actual[name])


def _assert_sum_rule(points, score):
    """The points of a half add up to that half's score, apart from rounding."""
    if score is None:
        assert points == {}
        return
    assert sum(points.values()) == pytest.approx(score, abs=0.05 * len(points) + 0.05), (points, score)


# ---- Fix A: score parts ---------------------------------------------------------


def test_rank_score_rows_have_points(tiny_db):
    rows = _rows(_rank(tiny_db))
    for code, expected in POINTS.items():
        _assert_points(rows[code]["demand_points"], expected["demand"])
        _assert_points(rows[code]["strain_points"], expected["strain"])
    # LAX: the biggest strain reason is nas_delay_per_flight (20.0 points)
    lax = rows["LAX"]["strain_points"]
    assert max(lax, key=lax.get) == "nas_delay_per_flight"
    # MHT: load_factor (27.8 points)
    mht = rows["MHT"]["strain_points"]
    assert max(mht, key=mht.get) == "load_factor"


def test_points_add_up_to_the_half_scores(tiny_db):
    rows = _rows(_rank(tiny_db))
    assert set(rows) == set(STRAIN_SCORE)
    for code, row in rows.items():
        _assert_sum_rule(row["demand_points"], row["demand_score"])
        _assert_sum_rule(row["strain_points"], row["strain_score"])
        # and the hand scores: e.g. MHT strain 27.767 + 0 + 0 + 4.175 = 31.94 -> 31.9
        _assert_sum_rule(row["demand_points"], DEMAND_SCORE[code])
        _assert_sum_rule(row["strain_points"], STRAIN_SCORE[code])


def test_missing_measure_is_left_out_and_weights_rescaled(tiny_db):
    btv = _rows(_rank(tiny_db))["BTV"]
    # BTV has no S2, S3 grade: only load_factor and departures_per_runway, total weight 35
    assert set(btv["strain_points"]) == {"load_factor", "departures_per_runway"}
    _assert_points(btv["strain_points"], POINTS["BTV"]["strain"])
    _assert_points(btv["demand_points"], POINTS["BTV"]["demand"])


def test_points_use_custom_weights(tiny_db):
    # weights D1 20, D2 30 (demand total 50); S1 20, S2 10, S3 10, S4 10 (strain total 50)
    weights = {"D1": 20, "D2": 30, "S1": 20, "S2": 10, "S3": 10, "S4": 10}
    rows = _rows(_rank(tiny_db, weights=weights))
    lax = rows["LAX"]
    # demand: 0*20/50 = 0; 66.7*30/50 = 40.02 -> demand_score 40.0
    _assert_points(lax["demand_points"], {"growth_long": 0.0, "growth_short": 40.02})
    # strain: 33.3*20/50 = 13.32; 80*10/50 = 16; 80*10/50 = 16; 66.7*10/50 = 13.34
    #   sum 58.66 -> strain_score (666 + 800 + 800 + 667) / 50 = 58.66 -> 58.7
    _assert_points(
        lax["strain_points"],
        {"load_factor": 13.32, "nas_delay_per_flight": 16.0, "taxi_out_min": 16.0, "departures_per_runway": 13.34},
    )
    assert lax["strain_score"] == pytest.approx(58.66, abs=ROUND)
    for row in rows.values():
        _assert_sum_rule(row["demand_points"], row["demand_score"])
        _assert_sum_rule(row["strain_points"], row["strain_score"])

    # {D1 50, D2 50}: strain weights total 0 -> strain_points {}
    half = _rows(_rank(tiny_db, weights={"D1": 50, "D2": 50}))
    for row in half.values():
        assert row["strain_points"] == {}
    # MHT demand: 83.3*50/100 = 41.65 each
    _assert_points(half["MHT"]["demand_points"], {"growth_long": 41.65, "growth_short": 41.65})


def test_rank_by_measure_rows_have_default_points(tiny_db):
    # sort_by a measure: no custom weights allowed, so the default-weight points
    rows = _rows(_rank(tiny_db, sort_by="load_factor"))
    for code, expected in POINTS.items():
        _assert_points(rows[code]["demand_points"], expected["demand"])
        _assert_points(rows[code]["strain_points"], expected["strain"])
    strain_rows = _rows(_rank(tiny_db, sort_by="strain_score"))
    _assert_points(strain_rows["LAX"]["strain_points"], POINTS["LAX"]["strain"])


def test_profile_has_points(tiny_db):
    entries = _profile(tiny_db, ["LAX", "BOS", "BTV"])
    for code in ("LAX", "BOS", "BTV"):
        _assert_points(entries[code]["demand_points"], POINTS[code]["demand"])
        _assert_points(entries[code]["strain_points"], POINTS[code]["strain"])
        _assert_sum_rule(entries[code]["strain_points"], entries[code]["strain_score"])
        _assert_sum_rule(entries[code]["demand_points"], entries[code]["demand_score"])


def test_profile_airport_without_score_has_no_points(tiny_db):
    # BHB (55,000 boardings) is under the size filter: no score -> {} for both
    bhb = _profile(tiny_db, ["BHB"])["BHB"]
    assert bhb["final_score"] is None
    assert bhb["demand_points"] == {}
    assert bhb["strain_points"] == {}


def test_points_line_in_about(tiny_db):
    line = _norm(POINTS_LINE())
    assert "they add up to that score" in line  # the doc helper found the right sentence
    for result in (
        _rank(tiny_db),
        _rank(tiny_db, sort_by="load_factor"),
        _ok(run_tool(tiny_db, PROFILE, {"airports": ["BOS"]})),
    ):
        assert line in [_norm(a) for a in result["about"]["assumptions"]], result["about"]["assumptions"]


# ---- Fix B: grade levels --------------------------------------------------------


@pytest.mark.parametrize(
    "grade, level",
    [
        (0.0, "low"),
        (33, "low"),  # 33 or less
        (33.0, "low"),
        (33.1, "middle"),
        (33.3, "middle"),  # a real fixture grade (2/6)
        (50.0, "middle"),
        (66.7, "middle"),  # a real fixture grade (4/6): under 67
        (66.9, "middle"),
        (67, "high"),  # 67 or more
        (83.3, "high"),
        (100.0, "high"),
        (None, None),
    ],
)
def test_grade_level_edges(grade, level):
    assert _grade_level()(grade) == level


def test_profile_cells_have_level(tiny_db):
    entries = _profile(tiny_db, ["BOS", "LAX", "BTV", "BHB"])
    grade_level = _grade_level()
    # hand-picked: BOS load_factor 16.7 low, BOS departures_per_runway 33.3 middle,
    # BOS growth_long 66.7 middle, LAX nas_delay_per_flight 80 high, LAX growth_long 0 low,
    # BTV nas_delay_per_flight None -> None
    expected = {
        ("BOS", "load_factor"): "low",
        ("BOS", "departures_per_runway"): "middle",
        ("BOS", "growth_long"): "middle",
        ("LAX", "nas_delay_per_flight"): "high",
        ("LAX", "growth_long"): "low",
        ("BTV", "nas_delay_per_flight"): None,
        ("BTV", "taxi_out_min"): None,
    }
    for (code, name), level in expected.items():
        assert entries[code]["measures"][name]["level"] == level, (code, name)
    for code, entry in entries.items():
        for name, cell in entry["measures"].items():
            assert set(cell) == {"value", "grade", "level"}, cell
            assert cell["level"] == grade_level(cell["grade"]), (code, name)
        for name, cell in entry["congestion"]["measures"].items():
            assert cell == entry["measures"][name]  # level there too
    # BHB has no grades -> every level None
    assert all(cell["level"] is None for cell in entries["BHB"]["measures"].values())


def test_rank_rows_have_levels(tiny_db):
    rows = _rows(_rank(tiny_db))
    # MHT: D1 83.3 high, D2 83.3 high, S1 83.3 high, S2 0 low, S3 0 low, S4 16.7 low
    assert rows["MHT"]["levels"] == {
        "growth_long": "high",
        "growth_short": "high",
        "load_factor": "high",
        "nas_delay_per_flight": "low",
        "taxi_out_min": "low",
        "departures_per_runway": "low",
    }
    # BTV: no S2, S3 grade -> no S2, S3 level; D1 16.7 low, D2 16.7 low, S1 0 low, S4 0 low
    assert rows["BTV"]["levels"] == {
        "growth_long": "low",
        "growth_short": "low",
        "load_factor": "low",
        "departures_per_runway": "low",
    }
    for row in rows.values():
        assert set(row["levels"]) == set(row["grades"])
        assert row["level"] is None  # the score has no grade

    # by a measure: level of the row's grade. S4: ANC 83.3 high, LAX 66.7 middle,
    # SNA 50 middle, BOS 33.3 middle, MHT 16.7 low, BTV 0 low
    s4 = _rows(_rank(tiny_db, sort_by="departures_per_runway"))
    assert {code: row["level"] for code, row in s4.items()} == {
        "ANC": "high",
        "LAX": "middle",
        "SNA": "middle",
        "BOS": "middle",
        "MHT": "low",
        "BTV": "low",
    }


def test_unmet_runway_and_taxi_have_level(tiny_db):
    entries = _unmet(tiny_db, ["BOS", "LAX", "SNA", "BTV"])
    # BOS dpr 33.3 middle, taxi 60 middle; LAX taxi 80 high; SNA taxi 20 low;
    # BTV dpr 0 low, taxi None -> None
    expected = {
        ("BOS", "departures_per_runway"): "middle",
        ("BOS", "taxi_out_min"): "middle",
        ("LAX", "taxi_out_min"): "high",
        ("SNA", "taxi_out_min"): "low",
        ("BTV", "departures_per_runway"): "low",
        ("BTV", "taxi_out_min"): None,
    }
    for (code, name), level in expected.items():
        cell = entries[code]["why"]["runway_and_taxi"][name]
        assert set(cell) == {"value", "grade", "level"}, cell
        assert cell["level"] == level, (code, name)


def test_note_grades_has_level_sentence(tiny_db):
    from app.tools.rank import NOTE_GRADES

    sentence = _norm(LEVEL_SENTENCE())
    assert "a low cancel_rate level means fewer cancellations" in sentence  # helper found it
    assert _norm(NOTE_GRADES).endswith(sentence)
    notes = " ".join(_norm(a) for a in _rank(tiny_db)["about"]["assumptions"])
    assert sentence in notes


# ---- Fix C: unmet demand months ---------------------------------------------------


def _estimate(entry, target):
    found = [e for e in entry["estimates"] if abs(e["target"] - target) < 1e-9]
    assert len(found) == 1, entry["estimates"]
    return found[0]


def _assert_months(actual, expected):
    """expected: [(month, load_factor, missing_seats)]."""
    assert [m["month"] for m in actual] == [m for m, _lf, _ms in expected], actual
    for item, (_month, lf, ms) in zip(actual, expected):
        assert set(item) == {"month", "load_factor", "missing_seats"}, item
        assert item["load_factor"] == pytest.approx(lf, abs=1e-6)
        assert item["missing_seats"] == pytest.approx(ms, abs=1e-3)


def test_months_over_target(tiny_db):
    entries = _unmet(tiny_db, ["BOS", "MHT", "LAX", "BTV"])
    # BOS 80%: Jan 1,400/0.8 = 1,750 < 2,000 -> 0; Jul 1,768/0.8 - 2,000 = 210
    _assert_months(_estimate(entries["BOS"], 0.80)["months_over_target"], [(7, 0.884, 210.0)])
    # BOS 85%: Jul 1,768/0.85 - 2,000 = 80
    _assert_months(_estimate(entries["BOS"], 0.85)["months_over_target"], [(7, 0.884, 80.0)])
    # MHT 80%: Jan 840/0.8 - 1,000 = 50; Jul 960/0.8 - 1,000 = 200
    _assert_months(_estimate(entries["MHT"], 0.80)["months_over_target"], [(1, 0.84, 50.0), (7, 0.96, 200.0)])
    # MHT 85%: Jan 988.24 < 1,000 -> 0; Jul 960/0.85 - 1,000 = 129.412
    _assert_months(_estimate(entries["MHT"], 0.85)["months_over_target"], [(7, 0.96, 960 / 0.85 - 1000)])
    # LAX 85%: 2,460/0.85 = 2,894.1 < 3,000 both months -> none
    assert _estimate(entries["LAX"], 0.85)["months_over_target"] == []
    # BTV 80%: Jan 350/0.8 = 437.5 < 500, Jul 378/0.8 = 472.5 < 500 -> none
    assert _estimate(entries["BTV"], 0.80)["months_over_target"] == []


def test_annual_vs_target_sentences(tiny_db):
    entries = _unmet(tiny_db, ["BOS", "MHT", "LAX", "BTV"])
    cases = [
        # year 3,168 / 4,000 = .792 < .80; one month (Jul) over
        ("BOS", 0.80, "The 2025 load factor (79.2%) is below the 80% target; 1 month is above it: Jul."),
        ("BOS", 0.85, "The 2025 load factor (79.2%) is below the 85% target; 1 month is above it: Jul."),
        # year 1,800 / 2,000 = .90 > .80; Jan and Jul over
        ("MHT", 0.80, "The 2025 load factor (90.0%) is above the 80% target; 2 months are above it: Jan, Jul."),
        ("MHT", 0.85, "The 2025 load factor (90.0%) is above the 85% target; 1 month is above it: Jul."),
        # year 4,920 / 6,000 = .82 > .80; both months .82 over
        ("LAX", 0.80, "The 2025 load factor (82.0%) is above the 80% target; 2 months are above it: Jan, Jul."),
        # .82 < .85; no month over
        ("LAX", 0.85, "The 2025 load factor (82.0%) is below the 85% target; no month is above it."),
        # year 728 / 1,000 = .728 < .80; no month over
        ("BTV", 0.80, "The 2025 load factor (72.8%) is below the 80% target; no month is above it."),
    ]
    for code, target, sentence in cases:
        assert _estimate(entries[code], target)["annual_vs_target"] == sentence, (code, target)


def test_annual_vs_target_equal(tiny_db):
    # LAX custom target 0.82: year 4,920 / 6,000 = 0.82 (equal within 1e-9);
    # each month 2,460 / 0.82 - 3,000 = 0 -> no month over
    lax = _unmet(tiny_db, ["LAX"], target_load_factor=0.82)["LAX"]
    custom = _estimate(lax, 0.82)
    assert custom["months_over_target"] == []
    assert custom["annual_vs_target"] == "The 2025 load factor (82.0%) is equal to the 82% target; no month is above it."


# ---- Fix D: measure label ---------------------------------------------------------


def test_measure_label_for_a_measure(tiny_db):
    for sort_by in ("load_factor", "departures_per_runway", "demand_score", "strain_score"):
        data = _rank(tiny_db, sort_by=sort_by)["data"]
        assert data["measure_label"] == MEASURES[sort_by].label, sort_by


def test_measure_label_for_score(tiny_db):
    assert _rank(tiny_db)["data"]["measure_label"] == "Final score (demand 40% + strain 60% by default)"
    # custom weights: half totals D1+D2 = 20+30 = 50, S1..S4 = 20+10+10+10 = 50
    custom = _rank(tiny_db, weights={"D1": 20, "D2": 30, "S1": 20, "S2": 10, "S3": 10, "S4": 10})
    assert custom["data"]["measure_label"] == "Final score (demand 50% + strain 50%)"
    # D1 50 + D2 50 = 100; strain 0
    half = _rank(tiny_db, weights={"D1": 50, "D2": 50})
    assert half["data"]["measure_label"] == "Final score (demand 100% + strain 0%)"
    # custom weights with the default totals still don't say "by default": 10+30 = 40, 30+10+10+10 = 60
    same = _rank(tiny_db, weights={"D1": 10, "D2": 30, "S1": 30, "S2": 10, "S3": 10, "S4": 10})
    assert same["data"]["measure_label"] == "Final score (demand 40% + strain 60%)"


# ---- Fix E: prompt lines ----------------------------------------------------------


def _bullets_from_agent_md():
    """The "- " bullets under '## Rules in the system prompt' in docs/agent.md."""
    bullets, inside = [], False
    for line in AGENT_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Rules in the system prompt"
            continue
        if inside and line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


@pytest.mark.parametrize("keyword", PROMPT_KEYWORDS)
def test_new_prompt_line_in_doc_and_prompt(keyword):
    found = [b for b in _bullets_from_agent_md() if keyword in b]
    assert len(found) == 1, (keyword, found)
    assert "- " + found[0] in SYSTEM_PROMPT, f"line missing word for word: {found[0]}"


def test_every_doc_bullet_is_in_the_prompt():
    bullets = _bullets_from_agent_md()
    assert len(bullets) >= len(PROMPT_KEYWORDS)
    for bullet in bullets:
        assert bullet in SYSTEM_PROMPT, f"line missing word for word: {bullet}"
