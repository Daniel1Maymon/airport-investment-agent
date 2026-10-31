"""Tool 7, `unmet_demand`: missing seats at 1 to 5 airports, as a range, with the "why".

What it is:   The unmet_demand tool: for each airport asked, the 2025 missing seats and
              missing flights at an 80% and an 85% target load factor (plus an optional
              custom target), and the reasons next to them: load factor by month, the
              split of delay minutes by cause, and the runway and taxi-out grades.
Why we need:  Answers "what is the unmet flight demand at SFO, and why?" with an amount,
              not a yes/no. The target is an assumption, so the answer is always a range.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step12_unmet_info_live.py.
Uses:         app/measures.py (compute_measures, monthly_missing_seats, YEAR),
              app/tools/base.py, app/tools/rank.py (grade_every_measure,
              DEFAULT_MIN_ENPLANEMENTS, NOTE_DELAYS, NOTE_TAXI, about_assumptions),
              app/tools/resolver.py (load_airports); tables airports, route_traffic,
              airport_delays, enplanements.
Main parts:   TARGETS - the two fixed targets and their labels (80% high, 85% low).
              UnmetSettings - the tool's settings: 1-5 airports, optional target 0.70-0.95.
              unmet_demand(con, settings) - the tool; a ToolResult with one entry per airport.
Design:       docs/tools.md "7. unmet_demand" and "Unmet demand: how it becomes an amount";
              docs/decisions.md 7.17; docs/implementation-plan.md P11, P29, P50-P52.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from app.measures import YEAR, compute_measures, monthly_missing_seats
from app.tools.base import Allowed, AirportList, ToolResult, register
from app.tools.rank import DEFAULT_MIN_ENPLANEMENTS, NOTE_DELAYS, NOTE_TAXI, about_assumptions, grade_every_measure
from app.tools.resolver import load_airports

TARGETS = ((0.80, "high estimate"), (0.85, "low estimate"))
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


def _estimate(con, code, target, label):
    result = monthly_missing_seats(con, code, target)
    seats = result["seats_offered"]
    return {
        "target": target,
        "label": label,
        "missing_seats": result["missing_seats"],
        "missing_flights": result["missing_flights"],
        "missing_seats_pct": result["missing_seats"] / seats if seats else None,
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
    "gives the why: load factor by month, delay minutes by cause, and the national grades of "
    "departures_per_runway and taxi_out_min.",
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
            estimates = [_estimate(con, code, target, label) for target, label in targets]
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
                    "runway_and_taxi": {
                        name: {"value": raw.get(name), "grade": grades.get(name, {}).get(code)}
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
