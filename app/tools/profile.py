"""Tool 3, `airport_profile`: every measure with its national grade, for 1 to 5 airports.

What it is:   The airport_profile tool: for each airport asked, every measure of the shared
              list with its national grade, the score, its two halves, the national rank,
              the flags, and a congestion block (the five crowding measures + strain_score).
Why we need:  Answers "compare congestion at LAX and SNA", "tell me about Nashville", "why is
              BTV ranked 3rd?" with the same numbers and rules as the ranking.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step10_rank_profile.py.
Uses:         app/measures.py (compute_measures, YEAR), app/scoring.py (score_airports),
              app/tools/base.py, app/tools/rank.py (grade_every_measure and the `about`
              texts), app/tools/resolver.py (load_airports); tables airports, route_traffic,
              airport_delays, enplanements (read through compute_measures and load_airports).
Main parts:   CONGESTION_MEASURES - the five crowding measures of decisions 7.18.
              ProfileSettings - the tool's setting: 1-5 airport names or codes.
              airport_profile(con, settings) - the tool; a ToolResult with one entry per airport.
Design:       docs/tools.md "3. airport_profile" and congestion; docs/decisions.md 7.18;
              docs/implementation-plan.md P29, P34, P35.
"""

from pydantic import BaseModel, Field

from app.measures import YEAR, compute_measures
from app.scoring import score_airports
from app.tools.base import AirportList, ToolResult, register
from app.tools.rank import (
    DEFAULT_MIN_ENPLANEMENTS,
    about_assumptions,
    about_period,
    grade_every_measure,
    size_filter_text,
)
from app.tools.resolver import load_airports

CONGESTION_MEASURES = ("departures_per_runway", "nas_delay_per_flight", "taxi_out_min", "late_share", "cancel_rate")


class ProfileSettings(BaseModel):
    airports: AirportList = Field(description="1 to 5 airport codes or names, e.g. ['LAX', 'Santa Ana'].")


@register(
    "airport_profile",
    "Show every measure of the shared list, each with its national grade (0-100), for 1 to 5 airports "
    "side by side (codes or names), plus the final score, its demand and strain halves, the national rank "
    "and the flags. Each airport also has a `congestion` block: departures_per_runway, "
    "nas_delay_per_flight, taxi_out_min, late_share, cancel_rate with their grades, and strain_score as "
    "the summary. Grades and scores use airports with 100,000+ boardings in 2025 and the default weights; "
    "a smaller airport keeps its values but has no grades or score.",
    ProfileSettings,
)
def airport_profile(con, settings):
    min_enpl = DEFAULT_MIN_ENPLANEMENTS
    measures = compute_measures(con)
    scored = {a.iata: a for a in score_airports(measures, min_enplanements=min_enpl)}
    grades = grade_every_measure(measures, min_enpl)
    info = {match.iata: match for match, _lat, _lon in load_airports(con)}
    names = list(next(iter(measures.values()), {}))

    codes = list(dict.fromkeys(settings.airports))  # in the order asked, a repeated code once
    entries, missing = [], []
    for code in codes:
        raw = measures.get(code, {})
        cells = {name: {"value": raw.get(name), "grade": grades[name].get(code)} for name in names}
        airport = scored.get(code)
        if airport is None:
            missing.append(
                f"{code} has fewer than {min_enpl:,} boardings in {YEAR}, so it has no grades or score."
            )
        entries.append(
            {
                **info[code]._asdict(),
                "measures": cells,
                "final_score": airport.final_score if airport else None,
                "demand_score": airport.demand_score if airport else None,
                "strain_score": airport.strain_score if airport else None,
                "national_rank": airport.rank if airport else None,
                "flags": list(airport.flags) if airport else [],
                "missing": list(airport.missing) if airport else [],
                "congestion": {
                    "measures": {name: cells[name] for name in CONGESTION_MEASURES},
                    "strain_score": airport.strain_score if airport else None,
                },
            }
        )

    about = {
        "data_period": about_period(),
        "filters": [size_filter_text(min_enpl), f"airports: {', '.join(codes)}"],
        "missing": missing,
        "assumptions": about_assumptions(min_enpl, names),
    }
    return ToolResult(data={"airports": entries}, about=about)
