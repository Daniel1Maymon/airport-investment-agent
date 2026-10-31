"""Tool 2, `rank_airports`: rank airports by the score or by any measure of the shared list.

What it is:   The rank_airports tool: grades every airport against the national pool, then
              keeps the airports of the asked states, region or size, and lists them sorted
              by the score or by one measure. Also holds the helpers airport_profile uses
              (national grades for every measure, and the `about` texts).
Why we need:  Answers "which airports are strong candidates?", "10 most delayed airports",
              "rank again with growth at 60%". Python does every number; the AI explains.
Used by:      app/tools/__init__.py (the import registers the tool); app/tools/profile.py
              (grade_every_measure, about_period, about_assumptions, size_filter_text,
              DEFAULT_MIN_ENPLANEMENTS). The AI calls the tool through run_tool.
              tests: test_step10_rank_profile.py.
Uses:         app/measures.py (compute_measures, YEAR), app/scoring.py (score_airports,
              percentile_grades, DEFAULT_WEIGHTS, WEIGHT_MEASURES), app/tools/base.py,
              app/tools/find.py (Region, Size), app/tools/resolver.py (load_airports,
              resolve_region, SIZE_YEAR); tables airports, route_traffic, airport_delays,
              enplanements (read through compute_measures and load_airports).
Main parts:   DEFAULT_MIN_ENPLANEMENTS, SCORE_SORTS - fixed defaults and the three scores.
              WEIGHT_KEYS, Weights, Order, MinEnplanements - setting types of this tool.
              RankSettings - the tool's settings; weights are checked here (P30).
              grade_every_measure(measures, min_enplanements) - national grade of every
                measure (P29): measure -> {code: grade}.
              size_filter_text, about_period, about_assumptions - the `about` texts (P35).
              rank_airports(con, settings) - the tool; a ToolResult with up to 25 airports.
Design:       docs/tools.md "2. rank_airports"; docs/scoring.md;
              docs/implementation-plan.md P29-P33, P35.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.measures import YEAR, compute_measures
from app.scoring import DEFAULT_WEIGHTS, WEIGHT_MEASURES, percentile_grades, score_airports
from app.tools.base import Allowed, MeasureName, SettingsError, StateList, TopN, ToolResult, register
from app.tools.find import Region, Size
from app.tools.resolver import SIZE_YEAR, load_airports, resolve_region

DEFAULT_MIN_ENPLANEMENTS = 100_000
SCORE_SORTS = ("score", "demand_score", "strain_score")
WEIGHT_KEYS = list(DEFAULT_WEIGHTS)  # D1, D2, S1, S2, S3, S4

Weights = Annotated[dict[str, float], Allowed(WEIGHT_KEYS)]
Order = Annotated[Literal["highest_first", "lowest_first"], Allowed(["highest_first", "lowest_first"])]
MinEnplanements = Annotated[int, Field(ge=0, le=10_000_000), Allowed([0, 10_000_000])]

# `about` texts (P35). The limits are docs/tools.md "Known limits", without markdown marks.
DATA_PERIOD = "2025 (growth from 2019 and 2024; delays Jan–Dec 2025)"
NOTE_LONG_HAUL = "Long-haul = 3,000+ miles, passenger flights only."
NOTE_TARGET_85 = "missing_seats_pct uses an 85% target load factor (the cautious end of the 80–85% range)."
NOTE_DELAYS = (
    "Delay measures (S2, S3, late_share, cancel_rate) cover only domestic flights by the larger US airlines; "
    "small airports may have none."
)
NOTE_TAXI = (
    "taxi_out_min is the total time from gate to takeoff, so part of it is the distance to the runway, "
    "not the queue. Big airports score higher partly for that reason."
)
NOTE_AIRLINE = (
    "top_airline_share uses the airline that operates the flight. A regional airline flying for a major "
    "(e.g. SkyWest for United) counts separately, so dependence on a major can be understated."
)
DELAY_NAMES = ("nas_delay_per_flight", "taxi_out_min", "late_share", "cancel_rate")


class RankSettings(BaseModel):
    states: StateList | None = Field(None, description="Two-letter US state codes, e.g. ['MA', 'NH'].")
    region: Region | None = Field(None, description="A US Census region or division, e.g. 'New England'.")
    size: Size | None = Field(None, description="FAA hub size in 2025.")
    sort_by: MeasureName = Field("score", description="The measure to sort by ('score' if not given).")
    order: Order = Field("highest_first", description="'highest_first' (default) or 'lowest_first'.")
    weights: Weights | None = Field(
        None,
        description="Only with sort_by 'score': weights for D1 growth_long, D2 growth_short, S1 load_factor, "
        "S2 nas_delay_per_flight, S3 taxi_out_min, S4 departures_per_runway. Numbers >= 0 that total 100; "
        "keys left out count as 0. Default: D1 20, D2 20, S1 20, S2 15, S3 10, S4 15.",
    )
    min_enplanements: MinEnplanements = Field(
        DEFAULT_MIN_ENPLANEMENTS, description="Size filter: minimum 2025 boardings (default 100,000)."
    )
    top_n: TopN = Field(10, description="How many airports to list (1-25, default 10).")

    @model_validator(mode="after")
    def _check_weights(self):
        if self.weights is None:
            return self
        weights = self.weights
        if set(weights) - set(WEIGHT_KEYS):
            raise SettingsError("Unknown weight key. Use only D1, D2, S1, S2, S3, S4.", WEIGHT_KEYS)
        if any(w < 0 for w in weights.values()):
            raise SettingsError("Weights can't be negative.", WEIGHT_KEYS)
        if sum(weights.values()) != 100:
            raise SettingsError(f"Weights must total 100, not {sum(weights.values()):g}.", WEIGHT_KEYS)
        if self.sort_by != "score":
            raise SettingsError("'weights' can only be used with sort_by 'score'.", ["score"])
        return self


def grade_every_measure(measures, min_enplanements):
    """National grade of every measure (P29): {measure: {code: grade}}.

    The pool is the airports with enplanements >= min_enplanements and a value.
    """
    pool = {
        code: row
        for code, row in measures.items()
        if row.get("enplanements") is not None and row["enplanements"] >= min_enplanements
    }
    names = next(iter(measures.values()), {}).keys()
    return {name: percentile_grades({code: row.get(name) for code, row in pool.items()}) for name in names}


def size_filter_text(min_enplanements):
    return f"airports with {min_enplanements:,}+ enplanements in {YEAR}"


def about_period():
    return DATA_PERIOD


def about_assumptions(min_enplanements, shown):
    """The fixed notes (P35) for the measures `shown`."""
    notes = [
        f"Grades are national: compared with all US airports with {min_enplanements:,}+ enplanements "
        f"in {YEAR}, before any region filter."
    ]
    if "long_haul_share" in shown:
        notes.append(NOTE_LONG_HAUL)
    if "missing_seats_pct" in shown:
        notes.append(NOTE_TARGET_85)
    if any(name in shown for name in DELAY_NAMES):
        notes.append(NOTE_DELAYS)
    if "taxi_out_min" in shown:
        notes.append(NOTE_TAXI)
    if "top_airline_share" in shown:
        notes.append(NOTE_AIRLINE)
    return notes


@register(
    "rank_airports",
    "Rank US airports by the renovation score or by any measure of the shared list (`sort_by`, "
    "default 'score'). Filter by states, a US Census region or division, or FAA hub size; grades and "
    "national_rank are always national (worked out before the filters). Only airports with at least "
    "`min_enplanements` boardings in 2025 (default 100,000) are ranked. `order` is 'highest_first' "
    "(default) or 'lowest_first'. `weights` changes the score's weights (only with sort_by 'score'; "
    "D1..S4, total 100). Returns at most `top_n` airports (default 10, at most 25), each with the value, "
    "its national grade and national rank; for 'score' also the six measure grades and the flags.",
    RankSettings,
)
def rank_airports(con, settings):
    sort_by = settings.sort_by
    min_enpl = settings.min_enplanements
    measures = compute_measures(con)
    scored = score_airports(measures, weights=settings.weights, min_enplanements=min_enpl)
    by_code = {a.iata: a for a in scored}
    info = {match.iata: match for match, _lat, _lon in load_airports(con)}

    # Value of every pooled airport, and its national rank (from the highest; ties A->Z; None last).
    if sort_by in SCORE_SORTS:
        field = "final_score" if sort_by == "score" else sort_by
        values = {a.iata: getattr(a, field) for a in scored}
        grades = {}
    else:
        values = {a.iata: a.raw.get(sort_by) for a in scored}
        grades = grade_every_measure(measures, min_enpl)[sort_by]
    if sort_by == "score":
        national = {a.iata: a.rank for a in scored}
    else:
        ranked = sorted((c for c in values if values[c] is not None), key=lambda c: (-values[c], c))
        national = {code: rank for rank, code in enumerate(ranked, start=1)}

    # Filters after grading (P32).
    codes = [a.iata for a in scored]
    filters = [size_filter_text(min_enpl)]
    missing = []
    if settings.states is not None:
        codes = [c for c in codes if info[c].state in settings.states]
        filters.append(f"states: {', '.join(settings.states)}")
    if settings.region is not None:
        states = resolve_region(settings.region)
        codes = [c for c in codes if info[c].state in states]
        filters.append(f"region: {settings.region} ({', '.join(states)})")
    if settings.size is not None:
        no_size = sum(1 for c in codes if info[c].size is None)
        codes = [c for c in codes if info[c].size == settings.size]
        filters.append(f"size: {settings.size}")
        if no_size:
            missing.append(f"{no_size} airport(s) have no FAA hub size for {SIZE_YEAR} and were left out.")

    # No value: left out, except a None score, which is listed last (P32).
    if sort_by != "score":
        no_value = sum(1 for c in codes if values[c] is None)
        codes = [c for c in codes if values[c] is not None]
        if no_value:
            missing.append(f"{no_value} airport(s) have no value for {sort_by} and are not listed.")
    sign = 1 if settings.order == "lowest_first" else -1
    codes.sort(key=lambda c: (values[c] is None, sign * (values[c] or 0), c))

    matched = len(codes)
    rows = []
    for code in codes[: settings.top_n]:
        match = info[code]
        row = {
            **match._asdict(),
            "national_rank": national[code],
            "value": values[code],
            "grade": grades.get(code),
        }
        if sort_by == "score":
            airport = by_code[code]
            row.update(
                demand_score=airport.demand_score,
                strain_score=airport.strain_score,
                grades=dict(airport.grades),
                flags=list(airport.flags),
                missing=list(airport.missing),
            )
        rows.append(row)

    if not rows:
        missing.append("No airport matches these filters.")
    if matched > settings.top_n:
        missing.append(f"{matched} airports matched; only the first {settings.top_n} are shown.")

    shown = list(WEIGHT_MEASURES.values()) if sort_by in SCORE_SORTS else [sort_by]
    assumptions = about_assumptions(min_enpl, shown)
    if sort_by == "score":
        in_force = {k: (settings.weights or DEFAULT_WEIGHTS).get(k, 0) for k in WEIGHT_KEYS}
        assumptions.append("Weights: " + ", ".join(f"{k} {w:g}" for k, w in in_force.items()) + ".")

    about = {"data_period": about_period(), "filters": filters, "missing": missing, "assumptions": assumptions}
    return ToolResult(data={"sort_by": sort_by, "order": settings.order, "airports": rows}, about=about)
