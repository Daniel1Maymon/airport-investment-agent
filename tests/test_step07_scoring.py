"""Step 7 tests: grades and final score (app/scoring.py).

What the builder must follow (names the tests rely on)
------------------------------------------------------
* `DEFAULT_WEIGHTS = {"D1": 20, "D2": 20, "S1": 20, "S2": 15, "S3": 10, "S4": 15}`.
* `percentile_grades(values: dict[str, float | None]) -> dict[str, float]`
  (P1, P13, P14): grade = (number lower + 1/2 x number of OTHER airports with
  the same value) / number of airports with a value x 100, rounded to 1
  decimal. Airports whose value is None are left out of the result.
* `score_airports(measures, weights=None, min_enplanements=100_000)`
  -> list[ScoredAirport], best first. `measures` is the dict returned by
  `compute_measures(con)`. ScoredAirport has
  `iata, raw, grades, final_score, demand_score, strain_score, rank, flags, missing`.
* `WeightsError` for an unknown key, a negative value, or a total other than 100 (P20).
* Weight keys -> measures (P15): D1 growth_long, D2 growth_short, S1 load_factor,
  S2 nas_delay_per_flight, S3 taxi_out_min, S4 departures_per_runway.

Every expected value below is worked out by hand from
tests/fixtures/TINY_DATA.md ("Hand-worked numbers"); compute_measures (Step 6,
already tested) is only used to produce the INPUT.

HAND-WORKED TABLE (tiny dataset, default settings)
==================================================
Size filter (P21): enplanements 2025 >= 100,000. BHB has 55,000 -> left out.
Graded: BOS, MHT, BTV, LAX, SNA, ANC (6 airports; 5 for S2/S3, BTV has no delays).

Raw measures (fractions per P11):
  airport  D1 growth_long  D2 growth_short  S1 load_factor  S2 nas  S3 taxi  S4 dep/runway
  BOS      0.10            0.05             0.792           8       20       10
  MHT      0.50            0.20             0.90            1       12        8
  BTV      0.04            0.03             0.728           None    None      5
  LAX      0.025           0.06             0.82            10      22       15
  SNA      0.05            0.02             0.84            3       14       12
  ANC      0.08            0.04             0.864           2       16       30

Grades (number of airports lower / pool size x 100, no ties, 1 decimal):
  D1 (pool 6): LAX 0/6=0, BTV 1/6=16.7, SNA 2/6=33.3, ANC 3/6=50.0, BOS 4/6=66.7, MHT 5/6=83.3
  D2 (pool 6): SNA 0, BTV 16.7, ANC 33.3, BOS 50.0, LAX 66.7, MHT 83.3
  S1 (pool 6): BTV 0, BOS 16.7, LAX 33.3, SNA 50.0, ANC 66.7, MHT 83.3
  S2 (pool 5): MHT 0/5=0, ANC 1/5=20, SNA 2/5=40, BOS 3/5=60, LAX 4/5=80
  S3 (pool 5): MHT 0, SNA 20, ANC 40, BOS 60, LAX 80
  S4 (pool 6): BTV 0, MHT 16.7, BOS 33.3, SNA 50.0, LAX 66.7, ANC 83.3

Final score = sum(weight x grade) / sum(weights of measures with a value) (P16, P17):
  MHT .2*83.3+.2*83.3+.2*83.3+.15*0+.1*0+.15*16.7 = 49.98+2.505          = 52.485 -> 52.5
  LAX .2*0+.2*66.7+.2*33.3+.15*80+.1*80+.15*66.7 = 13.34+6.66+12+8+10.005 = 50.005 -> 50.0
  ANC .2*50+.2*33.3+.2*66.7+.15*20+.1*40+.15*83.3 = 10+6.66+13.34+3+4+12.495 = 49.495 -> 49.5
  BOS .2*66.7+.2*50+.2*16.7+.15*60+.1*60+.15*33.3 = 13.34+10+3.34+9+6+4.995 = 46.675 -> 46.7
  SNA .2*33.3+.2*0+.2*50+.15*40+.1*20+.15*50 = 6.66+0+10+6+2+7.5           = 32.16  -> 32.2
  BTV (S2, S3 missing; weights 20+20+20+15 = 75)
      (20*16.7+20*16.7+20*0+15*0)/75 = 668/75                              = 8.907  -> 8.9

Rank: 1 MHT 52.5, 2 LAX 50.0, 3 ANC 49.5, 4 BOS 46.7, 5 SNA 32.2, 6 BTV 8.9.

demand_score = (20*D1 + 20*D2) / 40 (P18):
  BOS (66.7+50)/2 = 58.35   MHT (83.3+83.3)/2 = 83.3   BTV (16.7+16.7)/2 = 16.7
  LAX (0+66.7)/2  = 33.35   SNA (33.3+0)/2    = 16.65  ANC (50+33.3)/2   = 41.65
  (x.x5 values are exactly halfway: either 1-decimal rounding is accepted.)
strain_score = (20*S1 + 15*S2 + 10*S3 + 15*S4) / 60 (P18):
  BOS (334+900+600+499.5)/60   = 2333.5/60 = 38.89 -> 38.9
  MHT (1666+0+0+250.5)/60      = 1916.5/60 = 31.94 -> 31.9
  BTV (20*0+15*0)/35           = 0.0       (S2, S3 skipped)
  LAX (666+1200+800+1000.5)/60 = 3666.5/60 = 61.11 -> 61.1
  SNA (1000+600+200+750)/60    = 2550/60   = 42.5
  ANC (1334+300+400+1249.5)/60 = 3283.5/60 = 54.73 -> 54.7

Flags (P19): load_factor > 0.85 -> MHT 0.90, ANC 0.864 get "planes over 85% full".
No NAS grade reaches 90 (top is LAX 80). BTV has both delay measures missing
-> "scored without delay data".
"""

