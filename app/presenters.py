"""Builds the tables and the "How I got this" steps of a reply, straight from the tool results.

What it is:   Functions that turn the tool events of one turn (what the AI asked for and
              what our tools returned) into what the chat page shows under the answer: tables
              of numbers and a short plain-words list of the steps taken. Also rebuilds a
              whole saved chat in that same shape, for a reload of the page.
Why we need:  The numbers in a table must be exactly what our tools worked out, never a number
              the AI wrote (it could be wrong or tricked). And the steps must show what really
              ran, not the AI's own story about it. So Python builds both, not the AI.
Used by:      app/api.py (the live reply of POST /chat and the reload of GET /chat/{id}).
              tests: test_step16_api.py.
Uses:         app/measures.py (MEASURES: the plain label and unit of each measure),
              app/refusals.py (REFUSALS: the fixed refusal messages).
              The tool results of app/tools/*.py (their `data` and `about` parts).
Main parts:   build_tables(tool_events) - list of {"title", "columns", "units", "rows", "about"}.
              build_steps(tool_events) - one plain-words line per tool event.
              rebuild_turns(steps) - a saved chat as a list of turns, for GET /chat/{id}.
              refusal_dict(cause) - a refusal as the page gets it: {"cause", "message"}.
Design:       docs/api.md; docs/decisions.md 7.19, 7.22; docs/implementation-plan.md P88-P91.

A "tool event" is one tool the AI asked for in this turn:
  {"id", "name", "args" (the settings the AI sent), "result" (what run_tool returned)}.

Rules for tables (P89): numbers are copied unchanged (not rounded, not turned into text;
None stays None). Each column has a unit ("share", "minutes", "rank", ...) so the chat page
knows how to show it, e.g. a share 0.823 as "82.3%". A tool that failed (its result has an
"error") or an unknown tool gives no table.

Example (question: "What % of flights out of Anchorage are long-haul?"):
  tool event:  route_mix with args {"airport": "ANC", "group_by": "distance_band"}
  steps:       ["Split departures into groups (airport: ANC; group by: distance_band)"]
  tables:      1. "ANC flight mix, 2025": Long-haul share 0.0276, ... (one row)
               2. "ANC departures by distance band, 2025": one row per distance band
"""

import json

from app.measures import MEASURES
from app.refusals import REFUSALS

# ---------------------------------------------------------------- steps (P88)

# The plain-words label of each tool, as shown in "How I got this".
STEP_LABELS = {
    "find_airports": "Looked up airports",
    "rank_airports": "Ranked airports",
    "airport_profile": "Looked up airport profiles",
    "traffic_trend": "Looked at traffic over time",
    "route_mix": "Split departures into groups",
    "delay_causes": "Looked at delay causes",
    "unmet_demand": "Estimated unmet demand",
    "data_info": "Checked which data we have",
    "live_status": "Checked today's FAA status",
}


def _setting_value(value):
    """One setting value in plain words: a list as "a, b", a dict as "key value", yes/no."""
    if isinstance(value, bool):  # checked first: in Python, True is also a number
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(_setting_value(v) for v in value)
    if isinstance(value, dict):
        return ", ".join(f"{k} {_setting_value(v)}" for k, v in value.items())
    return str(value)


def _settings_text(args):
    """The settings part of a step line: " (name: value; ...)", or "" when none were sent."""
    if not isinstance(args, dict):  # the AI sent text we could not read (P56)
        return " (settings could not be read)"
    if not args:
        return ""
    parts = [f"{name.replace('_', ' ')}: {_setting_value(value)}" for name, value in args.items()]
    return f" ({'; '.join(parts)})"


def build_steps(tool_events):
    """One plain-words line per tool event, in the order the tools ran (P88).

    Example: "Ranked airports (region: New England; top n: 5)".
    A tool that did not run ends with " – not run: <our own error text>".
    """
    lines = []
    for event in tool_events:
        name = event["name"]
        # An unknown name is still listed, so the page shows the AI asked for it.
        label = STEP_LABELS.get(name, f'Asked for an unknown tool "{name}"')
        line = label + _settings_text(event["args"])
        result = event["result"]
        if isinstance(result, dict) and "error" in result:
            line += f" – not run: {result['error']}"
        lines.append(line)
    return lines


