"""Step 8 tests: what every tool shares (app/tools/base.py, app/refusals.py).

What the builder must follow (names the tests rely on)
------------------------------------------------------
app/tools/base.py
* `ToolResult(data, about=None)`. `about` is a dict that may give any of
  `data_period` (str), `filters`, `missing`, `assumptions` (lists of str).
  `.to_dict()` -> `{"data": data, "about": {...}}`; `about` ALWAYS has exactly
  those four keys. A key not given becomes "" (data_period) or [] (the lists).
* `TOOLS`: dict, tool name -> registered entry.
* `register(name, description, settings_model)`: decorator for
  `fn(con, settings) -> ToolResult`, where `settings` is an instance of
  `settings_model` (a pydantic model). A name already registered -> ValueError.
* `run_tool(con, name, settings: dict) -> dict`: checks `settings` with the
  tool's model, runs the tool, returns `ToolResult.to_dict()`. It NEVER raises
  for a bad setting or an unknown tool. Instead it returns
  `{"error": <plain-English text>, "allowed": [...]}` and does NOT run the tool:
    - unknown tool          -> allowed = sorted names in TOOLS
    - number out of range   -> allowed = [min, max], e.g. [1, 25]; the error
                               text names the setting (e.g. "top_n")
    - too many/few airports -> allowed = [1, 5]
    - unknown measure       -> allowed = sorted(MEASURES)
    - unknown state         -> allowed = sorted 51 codes (50 states + DC)
    - unknown setting name  -> allowed = sorted setting names of that tool.
      run_tool must catch this ITSELF: the test tool's model below is a plain
      `BaseModel` with no `extra="forbid"` config.
    - wrong type            -> an error dict (any `allowed`), no exception
  When several things are wrong, reporting one error is enough.
* Shared setting types for settings models (e.g. `top_n: TopN = 10`):
    `TopN` int 1..25; `AirportList` list[str] with 1..5 items (only the COUNT
    is checked here; real airport codes are Step 9); `StateList` list of codes
    from `US_STATES`, lower case accepted and turned upper case ("ca" -> "CA");
    `MeasureName` str, a key of MEASURES.
* `US_STATES`: the fixed 50 states + DC (51 codes), not read from the database.
* `tool_specs_for_ai() -> list[dict]`: one entry per registered tool, sorted
  by name: `{"type": "function", "function": {"name", "description",
  "parameters": settings_model.model_json_schema()}}`.

app/refusals.py
* `REFUSALS: dict[str, str]`: key -> fixed message; keys exactly the Key
  column of the "Refusal messages" table in docs/agent.md (P23).
* `Refusal(cause, message)`: a small record with those two fields.

The test-only tool
------------------
`list_test_airports` (registered by a fixture, removed again after each test
so it never leaks into the real registry) lists airport codes from the tiny
`airports` table for the given states, with `?` placeholders (values are
never pasted into the SQL). Tiny data (tests/fixtures/TINY_DATA.md):
  MA: BOS   NH: MHT   VT: BTV   ME: BHB   CA: LAX, SNA   AK: ANC   (7 rows)
"""

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.measures import MEASURES
from app.refusals import REFUSALS, Refusal
from app.tools import base
from app.tools.base import (
    TOOLS,
    US_STATES,
    AirportList,
    MeasureName,
    StateList,
    ToolResult,
    TopN,
    register,
    run_tool,
    tool_specs_for_ai,
)

AGENT_DOC = Path(__file__).resolve().parent.parent / "docs" / "agent.md"

TEST_TOOL = "list_test_airports"

# The 50 states + DC, written out by hand (a fixed fact, not from any doc).
ALL_51_CODES = sorted(
    """AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD
       MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC
       SD TN TX UT VT VA WA WV WI WY DC""".split()
)


class _TestSettings(BaseModel):
    """Settings of the test-only tool. Plain BaseModel on purpose (see above)."""

    top_n: TopN = 10
    airports: AirportList = ["BOS"]
    states: StateList = ["MA"]
    measure: MeasureName = "load_factor"


# Sorted names of the test tool's settings.
TEST_SETTING_NAMES = ["airports", "measure", "states", "top_n"]


@pytest.fixture
def test_tool():
    """Register the test-only tool; restore TOOLS exactly as it was afterwards.

    Yields a dict whose "calls" counts how many times the tool really ran.
    """
    saved = dict(TOOLS)
    state = {"calls": 0, "settings": None}

    @register(TEST_TOOL, "Lists airport codes in the given states (test only).", _TestSettings)
    def _list_test_airports(con, settings):
        state["calls"] += 1
        state["settings"] = settings
        placeholders = ", ".join("?" for _ in settings.states)
        rows = con.execute(
            f"SELECT iata FROM airports WHERE state IN ({placeholders}) ORDER BY iata LIMIT ?",
            [*settings.states, settings.top_n],
        ).fetchall()
        return ToolResult(
            data={"airports": [r[0] for r in rows], "states": list(settings.states)},
            about={"data_period": "test period", "filters": ["only the given states"]},
        )

    yield state
    TOOLS.clear()
    TOOLS.update(saved)


