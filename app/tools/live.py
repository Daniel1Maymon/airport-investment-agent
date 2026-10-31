"""Tool 9, `live_status`: today's FAA delays and closures for one airport.

What it is:   The live_status tool: gets the FAA live airport status feed (XML), and lists
              the delay and closure events it reports for one airport right now.
Why we need:  Adds "what is happening there today" as context to an answer. It is never
              part of any score, and if the feed is down the tool says so instead of failing.
Used by:      app/tools/__init__.py (the import registers the tool); the AI calls it through
              run_tool. tests: test_step12_unmet_info_live.py.
Uses:         app/tools/base.py; the FAA feed at FEED_URL (through httpx); no tables.
Main parts:   FEED_URL - the FAA live airport status feed.
              fetch_faa_status() - gets the feed with a 10-second timeout; returns the XML text.
              LiveSettings - the tool's setting: one airport name or code.
              live_status(con, settings, fetch=None) - the tool; `fetch` replaces
                fetch_faa_status (tests pass a fake); a ToolResult, never an exception
                when the feed is down or broken.
Design:       docs/tools.md "9. live_status"; docs/data-sources.md E;
              docs/implementation-plan.md P54.

The feed's text is untrusted: it is read with the standard library XML parser, only
plain text is kept, and each reason is cut to 200 characters.
"""

import xml.etree.ElementTree as ET

import httpx
from pydantic import BaseModel, Field

from app.tools.base import AirportCode, ToolResult, register

FEED_URL = "https://nasstatus.faa.gov/api/airport-status-information"
TIMEOUT_SECONDS = 10
MAX_REASON = 200

FEED_DOWN = "The FAA live status feed is not available right now; try again later."
CONTEXT_ONLY = "Live status is context only; it is never part of any score."


def fetch_faa_status():
    """The FAA live status feed as XML text. Raises httpx errors when it is down."""
    response = httpx.get(FEED_URL, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text


class LiveSettings(BaseModel):
    airport: AirportCode = Field(description="One airport code or name, e.g. 'SFO'.")


def _event(kind, element):
    """One event: its type, the reason (cut to 200 characters) and its other fields as text."""
    event = {"type": kind}
    for child in element:
        tag = child.tag.lower()
        if tag == "arpt":
            continue
        if tag == "reason":
            event["reason"] = (child.text or "").strip()[:MAX_REASON]
        elif len(child):  # e.g. <Arrival_Departure Type="Arrival"><Min>...</Min>...</Arrival_Departure>
            if "Type" in child.attrib:
                event["direction"] = child.attrib["Type"]
            for field in child:
                event[field.tag.lower()] = (field.text or "").strip()
        else:
            event[tag] = (child.text or "").strip()
    return event


def _parse(xml_text, code):
    """(updated, events for `code`) from the feed text. Raises ET.ParseError when broken."""
    root = ET.fromstring(xml_text)
    events = []
    for delay_type in root.iter("Delay_type"):
        kind = (delay_type.findtext("Name") or "").strip()
        for element in delay_type.iter():
            arpt = element.find("ARPT")
            if arpt is not None and (arpt.text or "").strip().upper() == code:
                events.append(_event(kind, element))
    return root.findtext("Update_Time"), events


@register(
    "live_status",
    "Today's FAA delays and closures for one US airport (code or name), from the FAA live status feed. "
    "Context only: never part of any score. Says so when the feed is not available.",
    LiveSettings,
)
def live_status(con, settings, fetch=None):
    code = settings.airport
    fetch = fetch or fetch_faa_status  # looked up at call time, so tests can replace it
    missing = []
    try:
        updated, events = _parse(fetch(), code)
        available = True
    except (httpx.HTTPError, ET.ParseError):
        updated, events, available = None, [], False
        missing.append(FEED_DOWN)
    if available and not events:
        missing.append(f"No FAA delays or closures reported for {code} right now.")
    about = {
        "data_period": "Live, right now (FAA airport status feed)",
        "filters": [f"airport: {code}"],
        "missing": missing,
        "assumptions": [CONTEXT_ONLY],
    }
    data = {"airport": code, "feed_available": available, "updated": updated, "events": events}
    return ToolResult(data=data, about=about)
