"""What every tool shares: the result format, the tool list, setting checks, run_tool.

What it is:   The common frame of all agent tools: the result format, the tool list, the
              shared setting types and checks, and run_tool, the only way a tool is run.
Why we need:  The AI never writes SQL. It sends a tool name and settings; run_tool checks
              the settings with the tool's pydantic model and only then runs the tool.
Used by:      app/tools/find.py.
              tests: test_step08_tool_base.py, test_step09_resolver.py.
              Planned: the tool files of Steps 10-12 and the Step 14 agent loop.
Uses:         app/measures.py (MEASURES), app/refusals.py (REFUSALS),
              app/tools/resolver.py (resolve_airport, which reads the airports table).
Main parts:   US_STATES - the 50 states + DC.
              Allowed - marker on a setting type: the allowed values shown on an error.
              AIRPORT_NAMES - marker: the setting holds airport names to turn into codes.
              SettingsError - raised by a settings model's own check, with allowed values.
              TopN, AirportList, AirportCode, State, StateList, MeasureName - shared
                setting types for the tools' settings models.
              ToolResult(data, about) - what every tool returns; .to_dict().
              Tool - one registered tool: name, description, settings_model, fn.
              TOOLS - the tool list: name -> Tool.
              register(name, description, settings_model) - decorator that adds a tool.
              run_tool(con, name, settings) - check the settings, turn airport names into
                codes, run the tool; returns a dict and never raises for a bad setting.
              tool_specs_for_ai() - the tool descriptions sent to the AI, sorted by name.
Design:       docs/tools.md "How a tool call works" and "Limits that apply to every tool";
              docs/agent.md "What every tool returns"; docs/decisions.md 7.13, 7.19;
              docs/implementation-plan.md P24, P28.

A bad setting or an unknown tool gives the AI an error that lists the allowed values,
so it can correct itself, and nothing runs.
"""

from typing import Annotated, Literal, NamedTuple, get_args, get_origin

from pydantic import BaseModel, BeforeValidator, Field, ValidationError

from app.measures import MEASURES
from app.refusals import REFUSALS
from app.tools.resolver import resolve_airport

# The 50 states + DC. A fixed list in code, not read from the database, so a
# state with no airport in our data is still a valid (empty) answer.
US_STATES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
)  # fmt: skip


class Allowed(NamedTuple):
    """Marker on a setting type: the allowed values to show the AI on an error."""

    values: list


class _AirportNames:
    """Marker on a setting type: its values are airport names or codes that
    `run_tool` turns into codes before the tool runs (P28)."""


AIRPORT_NAMES = _AirportNames()


class SettingsError(ValueError):
    """Raised by a settings model's own check (one that looks at several settings
    together); `run_tool` turns it into an error with these allowed values."""

    def __init__(self, message, allowed=()):
        super().__init__(message)
        self.message = message
        self.allowed = list(allowed)


def _upper(value):
    """Accept "ca" as "CA"; leave non-text alone so pydantic reports the wrong type."""
    return value.upper() if isinstance(value, str) else value


# Shared setting types. Tools use them in their settings models, e.g. `top_n: TopN = 10`.
# Literal gives the AI the full list of choices in the tool description (JSON schema).
TopN = Annotated[int, Field(ge=1, le=25), Allowed([1, 25])]
# Airport names or codes; run_tool turns each into one code from our list (P28).
AirportList = Annotated[list[str], Field(min_length=1, max_length=5), Allowed([1, 5]), AIRPORT_NAMES]
AirportCode = Annotated[str, Field(min_length=1, max_length=100), AIRPORT_NAMES]
State = Annotated[Literal[US_STATES], BeforeValidator(_upper)]
StateList = Annotated[list[State], Allowed(sorted(US_STATES))]
MeasureName = Annotated[Literal[tuple(MEASURES)], Allowed(sorted(MEASURES))]


class ToolResult:
    """What every tool returns: the numbers (`data`) and their caveats (`about`)."""

    def __init__(self, data, about=None):
        about = about or {}
        self.data = data
        # `about` always has all four keys, so the AI always sees the same shape.
        self.about = {
            "data_period": about.get("data_period", ""),
            "filters": list(about.get("filters", [])),
            "missing": list(about.get("missing", [])),
            "assumptions": list(about.get("assumptions", [])),
        }

    def to_dict(self):
        return {"data": self.data, "about": self.about}