def _is_error(result):
    return isinstance(result, dict) and "error" in result and "allowed" in result


# 1
def test_result_has_data_and_about(tiny_db, test_tool):
    # The tool gave only data_period and filters; the other two must still be there.
    result = run_tool(tiny_db, TEST_TOOL, {"states": ["MA", "NH"]})
    assert set(result) == {"data", "about"}
    assert result["data"] == {"airports": ["BOS", "MHT"], "states": ["MA", "NH"]}
    assert result["about"] == {
        "data_period": "test period",
        "filters": ["only the given states"],
        "missing": [],
        "assumptions": [],
    }

    # Directly, with no about at all: every key has its empty default.
    assert ToolResult(data={"x": 1}).to_dict() == {
        "data": {"x": 1},
        "about": {"data_period": "", "filters": [], "missing": [], "assumptions": []},
    }

    # All four given: passed through as they are.
    full = {
        "data_period": "2025",
        "filters": ["f"],
        "missing": ["m"],
        "assumptions": ["a"],
    }
    assert ToolResult(data=[1, 2], about=full).to_dict() == {"data": [1, 2], "about": full}


# 2
def test_unknown_tool_returns_error(tiny_db, test_tool):
    result = run_tool(tiny_db, "no_such_tool", {})
    assert _is_error(result)
    assert isinstance(result["error"], str) and result["error"]
    assert result["allowed"] == sorted(TOOLS)
    assert TEST_TOOL in result["allowed"]


# 3
def test_top_n_over_25_refused_with_range(tiny_db, test_tool):
    result = run_tool(tiny_db, TEST_TOOL, {"top_n": 26})
    assert _is_error(result)
    assert result["allowed"] == [1, 25]
    assert "top_n" in result["error"]
    assert test_tool["calls"] == 0

    # The other end of the range too.
    result = run_tool(tiny_db, TEST_TOOL, {"top_n": 0})
    assert _is_error(result)
    assert result["allowed"] == [1, 25]
    assert "top_n" in result["error"]

    # Both ends are allowed.
    assert "error" not in run_tool(tiny_db, TEST_TOOL, {"top_n": 1})
    assert "error" not in run_tool(tiny_db, TEST_TOOL, {"top_n": 25})


# 4
def test_more_than_5_airports_refused(tiny_db, test_tool):
    six = ["BOS", "MHT", "BTV", "BHB", "LAX", "SNA"]
    result = run_tool(tiny_db, TEST_TOOL, {"airports": six})
    assert _is_error(result)
    assert result["allowed"] == [1, 5]
    assert test_tool["calls"] == 0

    # 5 is fine (only the count is checked in Step 8).
    assert "error" not in run_tool(tiny_db, TEST_TOOL, {"airports": six[:5]})

    # An empty list is refused too (at least 1).
    result = run_tool(tiny_db, TEST_TOOL, {"airports": []})
    assert _is_error(result)
    assert result["allowed"] == [1, 5]


# 5
def test_unknown_measure_lists_allowed(tiny_db, test_tool):
    result = run_tool(tiny_db, TEST_TOOL, {"measure": "happiness"})
    assert _is_error(result)
    assert result["allowed"] == sorted(MEASURES)
    assert test_tool["calls"] == 0

    # A real measure is accepted.
    assert "error" not in run_tool(tiny_db, TEST_TOOL, {"measure": "growth_short"})


# 6
def test_unknown_state_refused(tiny_db, test_tool):
    result = run_tool(tiny_db, TEST_TOOL, {"states": ["XX"]})
    assert _is_error(result)
    assert result["allowed"] == ALL_51_CODES
    assert len(result["allowed"]) == 51
    assert test_tool["calls"] == 0


# 7
def test_bad_setting_returns_error_not_exception(tiny_db, test_tool):
    # Wrong type: must come back as an error dict, not raise.
    result = run_tool(tiny_db, TEST_TOOL, {"top_n": "ten"})
    assert _is_error(result)
    assert isinstance(result["error"], str) and result["error"]
    assert test_tool["calls"] == 0

    # A plain string where a list is expected (pydantic does not turn "MA" into ["MA"]).
    result = run_tool(tiny_db, TEST_TOOL, {"states": "MA"})
    assert _is_error(result)

    result = run_tool(tiny_db, TEST_TOOL, {"airports": 42})
    assert _is_error(result)
    assert test_tool["calls"] == 0

    # A number inside the state list: upper-casing it must not blow up
    # (e.g. 5.upper() would raise AttributeError if not handled).
    result = run_tool(tiny_db, TEST_TOOL, {"states": [5]})
    assert _is_error(result)
    assert test_tool["calls"] == 0

    result = run_tool(tiny_db, TEST_TOOL, {"measure": 5})
    assert _is_error(result)
    assert test_tool["calls"] == 0