# ---------------------------------------------------------------- tables (P89, P90)
#
# One function per tool below. Each gets the tool result's `data` and `about` and returns a
# list of tables (most give one; route_mix and unmet_demand give two).


def _table(title, columns, rows, about):
    """One table. `columns` is a list of (column name, unit) pairs."""
    return {
        "title": title,
        "columns": [c for c, _unit in columns],
        "units": [u for _c, u in columns],
        "rows": rows,
        "about": about,
    }


def _find_airports(data, about):
    """"Airports found": one row per airport, e.g. ["SNA", "John Wayne Airport", "Santa Ana", "CA", "medium"]."""
    airports = data["airports"]
    columns = [("Code", "text"), ("Name", "text"), ("City", "text"), ("State", "text"), ("Size", "text")]
    keys = ["iata", "name", "city", "state", "size"]
    # The distance column only when the search was "near an airport".
    if airports and "distance_mi" in airports[0]:
        columns.append(("Distance (miles)", "miles"))
        keys.append("distance_mi")
    rows = [[a[k] for k in keys] for a in airports]
    return [_table("Airports found", columns, rows, about)]


def _rank_airports(data, about):
    """The ranking: one row per airport with its rank, the sorted measure and its grade.

    A ranking by the score also shows the two halves of the score (demand and strain).
    """
    airports = data["airports"]
    measure = MEASURES[data["sort_by"]]
    words = "highest first" if data["order"] == "highest_first" else "lowest first"
    is_score = data["sort_by"] == "score"
    # "Region rank" only when the tool gives it (rank inside the filtered list).
    has_region = bool(airports) and "region_rank" in airports[0]

    columns = [("National rank", "rank")]
    if has_region:
        columns.append(("Region rank", "rank"))
    columns += [("Code", "text"), ("Name", "text"), ("State", "text"), ("Size", "text"),
                (measure.label, measure.unit), ("Grade", "grade")]  # fmt: skip
    if is_score:
        columns += [("Demand score", "points"), ("Strain score", "points")]

    rows = []
    for a in airports:
        row = [a["national_rank"]] + ([a["region_rank"]] if has_region else [])
        row += [a["iata"], a["name"], a["state"], a["size"], a["value"], a["grade"]]
        if is_score:
            row += [a["demand_score"], a["strain_score"]]
        rows.append(row)
    return [_table(f"Airports ranked by {measure.label} ({words})", columns, rows, about)]


def _airport_profile(data, about):
    """Airports side by side: one row per measure, two columns (value, grade) per airport.

    Example row for LAX and SNA (made-up numbers): ["Load factor", "share", 0.84, 71.0, 0.86, 80.0].
    """
    airports = data["airports"]
    codes = [a["iata"] for a in airports]
    # One value column and one grade column per airport. The value column's unit is "row":
    # each row says its own unit in the "Unit" column.
    columns = [("Measure", "text"), ("Unit", "text")]
    for code in codes:
        columns += [(code, "row"), (f"{code} grade", "grade")]

    rows = []
    names = list(airports[0]["measures"]) if airports else []
    for name in names:
        row = [MEASURES[name].label, MEASURES[name].unit]
        for a in airports:
            entry = a["measures"].get(name, {})
            row += [entry.get("value"), entry.get("grade")]
        rows.append(row)
    # The scores and the national rank have no grade.
    for label, unit, key in (("Score", "points", "final_score"), ("Demand score", "points", "demand_score"),
                             ("Strain score", "points", "strain_score"), ("National rank", "rank", "national_rank")):  # fmt: skip
        row = [label, unit]
        for a in airports:
            row += [a[key], None]
        rows.append(row)
    return [_table(f"Profile: {', '.join(codes)}", columns, rows, about)]


def _traffic_trend(data, about):
    """One measure over time: one row per airport (or area) per year, or per month."""
    measure = MEASURES[data["measure"]]
    by_month = data["by"] == "month"
    columns = [("Airport or area", "text"), ("Year", "year")]
    if by_month:
        columns.append(("Month", "month"))
    columns.append(("Value", measure.unit))
    if not by_month:
        columns.append(("Change from first year", "share"))

    rows = []
    for series in data["series"]:
        for p in series["points"]:
            row = [series["name"], p["year"]]
            if by_month:
                row.append(p["month"])
            row.append(p["value"])
            if not by_month:
                row.append(p["change_from_first"])
            rows.append(row)
    return [_table(f"{measure.label} by {data['by']}", columns, rows, about)]


