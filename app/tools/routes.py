"""Tool 5, `route_mix`: split one airport's departures into groups, with their shares.

What it is:   The route_mix tool: one airport's departures in one year, split by destination,
              country, airline, distance band or aircraft size, each group with its
              departures, seats, passengers and their shares, plus the long-haul,
              international and cargo shares.
Why we need:  Answers "what % of flights out of Anchorage are long-haul?", "how dependent is
              Charlotte on one airline?". Python does every number.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step11_trend_routes_delays.py.
Uses:         app/measures.py (route_groups, route_totals, DISTANCE_BANDS, AIRCRAFT_SIZES,
              TRAFFIC_YEARS), app/tools/base.py, app/tools/rank.py (NOTE_AIRLINE); table
              route_traffic (read through those functions).
Main parts:   GROUP_BY, NATURAL_ORDER - the groupings, and the fixed order of bands and sizes.
              GroupBy, LongHaulMiles, Year - setting types of this tool.
              RouteSettings - the tool's settings.
              route_mix(con, settings) - the tool; a ToolResult with up to top_n groups
                (+ one "other" row).
Design:       docs/tools.md "5. route_mix"; docs/implementation-plan.md P36, P38, P39, P41.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.measures import AIRCRAFT_SIZES, DISTANCE_BANDS, TRAFFIC_YEARS, route_groups, route_totals
from app.tools.base import AirportCode, Allowed, TopN, ToolResult, register
from app.tools.rank import NOTE_AIRLINE

GROUP_BY = ("destination", "country", "airline", "distance_band", "aircraft_size")
NATURAL_ORDER = {"distance_band": DISTANCE_BANDS, "aircraft_size": AIRCRAFT_SIZES}

GroupBy = Annotated[Literal[GROUP_BY], Allowed(list(GROUP_BY))]
LongHaulMiles = Annotated[int, Field(ge=500, le=6000), Allowed([500, 6000])]
Year = Annotated[Literal[TRAFFIC_YEARS], Allowed(list(TRAFFIC_YEARS))]


class RouteSettings(BaseModel):
    airport: AirportCode = Field(description="One airport code or name, e.g. 'ANC' or 'Anchorage'.")
    group_by: GroupBy = Field(
        "destination",
        description="destination (default), country, airline, distance_band (under 500, 500-999, "
        "1,000-1,999, 2,000-2,999, 3,000+ miles) or aircraft_size (seats per flight: regional under "
        "100, single-aisle 100-229, wide-body 230+, cargo).",
    )
    passengers_only: bool = Field(True, description="true (default): passenger flights only; false: cargo too.")
    long_haul_miles: LongHaulMiles = Field(3000, description="Long-haul distance in miles (500-6000, default 3000).")
    year: Year = Field(2025, description="2019, 2024 or 2025 (default).")
    top_n: TopN = Field(10, description="How many groups to list (1-25, default 10); the rest go in 'other'.")


def _share(part, total):
    return part / total if total else None


@register(
    "route_mix",
    "Split one airport's departing flights in one year into groups (`group_by`: destination, country, "
    "airline, distance_band, aircraft_size). Each group has departures, seats, passengers and their "
    "shares (fractions of the airport's total). Also returns long_haul_share (departures of "
    "`long_haul_miles`+ miles, default 3000) and international_share over the departures in scope, and "
    "cargo_share (cargo / all departures). `passengers_only` (default true) leaves cargo flights out. "
    "At most `top_n` groups (default 10); the rest are added into one 'other' row.",
    RouteSettings,
)
def route_mix(con, settings):
    iata, year, group_by = settings.airport, settings.year, settings.group_by
    totals = route_totals(con, iata, year, settings.passengers_only, settings.long_haul_miles)
    groups = route_groups(con, iata, year, group_by, settings.passengers_only)

    if group_by in NATURAL_ORDER:
        order = NATURAL_ORDER[group_by]
        groups.sort(key=lambda g: order.index(g["group"]))
    else:
        groups.sort(key=lambda g: (-g["departures"], g["group"]))

    shown, rest = groups[: settings.top_n], groups[settings.top_n :]
    if rest:
        shown.append(
            {
                "group": "other",
                "groups": len(rest),
                **{k: sum(g[k] for g in rest) for k in ("departures", "seats", "passengers")},
            }
        )

    rows = []
    for g in shown:
        row = {"group": g["group"]}
        if group_by == "airline" and g["group"] != "other":
            row["airline_name"] = g["carrier_name"]
        if "groups" in g:
            row["groups"] = g["groups"]
        for k in ("departures", "seats", "passengers"):
            row[k] = g[k]
            row[f"{k}_share"] = _share(g[k], totals[k])
        rows.append(row)

    miles = settings.long_haul_miles
    scope = "passenger flights only" if settings.passengers_only else "all departures (cargo included)"
    # With the default 3,000 miles and passenger flights this is exactly NOTE_LONG_HAUL.
    assumptions = [f"Long-haul = {miles:,}+ miles, {scope}."]
    assumptions.append("Shares are fractions of the airport's departures, seats and passengers in scope.")
    if group_by == "airline":
        assumptions.append(NOTE_AIRLINE)

    missing = [] if totals["departures"] else [f"No departures from {iata} in {year}."]
    filters = [f"airport: {iata}", "passenger flights only" if settings.passengers_only else "passenger and cargo flights"]

    data = {
        "airport": iata,
        "year": year,
        "group_by": group_by,
        "passengers_only": settings.passengers_only,
        "totals": {k: totals[k] for k in ("departures", "seats", "passengers")},
        "long_haul_share": totals["long_haul_share"],
        "international_share": totals["international_share"],
        "cargo_share": totals["cargo_share"],
        "groups": rows,
    }
    about = {"data_period": str(year), "filters": filters, "missing": missing, "assumptions": assumptions}
    return ToolResult(data=data, about=about)