import copy

import pytest

from app.measures import compute_measures
from app.scoring import (
    DEFAULT_WEIGHTS,
    ScoredAirport,
    WeightsError,
    percentile_grades,
    score_airports,
)

ROUND = 0.051  # tolerance for numbers rounded to 1 decimal
HALF = 0.051  # used on exact x.x5 values: accepts both x.x and x.x+0.1

SCORED_MEASURES = (
    "growth_long",
    "growth_short",
    "load_factor",
    "nas_delay_per_flight",
    "taxi_out_min",
    "departures_per_runway",
)
FIELDS = ("iata", "raw", "grades", "final_score", "demand_score", "strain_score", "rank", "flags", "missing")


def _airport(enplanements=1_000_000, **values):
    """A hand-made measure row: the six scored measures (default None) plus enplanements."""
    row = {name: None for name in SCORED_MEASURES}
    row["enplanements"] = enplanements
    row.update(values)
    return row


def _full(value, enplanements=1_000_000):
    """A hand-made airport with the same value on all six scored measures."""
    return _airport(enplanements, **{name: value for name in SCORED_MEASURES})


def _by_iata(result):
    return {a.iata: a for a in result}


@pytest.fixture
def tiny_measures(tiny_db):
    return compute_measures(tiny_db)


@pytest.fixture
def scored(tiny_measures):
    return score_airports(tiny_measures)


