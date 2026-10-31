"""Tool 1, `find_airports`: find airports in our list by name, place, size or distance.

What it is:   The find_airports tool: filters our airport list by name, city or code, by
              states, by Census region, by FAA hub size, or by distance from an airport.
Why we need:  People name places, not codes ("LA", "New England"). This lists the matching
              airports, so the AI picks codes from our list and never guesses one.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it
              through run_tool. app/tools/rank.py (the Region and Size setting types),
              app/tools/trend.py (Region).
              tests: test_step09_resolver.py, test_step10_rank_profile.py.
Uses:         app/tools/base.py, app/tools/resolver.py, app/refusals.py; the tables
              airports and enplanements (2025 hub size), read through the resolver.
Main parts:   MAX_ROWS, DEFAULT_MILES, EARTH_RADIUS_MI, FILTERS, SIZES - fixed limits
                and choices.
              Region, Size, Miles - setting types of this tool.
              FindSettings - the tool's settings; at least one filter must be given.
              find_airports(con, settings) - the tool; a ToolResult with up to 25 airports.
Design:       docs/tools.md "1. find_airports"; docs/agent.md "Name resolver";
              docs/implementation-plan.md P26, P27.
"""

from math import asin, cos, radians, sin, sqrt
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.refusals import REFUSALS
from app.tools.base import AirportCode, Allowed, SettingsError, StateList, ToolResult, register
from app.tools.resolver import REGIONS, SIZE_YEAR, load_airports, resolve_airport, resolve_region

MAX_ROWS = 25
DEFAULT_MILES = 50
EARTH_RADIUS_MI = 3958.8
FILTERS = ("text", "states", "region", "size", "near_airport")
SIZES = ("large", "medium", "small", "non-hub")


def _region_name(value):
    """Accept a region in any case ("new england" -> "New England")."""
    if isinstance(value, str):
        for region in REGIONS:
            if region.lower() == value.strip().lower():
                return region
    return value


Region = Annotated[Literal[tuple(REGIONS)], BeforeValidator(_region_name), Allowed(sorted(REGIONS))]
Size = Annotated[Literal[SIZES], Allowed(list(SIZES))]
Miles = Annotated[float, Field(ge=1, le=500), Allowed([1, 500])]


class FindSettings(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=100)] | None = Field(
        None, description="An airport name, city or code, e.g. 'Santa Ana', 'LA', 'BOS'."
    )
    states: StateList | None = Field(None, description="Two-letter US state codes, e.g. ['MA', 'NH'].")
    region: Region | None = Field(None, description="A US Census region or division, e.g. 'New England'.")
    size: Size | None = Field(None, description="FAA hub size in 2025.")
    near_airport: AirportCode | None = Field(None, description="An airport code or name to search around.")
    within_miles: Miles | None = Field(
        None, description=f"Distance from near_airport in miles (1-500; {DEFAULT_MILES} if not given)."
    )

    @model_validator(mode="after")
    def _check_together(self):
        if all(getattr(self, name) is None for name in FILTERS):
            raise SettingsError("Give at least one of these settings.", FILTERS)
        if self.within_miles is not None and self.near_airport is None:
            raise SettingsError("'within_miles' needs 'near_airport' (the airport to measure from).", ["near_airport"])
        return self


def _miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles (haversine formula)."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return EARTH_RADIUS_MI * 2 * asin(sqrt(a))


@register(
    "find_airports",
    "Find US airports in our list. Filter by name, city or code (`text`), by states, by a US Census "
    "region or division (`region`, e.g. 'New England', 'Pacific', 'South'), by FAA hub size, or by "
    f"distance from another airport (`near_airport` + `within_miles`, {DEFAULT_MILES} miles if not given). "
    "Give at least one filter; all given filters must match. Returns code, name, city, state and size "
    f"(at most {MAX_ROWS} rows). Use it for unclear names ('LA') and places; when several airports match, "
    "pick one from the list, never guess a code.",
    FindSettings,
)
def find_airports(con, settings):
    all_rows = load_airports(con)
    rows = all_rows
    filters, missing = [], []

    if settings.text is not None:
        codes = {m.iata for m in resolve_airport(con, settings.text)}
        rows = [r for r in rows if r[0].iata in codes]
        filters.append(f"name, city or code: {settings.text}")
    if settings.states is not None:
        rows = [r for r in rows if r[0].state in settings.states]
        filters.append(f"states: {', '.join(settings.states)}")
    if settings.region is not None:
        states = resolve_region(settings.region)
        rows = [r for r in rows if r[0].state in states]
        filters.append(f"region: {settings.region} ({', '.join(states)})")
    if settings.size is not None:
        no_size = sum(1 for r in rows if r[0].size is None)
        rows = [r for r in rows if r[0].size == settings.size]
        filters.append(f"size: {settings.size}")
        if no_size:
            missing.append(f"{no_size} airport(s) have no FAA hub size for {SIZE_YEAR} and were left out.")

    distances = {}
    if settings.near_airport is not None:
        miles = settings.within_miles if settings.within_miles is not None else DEFAULT_MILES
        [center] = [r for r in all_rows if r[0].iata == settings.near_airport]
        _, lat0, lon0 = center
        kept = []
        for match, lat, lon in rows:
            if match.iata == settings.near_airport or None in (lat, lon, lat0, lon0):
                continue
            distance = _miles(lat0, lon0, lat, lon)
            if distance <= miles:
                distances[match.iata] = round(distance, 1)
                kept.append((match, lat, lon))
        rows = sorted(kept, key=lambda r: (distances[r[0].iata], r[0].iata))
        filters.append(f"within {miles:g} miles of {settings.near_airport}")

    matched = len(rows)
    airports = []
    for match, _lat, _lon in rows[:MAX_ROWS]:
        row = match._asdict()
        if settings.near_airport is not None:
            row["distance_mi"] = distances[match.iata]
        airports.append(row)

    if not airports:
        missing.append(REFUSALS["airport_not_found"])
    if matched > MAX_ROWS:
        missing.append(f"{matched} airports matched; only the first {MAX_ROWS} are shown.")

    about = {
        "data_period": f"FAA hub size: {SIZE_YEAR}",
        "filters": filters,
        "missing": missing,
        "assumptions": ["Distances are great-circle (straight-line) miles."] if settings.near_airport else [],
    }
    return ToolResult(data={"airports": airports}, about=about)
