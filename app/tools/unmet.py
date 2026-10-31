"""Tool 7, `unmet_demand`: missing seats at 1 to 5 airports, as a range, with the "why".

What it is:   The unmet_demand tool: for each airport asked, the 2025 missing seats and
              missing flights at an 80% and an 85% target load factor (plus an optional
              custom target), and the reasons next to them: load factor by month, the
              split of delay minutes by cause, and the runway and taxi-out grades.
Why we need:  Answers "what is the unmet flight demand at SFO, and why?" with an amount,
              not a yes/no. The target is an assumption, so the answer is always a range.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step12_unmet_info_live.py, test_fix_answer_quality.py.
Uses:         app/measures.py (compute_measures, monthly_missing_seats, YEAR),
              app/tools/base.py (grade_level), app/tools/rank.py (grade_every_measure,
              DEFAULT_MIN_ENPLANEMENTS, NOTE_DELAYS, NOTE_TAXI, about_assumptions),
              app/tools/resolver.py (load_airports); tables airports, route_traffic,
              airport_delays, enplanements.
Main parts:   TARGETS - the two fixed targets and their labels (80% high, 85% low).
              MONTH_NAMES, OVER_TARGET_MIN - month names and the "above the target" limit (P77).
              UnmetSettings - the tool's settings: 1-5 airports, optional target 0.70-0.95.
              annual_vs_target(load_factor, target, months) - the sentence that compares the
                year's load factor and the months with the target (P77).
              unmet_demand(con, settings) - the tool; a ToolResult with one entry per airport.
Design:       docs/tools.md "7. unmet_demand" and "Unmet demand: how it becomes an amount";
              docs/decisions.md 7.17; docs/implementation-plan.md P11, P29, P50-P52, P76, P77.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from app.measures import YEAR, compute_measures, monthly_missing_seats
from app.tools.base import Allowed, AirportList, ToolResult, grade_level, register
from app.tools.rank import DEFAULT_MIN_ENPLANEMENTS, NOTE_DELAYS, NOTE_TAXI, about_assumptions, grade_every_measure
from app.tools.resolver import load_airports

TARGETS = ((0.80, "high estimate"), (0.85, "low estimate"))
# Three-letter month names for the annual_vs_target sentence (P77); index 0 = January.
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# A month counts as above the target only when it misses more than this many seats. Without
# it, a month exactly at the target can show a tiny rounding leftover (about 1e-13 seats).
OVER_TARGET_MIN = 1e-9
CUSTOM_LABEL = "custom target"
CAUSES = ("nas", "weather", "carrier", "late_aircraft", "security")

TargetLoadFactor = Annotated[float, Field(ge=0.70, le=0.95), Allowed([0.7, 0.95])]

DATA_PERIOD = "2025 by month (departing passenger flights; delays Jan–Dec 2025)"
NOTES = (
    "This is an estimate of missing seats, not a count of people turned away.",
    "It counts only people who would have flown at today's prices.",
    "Monthly averages hide daily peaks, so the true peak shortage is likely larger.",
    "Range: an 80% target load factor gives the high estimate, 85% the low estimate.",
)

# Delay minutes by cause, 2025 arriving flights (where BTS records causes).
_CAUSES_SQL = """
SELECT COUNT(*),
       SUM(nas_delay_min)::DOUBLE, SUM(weather_delay_min)::DOUBLE, SUM(carrier_delay_min)::DOUBLE,
       SUM(late_aircraft_delay_min)::DOUBLE, SUM(security_delay_min)::DOUBLE
