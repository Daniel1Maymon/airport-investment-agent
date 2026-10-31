"""The name resolver: turns what the user typed into airport codes from our own list.

What it is:   Finds the airports that match what the user typed (a code, a short city
              name, a city, an airport name), and holds the US Census regions.
Why we need:  It never guesses. It only returns airports that are in our `airports`
              table, and an empty list means "airport not found".
Used by:      app/tools/base.py (run_tool turns airport names in settings into codes),
              app/tools/find.py, app/tools/rank.py, app/tools/profile.py,
              app/tools/unmet.py (load_airports).
              tests: test_step09_resolver.py, test_step10_rank_profile.py.
Uses:         tables airports and enplanements (2025 hub type), through one fixed query.
              No other project file.
Main parts:   HUB_SIZES - FAA hub letter -> size in words (P26).
              SIZE_YEAR - the year of the hub size (2025).
              ABBREVIATIONS - short city names: LA, NYC, SF, DC (P5).
              REGIONS - Census region or division -> its states.
              AIRPORTS_SQL - the one fixed query.
              AirportMatch - one airport found: iata, name, city, state, size.
              load_airports(con) - every airport as (AirportMatch, lat, lon), by code.
              resolve_airport(con, text) - airports matching `text` (rules of P25);
                [] means not found.
              resolve_region(name) - the states of a region or division; unknown gives
                ValueError.
Design:       docs/agent.md "Name resolver"; docs/tools.md "1. find_airports";
              docs/implementation-plan.md P5, P25, P26.

The matching is done in Python on the rows read by one fixed query, so the user's
text never goes into SQL, and characters like `%` or `_` are just characters.
"""

from typing import NamedTuple

# The FAA hub size letters (enplanements.hub_type) in plain words (P26).
HUB_SIZES = {"L": "large", "M": "medium", "S": "small", "N": "non-hub"}
SIZE_YEAR = 2025

# Short names people use for a city (P5). Each gives every airport in that city.
ABBREVIATIONS = {"LA": "Los Angeles", "NYC": "New York", "SF": "San Francisco", "DC": "Washington"}

# US Census Bureau regions and divisions (published Census definition).
_DIVISIONS = {
    "New England": ["CT", "ME", "MA", "NH", "RI", "VT"],
    "Middle Atlantic": ["NJ", "NY", "PA"],
    "East North Central": ["IL", "IN", "MI", "OH", "WI"],
    "West North Central": ["IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South Atlantic": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"],
    "East South Central": ["AL", "KY", "MS", "TN"],
    "West South Central": ["AR", "LA", "OK", "TX"],
    "Mountain": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"],
    "Pacific": ["AK", "CA", "HI", "OR", "WA"],
}
_REGION_DIVISIONS = {
    "Northeast": ["New England", "Middle Atlantic"],
    "Midwest": ["East North Central", "West North Central"],
    "South": ["South Atlantic", "East South Central", "West South Central"],
    "West": ["Mountain", "Pacific"],
}
REGIONS = {
    **{region: [s for d in divisions for s in _DIVISIONS[d]] for region, divisions in _REGION_DIVISIONS.items()},
    **_DIVISIONS,
}

# One fixed query: every airport with its 2025 FAA hub type (no user text in it).
AIRPORTS_SQL = """
SELECT a.iata, a.name, a.city, a.state, e.hub_type, a.lat, a.lon
FROM airports a
LEFT JOIN enplanements e ON e.iata = a.iata AND e.year = ?
ORDER BY a.iata
"""


class AirportMatch(NamedTuple):
    """One airport found by the resolver. `size` is the 2025 FAA hub size, or None."""

    iata: str
    name: str
    city: str
    state: str
    size: str | None


def load_airports(con):
    """Every airport in our list as (AirportMatch, lat, lon), sorted by code."""
    rows = con.execute(AIRPORTS_SQL, [SIZE_YEAR]).fetchall()
    return [
        (AirportMatch(iata, name or "", city or "", state or "", HUB_SIZES.get(hub)), lat, lon)
        for iata, name, city, state, hub, lat, lon in rows
    ]


def resolve_airport(con, text):
    """Airports matching `text`, sorted by code; [] means not found.

    Rules in order, stopping at the first that finds something (P25):
    1. a code in our list; 2. a short city name (LA, NYC, SF, DC);
    3. the exact city; 4. the exact airport name; 5. part of the name (3+ characters).
    All rules ignore case and spaces at the ends.
    """
    wanted = text.strip().lower()
    if not wanted:
        return []
    airports = [match for match, _lat, _lon in load_airports(con)]

    rules = [
        lambda a: a.iata.lower() == wanted,
        lambda a: wanted.upper() in ABBREVIATIONS and a.city.lower() == ABBREVIATIONS[wanted.upper()].lower(),
        lambda a: a.city.lower() == wanted,
        lambda a: a.name.lower() == wanted,
        lambda a: len(wanted) >= 3 and wanted in a.name.lower(),
    ]
    for rule in rules:
        found = [a for a in airports if rule(a)]
        if found:
            return found  # already sorted by code
    return []


def resolve_region(name):
    """The states of a Census region or division, name in any case. Unknown -> ValueError."""
    wanted = name.strip().lower()
    for region, states in REGIONS.items():
        if region.lower() == wanted:
            return list(states)
    raise ValueError(f"Unknown region {name!r}. Use one of: {', '.join(sorted(REGIONS))}.")
