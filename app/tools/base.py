"""What every tool shares: the result format, the tool list, setting checks, run_tool.

The AI never writes SQL. It sends a tool name and settings; `run_tool` checks the
settings with the tool's pydantic model and only then runs the tool. A bad
setting or an unknown tool gives the AI an error that lists the allowed values,
so it can correct itself, and nothing runs.
"""

from typing import Annotated, Literal, NamedTuple, get_args, get_origin

from pydantic import BaseModel, BeforeValidator, Field, ValidationError

from app.measures import MEASURES

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


def _upper(value):
    """Accept "ca" as "CA"; leave non-text alone so pydantic reports the wrong type."""
    return value.upper() if isinstance(value, str) else value


# Shared setting types. Tools use them in their settings models, e.g. `top_n: TopN = 10`.
# Literal gives the AI the full list of choices in the tool description (JSON schema).
TopN = Annotated[int, Field(ge=1, le=25), Allowed([1, 25])]
# Only the count is checked here; whether a code is a real airport is Step 9.
AirportList = Annotated[list[str], Field(min_length=1, max_length=5), Allowed([1, 5])]
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


def _setting_error(model, error):
    """Turn the first pydantic error into a plain-English error with allowed values."""
    setting = str(error["loc"][0]) if error["loc"] else "settings"
    field = model.model_fields.get(setting)
    metadata = list(field.metadata) if field else []
    # For an optional setting (`StateList | None`), the marker sits inside the union's Annotated member.
    for member in get_args(field.annotation) if field else ():
        if get_origin(member) is Annotated:
            metadata.extend(get_args(member)[1:])
    markers = [m for m in metadata if isinstance(m, Allowed)]
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

    return tool.fn(con, checked).to_dict()


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
