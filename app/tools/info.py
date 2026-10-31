"""Tool 8, `data_info`: which data the agent has, for which period, and what it lacks.

What it is:   The data_info tool: the sources loaded (with their period, load time and row
              count, read from the data_sources table), the scope (how many airports), and
              a fixed list of what the data does not cover.
Why we need:  Answers "where does your data come from?" and "how fresh is it?", and lets the
              agent state its scope and gaps honestly instead of guessing.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step12_unmet_info_live.py.
Uses:         app/tools/base.py; tables data_sources, airports.
Main parts:   SCOPE_TEXT, GAPS - the fixed scope sentence and the list of gaps.
              InfoSettings - no settings; any setting given is an error.
              data_info(con, settings) - the tool; a ToolResult with sources, scope, gaps.
Design:       docs/tools.md "8. data_info"; docs/data-sources.md; docs/schema.md
              data_sources; docs/implementation-plan.md P53.
"""

from pydantic import BaseModel

from app.tools.base import ToolResult, register

SCOPE_TEXT = "US airports with scheduled passenger service and an IATA code; US territories excluded."
GAPS = [
    "No terminal size or gate counts: runways and traffic stand in for them.",
    "No ticket prices.",
    "No airport finances (revenue, costs, debt).",
    "Delay data covers only domestic flights of the larger US airlines.",
    "Live FAA status is context only and is never part of a score.",
]

_SOURCES_SQL = "SELECT source, url, period, loaded_at, row_count FROM data_sources ORDER BY source"


class InfoSettings(BaseModel):
    pass


@register(
    "data_info",
    "Describe the data: each source with its URL, period, load time and row count; the scope (how many "
    "US airports); and what the data does not have (e.g. terminal size, ticket prices). No settings.",
    InfoSettings,
)
def data_info(con, settings):
    sources = [
        {"source": source, "url": url, "period": period, "loaded_at": str(loaded_at), "row_count": row_count}
        for source, url, period, loaded_at, row_count in con.execute(_SOURCES_SQL).fetchall()
    ]
    (airports,) = con.execute("SELECT COUNT(*) FROM airports").fetchone()
    data = {"sources": sources, "scope": {"airports": airports, "text": SCOPE_TEXT}, "gaps": list(GAPS)}
    about = {"data_period": "Each source's period is listed with it."}
    return ToolResult(data=data, about=about)
