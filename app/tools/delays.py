"""Tool 6, `delay_causes`: delay minutes split by cause, for 1 to 5 airports.

What it is:   The delay_causes tool: for each airport asked, its 2025 delay minutes on
              arriving flights split into airline (carrier), weather, airspace/airport (NAS),
              late incoming plane and security, with minutes per flight and each cause's
              share; for the year or month by month.
Why we need:  Answers "why are flights at Newark late?", and the "why" part of unmet demand:
              is the airport itself (NAS) the cause, or the weather or the airlines?
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step11_trend_routes_delays.py.
Uses:         app/measures.py (delay_cause_minutes, DELAY_CAUSES, YEAR), app/tools/base.py,
              app/tools/rank.py (NOTE_DELAYS); table airport_delays (read through
              delay_cause_minutes).
Main parts:   NOTE_CAUSES - the fixed note on how causes are recorded (P41).
              DelaySettings - the tool's settings: 1-5 airports, by year or month.
              delay_causes(con, settings) - the tool; a ToolResult with one entry per airport.
Design:       docs/tools.md "6. delay_causes"; docs/implementation-plan.md P36, P40, P41.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.measures import DELAY_CAUSES, YEAR, delay_cause_minutes
from app.tools.base import AirportList, Allowed, ToolResult, register
from app.tools.rank import NOTE_DELAYS

NOTE_CAUSES = (
    "Causes are recorded on arriving flights 15+ minutes late; per-flight minutes divide by all arriving flights."
)

By = Annotated[Literal["year", "month"], Allowed(["year", "month"])]


class DelaySettings(BaseModel):
    airports: AirportList = Field(description="1 to 5 airport codes or names, e.g. ['EWR', 'Newark'].")
    by: By = Field("year", description="'year' (default, the 2025 total) or 'month'.")


def _empty_causes():
    return {cause: {"minutes": None, "per_flight": None, "share": None} for cause in DELAY_CAUSES}


@register(
    "delay_causes",
    "Delay minutes in 2025 on arriving flights for 1 to 5 airports (codes or names), split by cause: "
    "carrier (the airline), weather, nas (airspace and airport: the National Airspace System), "
    "late_aircraft (late incoming plane), security. Each cause has its minutes, minutes per arriving "
    "flight and share of all delay minutes. `by` 'month' also gives each month.",
    DelaySettings,
)
def delay_causes(con, settings):
    codes = list(dict.fromkeys(settings.airports))  # in the order asked, a repeated code once
    entries, missing = [], []
    for code in codes:
        year_rows = delay_cause_minutes(con, code, "year")
        if year_rows:
            entry = {"iata": code, **{k: v for k, v in year_rows[0].items() if k != "month"}}
        else:
            entry = {"iata": code, "arriving_flights": None, "total_delay_min": None, "causes": _empty_causes()}
            missing.append(f"{code} has no delay data for {YEAR}.")
        if settings.by == "month":
            entry["months"] = delay_cause_minutes(con, code, "month")
        entries.append(entry)

    # The coverage limit explains the missing data (P40); stated once, in `missing` when data is missing.
    assumptions = [NOTE_CAUSES]
    (missing if missing else assumptions).append(NOTE_DELAYS)
    about = {
        "data_period": "2025 (Jan–Dec)",
        "filters": [f"airports: {', '.join(codes)}", "arriving flights"],
        "missing": missing,
        "assumptions": assumptions,
    }
    return ToolResult(data={"airports": entries}, about=about)