class Tool(NamedTuple):
    """One registered tool."""

    name: str
    description: str
    settings_model: type[BaseModel]
    fn: object  # fn(con, settings) -> ToolResult


TOOLS = {}


def register(name, description, settings_model):
    """Decorator that adds `fn(con, settings) -> ToolResult` to TOOLS under `name`."""

    def decorator(fn):
        if name in TOOLS:
            raise ValueError(f"A tool named {name!r} is already registered.")
        TOOLS[name] = Tool(name, description, settings_model, fn)
        return fn

    return decorator


def _error(message, allowed):
    return {"error": message, "allowed": list(allowed)}


def _markers(field):
    """Every marker on a setting's type, also when it is wrapped as optional."""
    if field is None:
        return []
    metadata = list(field.metadata)
    # For an optional setting (`StateList | None`), the marker sits inside the union's Annotated member.
    for member in get_args(field.annotation):
        if get_origin(member) is Annotated:
            metadata.extend(get_args(member)[1:])
    return metadata


def _setting_error(model, error):
    """Turn the first pydantic error into a plain-English error with allowed values."""
    own = (error.get("ctx") or {}).get("error")
    if isinstance(own, SettingsError):
        return _error(own.message, own.allowed)
    setting = str(error["loc"][0]) if error["loc"] else "settings"
    field = model.model_fields.get(setting)
    markers = [m for m in _markers(field) if isinstance(m, Allowed)]
    allowed = markers[0].values if markers else []
    if error["type"] == "literal_error":
        reason = "this value is not one of the allowed values"
    else:
        reason = error["msg"]
    return _error(f"The setting '{setting}' is not valid: {reason}. Use one of the allowed values.", allowed)


def run_tool(con, name, settings):
    """Check `settings`, run the tool, return its result as a dict.

    Never raises for an unknown tool or a bad setting: returns
    {"error": ..., "allowed": [...]} instead and does not run the tool.
    """
    tool = TOOLS.get(name)
    if tool is None:
        return _error(f"There is no tool named '{name}'. Use one of the allowed tools.", sorted(TOOLS))

    model = tool.settings_model
    if not isinstance(settings, dict):
        return _error("Settings must be a set of name/value pairs.", sorted(model.model_fields))

    # Checked here, not by the model, so every tool refuses unknown setting
    # names even if its model forgets `extra="forbid"`.
    unknown = sorted(set(settings) - set(model.model_fields))
    if unknown:
        return _error(
            f"Unknown setting '{unknown[0]}'. Use only the allowed setting names.", sorted(model.model_fields)
        )

    try:
        checked = model.model_validate(settings)
    except ValidationError as exc:
        return _setting_error(model, exc.errors()[0])

    checked, error = _names_to_codes(con, checked)
    if error:
        return error

    return tool.fn(con, checked).to_dict()


def _one_code(con, setting, text):
    """(code, None) when `text` is exactly one airport, else (None, error)."""
    matches = resolve_airport(con, text)
    if len(matches) == 1:
        return matches[0].iata, None
    if not matches:
        return None, _error(f"{REFUSALS['airport_not_found']} (setting '{setting}': '{text}')", [])
    return None, _error(
        f"'{text}' in setting '{setting}' matches several airports. Pick one of the allowed codes.",
        [m.iata for m in matches],
    )


def _names_to_codes(con, checked):
    """Turn airport names into codes in the settings typed AirportList or AirportCode.

    Runs after the pydantic checks, and only on settings the caller sent
    (never `states`, where "LA" is Louisiana). Returns (settings, error).
    """
    updates = {}
    for setting, field in type(checked).model_fields.items():  # fixed order, so errors are repeatable
        value = getattr(checked, setting)
        if setting not in checked.model_fields_set or value is None or AIRPORT_NAMES not in _markers(field):
            continue
        texts = value if isinstance(value, list) else [value]
        codes = []
        for text in texts:
            code, error = _one_code(con, setting, text)
            if error:
                return checked, error
            codes.append(code)
        updates[setting] = codes if isinstance(value, list) else codes[0]
    return checked.model_copy(update=updates), None


def tool_specs_for_ai():
    """The tool descriptions sent to the AI, one per tool, sorted by name."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.settings_model.model_json_schema(),
            },
        }
        for tool in sorted(TOOLS.values(), key=lambda t: t.name)
    ]