# 8
def test_sql_text_in_setting_is_harmless(tiny_db, test_tool):
    before = tiny_db.execute("SELECT COUNT(*) FROM airports").fetchone()[0]
    assert before == 7  # 7 airports in the tiny dataset

    result = run_tool(tiny_db, TEST_TOOL, {"states": ["CA'; DROP TABLE airports"]})
    assert _is_error(result)
    assert result["allowed"] == ALL_51_CODES
    assert test_tool["calls"] == 0

    after = tiny_db.execute("SELECT COUNT(*) FROM airports").fetchone()[0]
    assert after == 7


# 9
def test_tool_specs_for_ai_have_json_schema(test_tool):
    specs = tool_specs_for_ai()
    assert isinstance(specs, list)
    assert len(specs) == len(TOOLS)

    names = [s["function"]["name"] for s in specs]
    assert names == sorted(names)
    assert set(names) == set(TOOLS)

    ours = [s for s in specs if s["function"]["name"] == TEST_TOOL]
    assert len(ours) == 1
    assert ours[0] == {
        "type": "function",
        "function": {
            "name": TEST_TOOL,
            "description": "Lists airport codes in the given states (test only).",
            "parameters": _TestSettings.model_json_schema(),
        },
    }
    # The schema really describes the settings.
    assert set(ours[0]["function"]["parameters"]["properties"]) == set(TEST_SETTING_NAMES)


def _refusal_keys_from_agent_doc():
    """Read the Key column of the table under "## Refusal messages" in agent.md."""
    text = AGENT_DOC.read_text(encoding="utf-8")
    start = text.index("## Refusal messages")
    rest = text[start + len("## Refusal messages"):]
    end = rest.find("\n## ")
    section = rest if end == -1 else rest[:end]

    rows = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    cells = [[c.strip() for c in row.strip("|").split("|")] for row in rows]
    header = cells[0]
    key_col = header.index("Key")
    keys = []
    for row in cells[1:]:
        if all(re.fullmatch(r":?-+:?", c) for c in row):  # the |---|---| line
            continue
        keys.append(row[key_col].strip("`").strip())
    return keys


# 10
def test_one_refusal_per_cause_in_agent_doc():
    doc_keys = _refusal_keys_from_agent_doc()
    assert len(doc_keys) == 9
    assert len(set(doc_keys)) == 9
    assert set(REFUSALS) == set(doc_keys)
    for key, message in REFUSALS.items():
        assert isinstance(message, str) and message.strip(), key


# ---- extras ----------------------------------------------------------------


def test_valid_call_runs_the_tool_once(tiny_db, test_tool):
    result = run_tool(tiny_db, TEST_TOOL, {"states": ["CA"], "top_n": 5})
    # CA in the tiny data: LAX, SNA (A->Z).
    assert result["data"]["airports"] == ["LAX", "SNA"]
    assert test_tool["calls"] == 1
    # The tool got an instance of its settings model, not the raw dict.
    assert isinstance(test_tool["settings"], _TestSettings)
    assert test_tool["settings"].top_n == 5


def test_top_n_limits_rows(tiny_db, test_tool):
    # MA, NH, VT, ME -> BHB, BOS, BTV, MHT (A->Z); top_n 2 keeps the first 2.
    result = run_tool(tiny_db, TEST_TOOL, {"states": ["MA", "NH", "VT", "ME"], "top_n": 2})
    assert result["data"]["airports"] == ["BHB", "BOS"]


def test_state_not_in_tiny_data_is_accepted(tiny_db, test_tool):
    # TX is a real state; the tiny data has no TX airport, so the list is empty.
    result = run_tool(tiny_db, TEST_TOOL, {"states": ["TX"]})
    assert "error" not in result
    assert result["data"] == {"airports": [], "states": ["TX"]}


def test_lower_case_state_becomes_upper_case(tiny_db, test_tool):
    result = run_tool(tiny_db, TEST_TOOL, {"states": ["ca", "Ak"]})
    assert "error" not in result
    assert result["data"]["states"] == ["CA", "AK"]
    # CA: LAX, SNA; AK: ANC -> A->Z: ANC, LAX, SNA
    assert result["data"]["airports"] == ["ANC", "LAX", "SNA"]


def test_us_states_has_50_states_and_dc():
    assert len(US_STATES) == 51
    assert sorted(US_STATES) == ALL_51_CODES


def test_unknown_setting_name_refused(tiny_db, test_tool):
    result = run_tool(tiny_db, TEST_TOOL, {"region": "New England"})
    assert _is_error(result)
    assert result["allowed"] == TEST_SETTING_NAMES
    assert test_tool["calls"] == 0


def test_register_same_name_twice_raises(test_tool):
    with pytest.raises(ValueError):

        @register(TEST_TOOL, "again", _TestSettings)
        def _again(con, settings):
            return ToolResult(data=None)


def test_test_tool_is_removed_after_use():
    # The fixture's tool must not leak into the registry for other tests.
    assert TEST_TOOL not in TOOLS


def test_refusal_record_has_cause_and_message():
    r = Refusal("busy", REFUSALS["busy"])
    assert r.cause == "busy"
    assert r.message == REFUSALS["busy"]


def test_shared_types_are_exported():
    # Later tools import these from app.tools.base.
    for name in ("TopN", "AirportList", "StateList", "MeasureName", "US_STATES"):
        assert hasattr(base, name), name