def _route_mix(data, about):
    """Two tables: the airport's flight mix (one row), then its departures split into groups."""
    code, year = data["airport"], data["year"]
    # Table 1: the airport's summary shares (exam question 3: the long-haul share).
    mix = _table(
        f"{code} flight mix, {year}",
        [("Long-haul share", "share"), ("International share", "share"), ("Cargo share", "share")],
        [[data["long_haul_share"], data["international_share"], data["cargo_share"]]],
        about,
    )
    # Table 2: the departures split into groups.
    by_airline = data["group_by"] == "airline"
    columns = [("Group", "text")]
    if by_airline:
        columns.append(("Airline", "text"))
    columns += [("Departures", "departures"), ("Seats", "seats"), ("Passengers", "passengers"),
                ("Departures share", "share"), ("Seats share", "share"), ("Passengers share", "share")]  # fmt: skip
    rows = []
    for g in data["groups"]:
        row = [g["group"]]
        if by_airline:
            row.append(g.get("airline_name"))  # the "other" row has no airline name
        row += [g["departures"], g["seats"], g["passengers"],
                g["departures_share"], g["seats_share"], g["passengers_share"]]  # fmt: skip
        rows.append(row)
    group_words = data["group_by"].replace("_", " ")
    groups = _table(f"{code} departures by {group_words}, {year}", columns, rows, about)
    return [mix, groups]


# The delay causes in their fixed order, with plain names.
CAUSE_LABELS = [
    ("carrier", "Airline"),
    ("weather", "Weather"),
    ("nas", "Airspace/airport (NAS)"),
    ("late_aircraft", "Late incoming plane"),
    ("security", "Security"),
]


def _delay_causes(data, about):
    """Delay minutes by cause: five rows (one per cause) per airport, or per airport per month."""
    entries = data["airports"]
    # By month, each airport entry has a "months" list; by year it does not.
    by_month = any("months" in e for e in entries)
    columns = [("Airport", "text")]
    if by_month:
        columns.append(("Month", "month"))
    columns += [("Cause", "text"), ("Minutes", "minutes"), ("Minutes per flight", "minutes"), ("Share of delay", "share")]

    rows = []
    for e in entries:
        periods = e["months"] if by_month else [e]
        for period in periods:
            for key, label in CAUSE_LABELS:
                cause = period["causes"][key]
                row = [e["iata"]] + ([period["month"]] if by_month else [])
                row += [label, cause["minutes"], cause["per_flight"], cause["share"]]
                rows.append(row)
    return [_table("Delay causes, 2025 (arriving flights)", columns, rows, about)]


def _unmet_demand(data, about):
    """Two tables: the estimates (the amount), then the load factor by month (the "why").

    Example estimate row (shape only): ["SFO", "high", 0.8, 1063236, 6200, 0.03] - at an 80% target,
    about 1.06M seats were missing in 2025.
    """
    estimates, months = [], []
    for a in data["airports"]:
        for est in a["estimates"]:
            estimates.append([a["iata"], est["label"], est["target"], est["missing_seats"],
                              est["missing_flights"], est["missing_seats_pct"]])  # fmt: skip
        for m in a["why"]["by_month"]:
            months.append([a["iata"], m["month"], m["passengers"], m["seats"], m["load_factor"]])
    return [
        _table(
            "Unmet demand estimates, 2025",
            [("Airport", "text"), ("Estimate", "text"), ("Target load factor", "share"),
             ("Missing seats", "seats"), ("Missing flights", "departures"), ("Missing seats share", "share")],  # fmt: skip
            estimates,
            about,
        ),
        _table(
            "Load factor by month, 2025",
            [("Airport", "text"), ("Month", "month"), ("Passengers", "passengers"), ("Seats", "seats"),
             ("Load factor", "share")],  # fmt: skip
            months,
            about,
        ),
    ]


def _data_info(data, about):
    """Our data sources: one row per source, with where it came from and when it was loaded."""
    rows =[[s["source"], s["url"], s["period"], s["loaded_at"], s["row_count"]] for s in data["sources"]]
    # "Rows" is a plain count with no measure unit, so it is shown as it is ("text").
    columns = [("Source", "text"), ("URL", "text"), ("Period", "text"), ("Loaded at", "text"), ("Rows", "text")]
    return [_table("Data sources", columns, rows, about)]


