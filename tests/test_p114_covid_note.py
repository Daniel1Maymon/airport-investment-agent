"""Tests for P114: answers that use 2019 explain why (COVID).

Growth since 2019 and yearly passenger trends use 2019 as the "before" year and skip
2020-2022. The tool's "about" notes say so in one fixed sentence (NOTE_COVID), and the AI
passes the notes on to the reader. Answers that do not use 2019 do not get the note.
"""

import app.tools  # noqa: F401  (fills the tool registry TOOLS)
from app.tools.base import run_tool
from app.tools.rank import NOTE_COVID


def assumptions(result):
    return result["about"]["assumptions"]


def test_note_names_2019_covid_and_the_skipped_years():
    assert "2019" in NOTE_COVID
    assert "COVID" in NOTE_COVID
    assert "2020" in NOTE_COVID and "2022" in NOTE_COVID


def test_ranking_by_score_has_the_covid_note(tiny_db):
    result = run_tool(tiny_db, "rank_airports", {})
    assert NOTE_COVID in assumptions(result)


def test_ranking_by_long_term_growth_has_the_covid_note(tiny_db):
    result = run_tool(tiny_db, "rank_airports", {"sort_by": "growth_long"})
    assert NOTE_COVID in assumptions(result)


def test_ranking_by_delays_only_has_no_covid_note(tiny_db):
    result = run_tool(tiny_db, "rank_airports", {"sort_by": "late_share"})
    assert NOTE_COVID not in assumptions(result)


def test_airport_profile_has_the_covid_note(tiny_db):
    result = run_tool(tiny_db, "airport_profile", {"airports": ["BOS"]})
    assert NOTE_COVID in assumptions(result)


def test_passenger_trend_has_the_covid_note(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"]})
    assert NOTE_COVID in assumptions(result)


def test_delay_trend_has_no_covid_note(tiny_db):
    result = run_tool(tiny_db, "traffic_trend", {"measure": "late_share", "airports": ["BOS"]})
    assert NOTE_COVID not in assumptions(result)