# 1
def test_percentile_grades():
    # pool of 4 (E has no value, left out):
    # A: 0 lower -> 0/4 = 0; B: 1/4 = 25; C: 2/4 = 50; D: 3/4 = 75
    grades = percentile_grades({"A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0, "E": None})
    assert set(grades) == {"A", "B", "C", "D"}
    assert grades["A"] == pytest.approx(0.0, abs=ROUND)
    assert grades["B"] == pytest.approx(25.0, abs=ROUND)
    assert grades["C"] == pytest.approx(50.0, abs=ROUND)
    assert grades["D"] == pytest.approx(75.0, abs=ROUND)

    # the order of the input does not matter; top of 6 = 5/6 = 83.3 (P13)
    six = percentile_grades({"F": 6, "B": 2, "D": 4, "A": 1, "E": 5, "C": 3})
    assert six["F"] == pytest.approx(83.3, abs=ROUND)  # 5/6*100 = 83.33
    assert six["B"] == pytest.approx(16.7, abs=ROUND)  # 1/6*100 = 16.67
    assert six["A"] == pytest.approx(0.0, abs=ROUND)


# 2
def test_ties_get_same_grade():
    # pool of 4: A 0/4 = 0; B and C tie: (1 lower + 0.5 * 1 other equal) / 4 = 37.5; D 3/4 = 75
    grades = percentile_grades({"A": 1.0, "B": 2.0, "C": 2.0, "D": 3.0})
    assert grades["B"] == grades["C"]
    assert grades["B"] == pytest.approx(37.5, abs=ROUND)
    assert grades["A"] == pytest.approx(0.0, abs=ROUND)
    assert grades["D"] == pytest.approx(75.0, abs=ROUND)

    # all equal: (0 lower + 0.5 * 1 other) / 2 = 25 each
    same = percentile_grades({"X": 5.0, "Y": 5.0})
    assert same["X"] == same["Y"] == pytest.approx(25.0, abs=ROUND)


# 3
def test_default_weights_total_100():
    assert DEFAULT_WEIGHTS == {"D1": 20, "D2": 20, "S1": 20, "S2": 15, "S3": 10, "S4": 15}
    assert sum(DEFAULT_WEIGHTS.values()) == 100
    # demand 40, strain 60 (scoring.md)
    assert DEFAULT_WEIGHTS["D1"] + DEFAULT_WEIGHTS["D2"] == 40


# 4
def test_small_airport_filtered_out(scored, tiny_measures):
    # BHB: 55,000 enplanements in 2025 < 100,000
    codes = {a.iata for a in scored}
    assert "BHB" not in codes
    assert codes == {"BOS", "MHT", "BTV", "LAX", "SNA", "ANC"}

    # BHB is also left out of the grading pool: BHB's S4 = 10 would tie BOS's 10.
    # Without BHB, BOS S4 = 2 lower (BTV 5, MHT 8) / 6 = 33.3.
    # (With BHB it would be (2 + 0.5) / 7 = 35.7.)
    bos = _by_iata(scored)["BOS"]
    assert bos.grades["departures_per_runway"] == pytest.approx(33.3, abs=ROUND)

    # a lower size limit lets BHB in (55,000 >= 50,000)
    looser = score_airports(tiny_measures, min_enplanements=50_000)
    assert "BHB" in {a.iata for a in looser}
    assert len(looser) == 7

    # no enplanements value -> left out too
    hand = {"AAA": _full(1.0), "BBB": _full(2.0, enplanements=None)}
    assert [a.iata for a in score_airports(hand)] == ["AAA"]


# 5
def test_final_score_formula(scored, tiny_measures):
    bos = _by_iata(scored)["BOS"]
    # grades worked out in the table at the top of this file
    assert bos.grades["growth_long"] == pytest.approx(66.7, abs=ROUND)  # 4/6
    assert bos.grades["growth_short"] == pytest.approx(50.0, abs=ROUND)  # 3/6
    assert bos.grades["load_factor"] == pytest.approx(16.7, abs=ROUND)  # 1/6
    assert bos.grades["nas_delay_per_flight"] == pytest.approx(60.0, abs=ROUND)  # 3/5
    assert bos.grades["taxi_out_min"] == pytest.approx(60.0, abs=ROUND)  # 3/5
    assert bos.grades["departures_per_runway"] == pytest.approx(33.3, abs=ROUND)  # 2/6
    assert set(bos.grades) == set(SCORED_MEASURES)
    # .2*66.7 + .2*50 + .2*16.7 + .15*60 + .1*60 + .15*33.3
    # = 13.34 + 10 + 3.34 + 9 + 6 + 4.995 = 46.675 -> 46.7
    assert bos.final_score == pytest.approx(46.7, abs=ROUND)
    # raw is the airport's full measure dict from compute_measures (P15)
    assert bos.raw == tiny_measures["BOS"]
    assert bos.missing == []
    assert isinstance(bos, ScoredAirport)


# 6
def test_rank_order_on_tiny_data(scored):
    # MHT 52.5, LAX 50.0, ANC 49.5, BOS 46.7, SNA 32.2, BTV 8.9 (table at the top)
    assert [a.iata for a in scored] == ["MHT", "LAX", "ANC", "BOS", "SNA", "BTV"]
    assert [a.rank for a in scored] == [1, 2, 3, 4, 5, 6]
    expected = {"MHT": 52.5, "LAX": 50.0, "ANC": 49.5, "BOS": 46.7, "SNA": 32.2, "BTV": 8.9}
    for a in scored:
        assert a.final_score == pytest.approx(expected[a.iata], abs=ROUND), a.iata


def test_equal_scores_ordered_by_iata():
    # two identical airports: same grades, same score -> A->Z by code (P21)
    hand = {"ZZZ": _full(1.0), "AAA": _full(1.0)}
    result = score_airports(hand)
    assert [a.iata for a in result] == ["AAA", "ZZZ"]
    assert [a.rank for a in result] == [1, 2]
    assert result[0].final_score == result[1].final_score


# 7
def test_custom_weights_change_order(tiny_measures):
    # only long-term growth counts; the keys left out count as 0 (P20)
    # score = D1 grade: MHT 83.3, BOS 66.7, ANC 50.0, SNA 33.3, BTV 16.7, LAX 0
    result = score_airports(tiny_measures, weights={"D1": 100})
    assert [a.iata for a in result] == ["MHT", "BOS", "ANC", "SNA", "BTV", "LAX"]
    expected = {"MHT": 83.3, "BOS": 66.7, "ANC": 50.0, "SNA": 33.3, "BTV": 16.7, "LAX": 0.0}
    for a in result:
        assert a.final_score == pytest.approx(expected[a.iata], abs=ROUND), a.iata
    # LAX was 2nd with the default weights, now last
    assert _by_iata(result)["LAX"].rank == 6
    # the defaults are not changed by a custom call
    assert DEFAULT_WEIGHTS == {"D1": 20, "D2": 20, "S1": 20, "S2": 15, "S3": 10, "S4": 15}


# 8
def test_weights_not_100_refused(tiny_measures):
    with pytest.raises(WeightsError):
        score_airports(tiny_measures, weights={"D1": 50, "D2": 40})  # total 90
    with pytest.raises(WeightsError):
        score_airports(tiny_measures, weights={"D1": 60, "D2": 60})  # total 120
    with pytest.raises(WeightsError):
        score_airports(tiny_measures, weights={"D1": 50, "D3": 50})  # unknown key
    with pytest.raises(WeightsError):
        score_airports(tiny_measures, weights={"D1": 120, "D2": -20})  # negative, total 100
    # a hand-made dict is refused the same way
    with pytest.raises(WeightsError):
        score_airports({"AAA": _full(1.0)}, weights={"S1": 99})


# 9
def test_missing_delay_weights_scaled_up(scored):
    btv = _by_iata(scored)["BTV"]
    # BTV has no delay rows: it is still scored
    assert btv.missing == ["nas_delay_per_flight", "taxi_out_min"]  # D1...S4 order
    assert "scored without delay data" in btv.flags
    assert set(btv.grades) == {"growth_long", "growth_short", "load_factor", "departures_per_runway"}
    # weights 20+20+20+15 = 75 scaled up to 100:
    # (20*16.7 + 20*16.7 + 20*0 + 15*0) / 75 = 668 / 75 = 8.907 -> 8.9
    assert btv.final_score == pytest.approx(8.9, abs=ROUND)
    # (without scaling it would be 668 / 100 = 6.7)


def test_any_missing_measure_scaled_up():
    # P16: the same rule for any measure. Pool of 2 airports, AAA lower on all.
    # BBB has no runway data (S4 None): grades on the other five = 1 lower / 2 = 50.
    # final = (20+20+20+15+10)*50 / 85 = 50.0 ; S4 in missing; no delay flag.
    hand = {
        "AAA": _full(1.0),
        "BBB": _airport(
            growth_long=2.0, growth_short=2.0, load_factor=0.5,
            nas_delay_per_flight=2.0, taxi_out_min=2.0, departures_per_runway=None,
        ),
    }
    hand["AAA"]["load_factor"] = 0.4
    bbb = _by_iata(score_airports(hand))["BBB"]
    assert bbb.missing == ["departures_per_runway"]
    assert "departures_per_runway" not in bbb.grades
    assert bbb.final_score == pytest.approx(50.0, abs=ROUND)
    assert "scored without delay data" not in bbb.flags
    # AAA: S4 pool is only AAA -> 0/1 = 0; everything else 0/2 = 0 -> 0.0
    aaa = _by_iata(score_airports(hand))["AAA"]
    assert aaa.final_score == pytest.approx(0.0, abs=ROUND)
    assert aaa.missing == []


# 10
def test_demand_and_strain_scores(scored, tiny_measures):
    by = _by_iata(scored)
    # demand = (20*D1 + 20*D2) / 40; x.x5 values are exactly halfway (HALF tolerance)
    demand = {"BOS": 58.35, "MHT": 83.3, "BTV": 16.7, "LAX": 33.35, "SNA": 16.65, "ANC": 41.65}
    # strain = (20*S1 + 15*S2 + 10*S3 + 15*S4) / 60; BTV: (20*0 + 15*0) / 35 = 0
    strain = {"BOS": 38.9, "MHT": 31.9, "BTV": 0.0, "LAX": 61.1, "SNA": 42.5, "ANC": 54.7}
    for code in demand:
        assert by[code].demand_score == pytest.approx(demand[code], abs=HALF), code
        assert by[code].strain_score == pytest.approx(strain[code], abs=ROUND), code

    # custom weights are scaled the same way; a half with total weight 0 is None (P18)
    only_s1 = _by_iata(score_airports(tiny_measures, weights={"S1": 100}))
    assert only_s1["LAX"].demand_score is None
    assert only_s1["LAX"].strain_score == pytest.approx(33.3, abs=ROUND)  # LAX S1 grade 2/6
    assert only_s1["LAX"].final_score == pytest.approx(33.3, abs=ROUND)


def test_half_with_no_values_is_none():
    # BBB has no strain values at all -> strain_score None, final from demand only
    # pool of 2 for D1/D2: BBB higher -> 1/2 = 50 each -> demand 50, final 50
    hand = {
        "AAA": _full(1.0),
        "BBB": _airport(growth_long=2.0, growth_short=2.0),
    }
    bbb = _by_iata(score_airports(hand))["BBB"]
    assert bbb.strain_score is None
    assert bbb.demand_score == pytest.approx(50.0, abs=ROUND)
    assert bbb.final_score == pytest.approx(50.0, abs=ROUND)
    assert bbb.missing == ["load_factor", "nas_delay_per_flight", "taxi_out_min", "departures_per_runway"]
    assert bbb.flags == ["scored without delay data"]


# 11
def test_flags(scored):
    by = _by_iata(scored)
    # load factor > 0.85: MHT 0.90, ANC 0.864; no NAS grade reaches 90 (top LAX 80)
    assert by["MHT"].flags == ["planes over 85% full"]
    assert by["ANC"].flags == ["planes over 85% full"]
    assert by["BOS"].flags == []  # 0.792
    assert by["LAX"].flags == []  # 0.82, NAS grade 80 < 90
    assert by["SNA"].flags == []  # 0.84
    assert by["BTV"].flags == ["scored without delay data"]  # 0.728, no delay data


def test_nas_top_ten_percent_flag():
    # 10 airports, NAS 1..10. Top: 9 lower / 10 = 90 -> flag (>= 90). Next: 8/10 = 80 -> none.
    # load factor 0.86 on the top one too: both flags, in P19 order.
    hand = {}
    for i in range(1, 11):
        code = "A" + chr(ord("A") + i - 1) + "X"  # AAX, ABX, ... AJX
        hand[code] = _full(float(i))
        hand[code]["load_factor"] = 0.5
    hand["AJX"]["load_factor"] = 0.86
    by = _by_iata(score_airports(hand))
    assert by["AJX"].grades["nas_delay_per_flight"] == pytest.approx(90.0, abs=ROUND)
    assert by["AJX"].flags == ["planes over 85% full", "NAS delays in the top 10% nationally"]
    assert by["AIX"].flags == []
    # exactly 0.85 is not "over 85%"
    hand["AIX"]["load_factor"] = 0.85
    assert _by_iata(score_airports(hand))["AIX"].flags == []


# 12
def test_same_input_same_output(tiny_measures):
    before = copy.deepcopy(tiny_measures)
    first = score_airports(tiny_measures)
    second = score_airports(tiny_measures)
    as_rows = lambda result: [tuple(getattr(a, f) for f in FIELDS) for a in result]  # noqa: E731
    assert as_rows(first) == as_rows(second)
    # the input is not changed
    assert tiny_measures == before


# Real-data check (skipped when airports.duckdb is missing)


@pytest.mark.realdata
def test_real_full_ranking_under_one_second(real_db):
    # Plan, Step 7: the full ranking takes under 1 second; print the top 10.
    # No known real top 10 exists, so only the shape of the ranking is checked.
    import time

    start = time.perf_counter()
    measures = compute_measures(real_db)
    ranking = score_airports(measures)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"full ranking took {elapsed:.3f} s"
    assert ranking
    assert [a.rank for a in ranking] == list(range(1, len(ranking) + 1))
    # every airport passed the size filter
    assert all(a.raw["enplanements"] >= 100_000 for a in ranking)
    # final scores never go up down the list; airports with no score come last
    scored = [a.final_score for a in ranking if a.final_score is not None]
    assert scored == sorted(scored, reverse=True)
    first_none = next((i for i, a in enumerate(ranking) if a.final_score is None), len(ranking))
    assert all(a.final_score is None for a in ranking[first_none:])

    fmt = lambda v: "  -  " if v is None else f"{v:5.1f}"  # noqa: E731
    print(f"\nFull ranking: {len(ranking)} airports in {elapsed:.3f} s. Top 10:")
    print("rank  code  final  demand  strain")
    for a in ranking[:10]:
        print(f"{a.rank:>4}  {a.iata:<4}  {fmt(a.final_score)}  {fmt(a.demand_score)}   {fmt(a.strain_score)}")