def _live_status(data, about):
    """Today's FAA events for one airport (delays, ground stops); no events = no rows."""
    rows = []
    for ev in data["events"]:
        # Details: every other field of the event, e.g. "avg: 45 minutes; max: 1 hour".
        details = "; ".join(f"{k}: {v}" for k, v in ev.items() if k not in ("type", "reason"))
        rows.append([ev.get("type"), ev.get("reason"), details])
    columns = [("Type", "text"), ("Reason", "text"), ("Details", "text")]
    return [_table(f"FAA live status for {data['airport']}", columns, rows, about)]


# Which function builds the tables of each tool.
TABLE_BUILDERS = {
    "find_airports": _find_airports,
    "rank_airports": _rank_airports,
    "airport_profile": _airport_profile,
    "traffic_trend": _traffic_trend,
    "route_mix": _route_mix,
    "delay_causes": _delay_causes,
    "unmet_demand": _unmet_demand,
    "data_info": _data_info,
    "live_status": _live_status,
}


def build_tables(tool_events):
    """The tables of all tool events, in the order the tools ran (P89, P90).

    One table per successful tool result (two for route_mix and unmet_demand). A failed
    tool (an "error" result) or an unknown tool gives no table. The events are not changed.
    """
    tables = []
    for event in tool_events:
        builder = TABLE_BUILDERS.get(event["name"])
        result = event["result"]
        if builder is None or not isinstance(result, dict) or "error" in result:
            continue  # nothing ran, so there are no numbers to show

        tables += builder(result["data"], result["about"])
    return tables


# ---------------------------------------------------------------- reload a chat (P91)


def refusal_dict(cause):
    """A refusal as the page gets it, e.g. {"cause": "busy", "message": "<the fixed text>"}."""
    return {"cause": cause, "message": REFUSALS[cause]}


def _refusal_of_saved_answer(text):
    """The refusal cause of a saved final answer, or None (the same rules as loop.py, P91).

    A turn that ended early saved its refusal message as the answer (P59); the AI's
    off-topic reply is the out_of_scope sentence, maybe with spaces around it.
    """
    for cause in ("ai_unavailable", "too_many_steps"):
        if text == REFUSALS[cause]:
            return cause
    if text.strip() == REFUSALS["out_of_scope"]:
        return "out_of_scope"
    return None


def rebuild_turns(steps):
    """The chat's turns, rebuilt from its saved steps only (P91).

    The chat history keeps one row per step: the user's question, each AI reply (text or
    "please run these tools"), each tool result. To reload a chat we put these rows back
    together into turns of {question, answer, tables, steps, refusal}, using the same
    build_tables/build_steps as the live reply, so a reloaded turn looks exactly the same.
    """
    # Group the steps into turns: a turn starts at each user question.
    groups = []
    for step in steps:
        if step.role == "user":
            groups.append([step])
        elif groups:
            groups[-1].append(step)

    turns = []
    for group in groups:
        question, rest = group[0].content, group[1:]
        # Rebuild the turn's tool events in the same shape run_turn gives the live reply:
        # {"id", "name", "args", "result"}.
        events = []
        answer = ""
        for i, s in enumerate(rest):
            if s.role != "assistant":
                continue
            if s.tool_calls:
                # The results of this request are the tool steps saved right after it (one
                # round), so an ID the AI reuses in a later round can't be mixed up.
                results = {}
                for t in rest[i + 1 :]:
                    if t.role != "tool":
                        break
                    results[t.tool_call_id] = json.loads(t.content)
                # Each request paired with its result; a request with no saved result is left out.
                for call in s.tool_calls:
                    if call["id"] in results:
                        events.append({"id": call["id"], "name": call["name"], "args": call["args"],
                                       "result": results[call["id"]]})  # fmt: skip
            else:
                answer = s.content or ""  # the last such step is the final answer
        # A turn that ended with a refusal saved the refusal text as its answer; show it
        # as a refusal again, like the live reply did.
        cause = _refusal_of_saved_answer(answer)
        turns.append(
            {
                "question": question,
                "answer": "" if cause else answer,
                "tables": build_tables(events),
                "steps": build_steps(events),
                "refusal": refusal_dict(cause) if cause else None,
            }
        )
    return turns
