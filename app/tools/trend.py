"""Tool 4, `traffic_trend`: one measure over time for 1 to 5 airports, or an area total.

What it is:   The traffic_trend tool: one measure (passengers, departures, seats,
              load_factor, enplanements, or a delay measure) by year or by month, for each
              airport asked, or added up over every airport of ours in states or a region.
Why we need:  Answers "has Denver recovered since 2019?", "which months are busiest at
              Orlando?", "how did New England grow?". Python does every number.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step11_trend_routes_delays.py.
Uses:         app/measures.py (traffic_by_period, enplanements_by_year, delays_by_period,
              TRAFFIC_YEARS, ENPLANEMENT_YEARS), app/tools/base.py, app/tools/find.py
              (Region), app/tools/rank.py (NOTE_DELAYS, NOTE_TAXI, DELAY_NAMES),
              app/tools/resolver.py (load_airports, resolve_region); tables route_traffic,
              enplanements, airport_delays, airports (read through those functions).
Main parts:   TRAFFIC_MEASURES, TREND_MEASURES - the 9 measures this tool shows.
              TrendMeasure, By - setting types of this tool.
              TrendSettings - the tool's settings; airports or an area, not both (P37).
              traffic_trend(con, settings) - the tool; a ToolResult with one series per
                airport, or one for the area.
Design:       docs/tools.md "4. traffic_trend"; docs/implementation-plan.md P36, P37, P41.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.measures import ENPLANEMENT_YEARS, TRAFFIC_YEARS, delays_by_period, enplanements_by_year, traffic_by_period
from app.tools.base import AirportList, Allowed, SettingsError, StateList, ToolResult, register
from app.tools.find import Region
from app.tools.rank import DELAY_NAMES, NOTE_COVID, NOTE_DELAYS, NOTE_TAXI
from app.tools.resolver import load_airports, resolve_region

TRAFFIC_MEASURES = ("passengers", "departures", "seats", "load_factor")
TREND_MEASURES = (*TRAFFIC_MEASURES, "enplanements", *DELAY_NAMES)
AREA_SETTINGS = ["airports", "states", "region"]

TrendMeasure = Annotated[Literal[TREND_MEASURES], Allowed(list(TREND_MEASURES))]
By = Annotated[Literal["year", "month"], Allowed(["year", "month"])]


class TrendSettings(BaseModel):
    measure: TrendMeasure = Field(
        description="passengers, departures, seats, load_factor (2019, 2024, 2025, by year or month); "
        "enplanements (2023-2025, by year only); nas_delay_per_flight, taxi_out_min, late_share, "
        "cancel_rate (2025 only, by year or month)."
    )
    by: By = Field("year", description="'year' (default) or 'month'.")
    airports: AirportList | None = Field(None, description="1 to 5 airport codes or names: one series each.")
    states: StateList | None = Field(None, description="Two-letter US state codes: one total for the area.")
    region: Region | None = Field(None, description="A US Census region or division: one total for the area.")

    @model_validator(mode="after")
    def _check_together(self):
        area = self.states is not None or self.region is not None
        if (self.airports is not None) == area:
            raise SettingsError(
                "Give either 'airports' or an area ('states' and/or 'region'), not both and not neither.",
                AREA_SETTINGS,
            )
        if self.measure == "enplanements" and self.by == "month":
            raise SettingsError("FAA counts boardings only per year, so enplanements can't be shown by month.", ["year"])
        return self


def _points(con, measure, codes, by):
    """The series points of `measure` added up over `codes` (P37)."""
    if measure == "enplanements":
        rows = enplanements_by_year(con, codes)
    elif measure in TRAFFIC_MEASURES:
        rows = traffic_by_period(con, codes, by)
    else:
        rows = delays_by_period(con, codes, by)
    points = []
    for row in rows:
        point = {"year": row["year"]}
        if by == "month":
            point["month"] = row["month"]
        point["value"] = row[measure]
        points.append(point)
    if by == "year" and points:
        first = points[0]["value"]
        for point in points:
            value = point["value"]
            point["change_from_first"] = None if not first or value is None else (value - first) / first
    return points


def _data_period(measure):
    if measure == "enplanements":
        return ", ".join(str(y) for y in ENPLANEMENT_YEARS)
    if measure in TRAFFIC_MEASURES:
        return ", ".join(str(y) for y in TRAFFIC_YEARS)
    return "2025 (Jan–Dec)"


@register(
    "traffic_trend",
    "One measure over time, by year (default) or by month, for 1 to 5 airports (codes or names, one "
    "series each), or the total of an area (`states` and/or `region`; every airport of ours there is "
    "added up). Measures: passengers, departures, seats, load_factor (passenger flights; 2019, 2024, "
    "2025); enplanements (FAA boardings; 2023-2025, by year only); nas_delay_per_flight, taxi_out_min, "
    "late_share, cancel_rate (2025 only). By year each point also has change_from_first (a fraction vs "
    "the first year). Give either airports or an area, not both.",
    TrendSettings,
)
def traffic_trend(con, settings):
    measure, by = settings.measure, settings.by
    filters, missing, assumptions = [], [], []

    if settings.airports is not None:
        codes = list(dict.fromkeys(settings.airports))  # in the order asked, a repeated code once
        series = [{"name": code, "airports": [code], "points": _points(con, measure, [code], by)} for code in codes]
        filters.append(f"airports: {', '.join(codes)}")
    else:
        rows = [match for match, _lat, _lon in load_airports(con)]
        labels = []
        if settings.region is not None:
            states = resolve_region(settings.region)
            rows = [m for m in rows if m.state in states]
            labels.append(settings.region)
            filters.append(f"region: {settings.region} ({', '.join(states)})")
        if settings.states is not None:
            rows = [m for m in rows if m.state in settings.states]
            labels.append(", ".join(settings.states))
            filters.append(f"states: {', '.join(settings.states)}")
        codes = sorted(m.iata for m in rows)
        name = " and ".join(labels)
        series = [{"name": name, "airports": codes, "points": _points(con, measure, codes, by) if codes else []}]
        filters.append(f"area total: {len(codes)} airport(s) added up ({', '.join(codes)}), no size filter")
        if not codes:
            missing.append("No airport of ours is in this area.")
        else:
            assumptions.append("Area totals add up the counts first; ratios are worked out from the added totals.")

    if measure in TRAFFIC_MEASURES:
        assumptions.append("passengers, departures, seats and load_factor count departing passenger flights only.")
        assumptions.append(NOTE_COVID)  # P114: these measures have 2019, 2024 and 2025
    if measure in DELAY_NAMES:
        assumptions.append(NOTE_DELAYS)
    if measure == "taxi_out_min":
        assumptions.append(NOTE_TAXI)
    for entry in series:
        if not entry["points"] and entry["airports"]:
            missing.append(f"{entry['name']} has no data for {measure}.")

    about = {"data_period": _data_period(measure), "filters": filters, "missing": missing, "assumptions": assumptions}
    return ToolResult(data={"measure": measure, "by": by, "series": series}, about=about)
