"""Grades and final score: turns the measure list into a ranked list of airports.

What it is:   Turns each of the six scored measures into a percentile grade from 0 to 100
              ("higher than X% of the US airports graded"), then a weighted average of
              the grades gives the final score.
Why we need:  compute_measures() (app/measures.py) gives raw numbers in different units
              (fractions, minutes, departures). They can only be added up on one scale.
Used by:      tests: test_step07_scoring.py only, so far.
              Planned: Step 10 tools `rank_airports` and `airport_profile`
              (app/tools/rank.py, app/tools/profile.py).
Uses:         the dict from compute_measures(), passed in by the caller. No database and
              no project imports.
Main parts:   DEFAULT_WEIGHTS - weight key (D1..S4) -> weight; they total 100.
              WEIGHT_MEASURES - weight key -> measure name (P15).
              DEMAND_KEYS, STRAIN_KEYS - the weight keys of each half of the score.
              DELAY_MEASURES - the two scored measures that come from delay data.
              FLAG_FULL, FLAG_NAS, FLAG_NO_DELAYS - the exact flag texts (P19).
              WeightsError - weights with an unknown key, a negative value, or not 100.
              ScoredAirport - one airport's raw measures, grades, scores, rank, flags,
                missing.
              percentile_grades(values) - grade each airport 0-100 against the others.
              score_airports(measures, weights=None, min_enplanements=100_000) - grade,
                score and rank every airport that passes the size filter, best first.
Design:       docs/scoring.md; docs/implementation-plan.md P1, P13-P22.

THE WEIGHTS (docs/scoring.md)
  Demand 40%: D1 growth_long 20, D2 growth_short 20
  Strain 60%: S1 load_factor 20, S2 nas_delay_per_flight 15,
              S3 taxi_out_min 10, S4 departures_per_runway 15

RULES (docs/implementation-plan.md, P13-P21)
  - Only airports with at least `min_enplanements` boardings are graded and
    ranked. Grades are national: every kept airport is in the pool.
  - A missing measure is skipped and the other weights are scaled up to 100;
    its name goes into `missing`. No airport is dropped for a gap in its data.
  - Same input, same output: no randomness, ties sorted by airport code.
"""

from dataclasses import dataclass, field

DEFAULT_WEIGHTS = {"D1": 20, "D2": 20, "S1": 20, "S2": 15, "S3": 10, "S4": 15}

# Weight key -> measure name (P15). Higher is better for all six.
WEIGHT_MEASURES = {
    "D1": "growth_long",
    "D2": "growth_short",
    "S1": "load_factor",
    "S2": "nas_delay_per_flight",
    "S3": "taxi_out_min",
    "S4": "departures_per_runway",
}
DEMAND_KEYS = ("D1", "D2")
STRAIN_KEYS = ("S1", "S2", "S3", "S4")
DELAY_MEASURES = ("nas_delay_per_flight", "taxi_out_min")

FLAG_FULL = "planes over 85% full"
FLAG_NAS = "NAS delays in the top 10% nationally"
FLAG_NO_DELAYS = "scored without delay data"


class WeightsError(ValueError):
    """Weights that use an unknown key, are negative, or don't total 100."""


@dataclass
class ScoredAirport:
    """One airport's raw measures, grades, scores, rank and plain-word notes."""

    iata: str
    raw: dict
    grades: dict
    final_score: float | None
    demand_score: float | None
    strain_score: float | None
    rank: int = 0
    flags: list = field(default_factory=list)
    missing: list = field(default_factory=list)


def percentile_grades(values: dict[str, float | None]) -> dict[str, float]:
    """Grade each airport 0-100 against the others (P13, P14).

    grade = (number lower + 1/2 x number of other airports with the same value)
            / number of airports with a value x 100, rounded to 1 decimal.
    Airports whose value is None are left out.
    """
    pool = {code: v for code, v in values.items() if v is not None}
    n = len(pool)
    grades = {}
    for code, v in pool.items():
        lower = sum(1 for other in pool.values() if other < v)
        same_others = sum(1 for other in pool.values() if other == v) - 1
        grades[code] = round((lower + 0.5 * same_others) / n * 100, 1)
    return grades


def _check_weights(weights):
    """The weights in force: the defaults, or a custom dict checked by P20."""
    if weights is None:
        return dict(DEFAULT_WEIGHTS)
    unknown = set(weights) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise WeightsError(f"Unknown weight key(s): {sorted(unknown)}; use D1, D2, S1, S2, S3, S4.")
    if any(w < 0 for w in weights.values()):
        raise WeightsError("Weights can't be negative.")
    if sum(weights.values()) != 100:
        raise WeightsError(f"Weights must total 100, not {sum(weights.values())}.")
    return {key: weights.get(key, 0) for key in DEFAULT_WEIGHTS}


def _weighted(grades, weights, keys):
    """Weighted average of the grades for `keys`, skipping missing ones; None if nothing counts."""
    used = [(weights[k], grades[WEIGHT_MEASURES[k]]) for k in keys if WEIGHT_MEASURES[k] in grades]
    total = sum(w for w, _ in used)
    if total == 0:
        return None
    return round(sum(w * g for w, g in used) / total, 1)


def score_airports(measures, weights=None, min_enplanements=100_000) -> list[ScoredAirport]:
    """Grade, score and rank every airport that passes the size filter, best first.

    `measures` is the dict from compute_measures(): {code: {measure: value}}.
    `weights` replaces DEFAULT_WEIGHTS; keys left out count as 0.
    """
    weights = _check_weights(weights)
    kept = {
        code: row
        for code, row in measures.items()
        if row.get("enplanements") is not None and row["enplanements"] >= min_enplanements
    }
    grades_by_measure = {
        name: percentile_grades({code: row.get(name) for code, row in kept.items()})
        for name in WEIGHT_MEASURES.values()
    }

    result = []
    for code, row in kept.items():
        grades = {name: g[code] for name, g in grades_by_measure.items() if code in g}
        missing = [name for name in WEIGHT_MEASURES.values() if name not in grades]
        flags = []
        if row.get("load_factor") is not None and row["load_factor"] > 0.85:
            flags.append(FLAG_FULL)
        if grades.get("nas_delay_per_flight", 0) >= 90:
            flags.append(FLAG_NAS)
        if all(name in missing for name in DELAY_MEASURES):
            flags.append(FLAG_NO_DELAYS)
        result.append(
            ScoredAirport(
                iata=code,
                raw=row,
                grades=grades,
                final_score=_weighted(grades, weights, DEFAULT_WEIGHTS),
                demand_score=_weighted(grades, weights, DEMAND_KEYS),
                strain_score=_weighted(grades, weights, STRAIN_KEYS),
                flags=flags,
                missing=missing,
            )
        )

    # Best first; an airport with no score at all goes last. Ties: code A->Z.
    result.sort(key=lambda a: (a.final_score is None, -(a.final_score or 0), a.iata))
    for rank, airport in enumerate(result, start=1):
        airport.rank = rank
    return result