FROM airport_delays
WHERE year = ? AND direction = 'arr' AND iata = ?
"""


class UnmetSettings(BaseModel):
    airports: AirportList = Field(description="1 to 5 airport codes or names, e.g. ['SFO'].")
    target_load_factor: TargetLoadFactor | None = Field(
        None,
        description="Optional extra target load factor as a fraction, 0.70-0.95 (e.g. 0.75). "
        "The 0.80 and 0.85 estimates are always given.",
    )


def annual_vs_target(load_factor, target, months):
    """The sentence that compares the year with the target (P77), written by Python so the
    AI copies it instead of working out which months are above the target.

    load_factor: the airport's 2025 load factor (a fraction), or None when not known.
    target:      the target load factor (a fraction), e.g. 0.85.
    months:      the months_over_target list, in month order.
    """
    if load_factor is None:
        return "The 2025 load factor is not known."
    # Which side of the target the whole year is.
    if abs(load_factor - target) <= 1e-9:
        side = "equal to"
    elif load_factor > target:
        side = "above"
    else:
        side = "below"
    start = f"The 2025 load factor ({load_factor:.1%}) is {side} the {target:.0%} target; "
    # The months above the target, by name.
    names = ", ".join(MONTH_NAMES[m["month"] - 1] for m in months)
    if not months:
        return start + "no month is above it."
    if len(months) == 1:
        return start + f"1 month is above it: {names}."
    return start + f"{len(months)} months are above it: {names}."


def _estimate(con, code, target, label, load_factor):
    """One estimate at one target.

    load_factor: the airport's 2025 load factor, used in the annual_vs_target sentence.
    """
    result = monthly_missing_seats(con, code, target)
    seats = result["seats_offered"]
    # The months that miss seats at this target, in month order (P77).
    months = [
        {"month": month, "load_factor": m["load_factor"], "missing_seats": m["missing_seats"]}
        for month, m in sorted(result["by_month"].items())
        if m["missing_seats"] > OVER_TARGET_MIN
    ]
    return {
        "target": target,
        "label": label,
        "missing_seats": result["missing_seats"],
        "missing_flights": result["missing_flights"],
        "missing_seats_pct": result["missing_seats"] / seats if seats else None,
        "months_over_target": months,
        "annual_vs_target": annual_vs_target(load_factor, target, months),
    }


def _delay_causes(con, code):
    """{cause: {minutes, share}} from 2025 arrival rows, or None when there are no rows."""
    count, *minutes = con.execute(_CAUSES_SQL, [YEAR, code]).fetchone()
    if not count:
        return None
    minutes = [m or 0.0 for m in minutes]
    total = sum(minutes)
    return {
        cause: {"minutes": m, "share": m / total if total else None} for cause, m in zip(CAUSES, minutes)
    }


@register(
    "unmet_demand",
    "Estimate unmet flight demand in 2025 for 1 to 5 airports (codes or names): the seats and flights "
    "missing to bring each month's planes down to a target load factor. Always gives a range: 80% target "
    "(high estimate) and 85% target (low estimate); `target_load_factor` (0.70-0.95) adds a third. Also "
    "gives the why: load factor by month, delay minutes by cause, and the national grades (with level "
    "words) of departures_per_runway and taxi_out_min. Each estimate lists months_over_target and an "
    "annual_vs_target sentence that compares the year's load factor with the target.",
    UnmetSettings,
)
def unmet_demand(con, settings):
    min_enpl = DEFAULT_MIN_ENPLANEMENTS
    measures = compute_measures(con)
    grades = grade_every_measure(measures, min_enpl)
    info = {match.iata: match for match, _lat, _lon in load_airports(con)}

    targets = list(TARGETS)
    custom = settings.target_load_factor
    if custom is not None and all(abs(custom - t) > 1e-9 for t, _label in TARGETS):
        targets.append((custom, CUSTOM_LABEL))

    codes = list(dict.fromkeys(settings.airports))  # in the order asked, a repeated code once
    entries, missing = [], []
    for code in codes:
        raw = measures.get(code, {})
        match = info[code]
        monthly = monthly_missing_seats(con, code, TARGETS[0][0])["by_month"]
        if monthly:
            year_lf = raw.get("load_factor")
            estimates = [_estimate(con, code, target, label, year_lf) for target, label in targets]
        else:
            estimates = []
            missing.append(f"{code} has no passenger flights in {YEAR}, so there is no estimate.")
        causes = _delay_causes(con, code)
        if causes is None:
            missing.append(f"{code} has no delay data for {YEAR}, so delay causes are not shown.")
        entries.append(
            {
                "iata": code,
                "name": match.name,
                "city": match.city,
                "state": match.state,
                "passengers": raw.get("passengers"),
                "seats_offered": raw.get("seats"),
                "load_factor": raw.get("load_factor"),
                "estimates": estimates,
                "why": {
                    "by_month": [
                        {
                            "month": month,
                            "passengers": m["passengers"],
                            "seats": m["seats"],
                            "load_factor": m["load_factor"],
                        }
                        for month, m in monthly.items()
                    ],
                    "delay_causes": causes,
                    # National grade with its level word (P76).
                    "runway_and_taxi": {
                        name: {
                            "value": raw.get(name),
                            "grade": grades.get(name, {}).get(code),
                            "level": grade_level(grades.get(name, {}).get(code)),
                        }
                        for name in ("departures_per_runway", "taxi_out_min")
                    },
                },
            }
        )

    about = {
        "data_period": DATA_PERIOD,
        "filters": [f"airports: {', '.join(codes)}"],
        "missing": missing,
        "assumptions": [*NOTES, *about_assumptions(min_enpl, []), NOTE_DELAYS, NOTE_TAXI],
    }
    return ToolResult(data={"airports": entries}, about=about)
