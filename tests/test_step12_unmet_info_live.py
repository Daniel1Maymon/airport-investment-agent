"""Step 12 tests: the `unmet_demand`, `data_info` and `live_status` tools.

What the builder must follow (names the tests rely on)
------------------------------------------------------
app/tools/unmet.py, app/tools/info.py and app/tools/live.py, all imported by
app/tools/__init__.py, so `import app.tools` registers `unmet_demand`, `data_info`
and `live_status`. The tests call them through `run_tool(con, name, settings)`.

unmet_demand (P50-P52)
* Settings: airports (1-5 names or codes); target_load_factor (optional fraction,
  0.70-0.95, else an error with allowed [0.7, 0.95]).
* data = {"airports": [entries]} in the order asked, a repeated code once.
  Entry keys: iata, name, city, state, passengers, seats_offered, load_factor,
  estimates, why.
* estimates: [{"target", "label", "missing_seats", "missing_flights",
  "missing_seats_pct"}] for 0.80 ("high estimate"), 0.85 ("low estimate"), then a
  custom target ("custom target"), not repeated when it is 0.80 or 0.85.
* why = {"by_month": [{"month", "passengers", "seats", "load_factor"}],
         "delay_causes": {cause: {"minutes", "share"}} or None,
         "runway_and_taxi": {"departures_per_runway": {"value", "grade"},
                             "taxi_out_min": {"value", "grade"}}}.

data_info (P53): no settings. data = {"sources", "scope", "gaps"}.

live_status (P54): setting `airport`. `live_status(con, settings, fetch=None)` in
app/tools/live.py; with no fetch it calls the module-level `fetch_faa_status()`, looked
up at call time, so these tests replace it with monkeypatch (no network).
data = {"airport", "feed_available", "updated", "events"}.

The exact `about` texts are read at run time from docs/implementation-plan.md (P35,
P52, P53, P54) and docs/tools.md ("Known limits"), not copied here.

HAND-WORKED NUMBERS (tiny dataset, tests/fixtures/TINY_DATA.md, 2025)
====================================================================
Departing passenger flights only (cargo ANC-SDF is left out). Each airport has two
months, January (1) and July (7). missing = passengers / target - seats, 0 if negative.

BOS: 2 routes x 10 departures x 100 seats; 40 departures, 4,000 seats a year.
  Jan 1,400 / 2,000 = 0.70     Jul 1,768 / 2,000 = 0.884    year 3,168 / 4,000 = 0.792
  80%: Jan 1,400/0.8 = 1,750 < 2,000 -> 0; Jul 1,768/0.8 = 2,210 - 2,000 = 210 -> 210
  85%: Jan 0; Jul 1,768/0.85 = 2,080 - 2,000 = 80 -> 80
  seats per flight 4,000 / 40 = 100 -> flights 2.1 (80%), 0.8 (85%)
  pct 210 / 4,000 = 0.0525 (80%), 80 / 4,000 = 0.02 (85%)
  75% (custom): Jan 1,400/0.75 = 1,866.67 < 2,000 -> 0;
                Jul 1,768/0.75 = 2,357.333 - 2,000 = 357.333
                flights 357.333 / 100 = 3.57333; pct 357.333 / 4,000 = 0.0893333
MHT: 16 departures, 2,000 seats -> 125 seats per flight.
  80%: Jan 840/0.8 = 1,050 - 1,000 = 50; Jul 960/0.8 = 1,200 - 1,000 = 200 -> 250
       flights 250 / 125 = 2.0; pct 250 / 2,000 = 0.125
  85%: Jan 840/0.85 = 988.24 < 1,000 -> 0; Jul 960/0.85 = 1,129.412 - 1,000 = 129.412
       flights 129.412 / 125 = 1.03529; pct 129.412 / 2,000 = 0.0647059
ANC: passenger departures 40 (SEA 20 + ATL 20), seats 4,000 -> 100 seats per flight.
     (Counting the 50 cargo departures too would give 4,000 / 90 = 44.4 and wrong flights.)
  80%: 1,728/0.8 = 2,160 - 2,000 = 160 per month -> 320; flights 3.2; pct 0.08
  85%: 1,728/0.85 = 2,032.94 - 2,000 = 32.94 per month -> 65.88; flights 0.6588
LAX: 60 departures, 6,000 seats -> 100 seats per flight.
  80%: 2,460/0.8 = 3,075 - 3,000 = 75 per month -> 150; flights 1.5
  85%: 2,460/0.85 = 2,894.1 < 3,000 -> 0; flights 0

Delay causes (arr rows, Jan + Jul, same each month):
  BOS: nas 800x2 = 1,600; carrier 600x2 = 1,200; weather 300x2 = 600;
       late_aircraft 700x2 = 1,400; security 0. Total 4,800.
       shares 1,600/4,800 = 1/3; 1,200/4,800 = 0.25; 600/4,800 = 0.125;
              1,400/4,800 = 0.291667; 0.
  LAX: nas 2,000; carrier 1,400; weather 200; late_aircraft 1,600; security 20.
       Total 5,220. nas 2,000/5,220 = 0.383142; security 20/5,220 = 0.0038314.
  BTV: no delay rows -> None.

Runway and taxi (P29 grades, 100,000 pool of 6: BOS MHT BTV LAX SNA ANC; see
test_step10_rank_profile.py for the full grade table):
  BOS departures_per_runway 40/4 = 10, grade 2/6 = 33.3; taxi_out_min 20, grade 3/5 = 60.0
  BTV departures_per_runway 10/2 = 5, grade 0/6 = 0.0;  taxi_out_min None, grade None

data_sources (4 rows, loaded_at 2026-10-31 12:00:00), sorted by source:
  BTS On-Time 24 rows; BTS T-100 Segment 66; FAA enplanements 21; OurAirports 7.

LIVE SAMPLE (tests/fixtures/raw/faa_status_sample.xml)
======================================================
A short copy of the real feed format (2026-10-31), with only its two event formats.
  Update_Time: "Sat Oct 31 16:18:30 2026 GMT"
  General Arrival/Departure Delay Info:
    BOS Arrival   16 minutes - 30 minutes Increasing  "ZBW / WX:Low Visibility"
    SNA Departure 31 minutes - 45 minutes Decreasing  "TM Initiatives:MIT:WX"
    LAX Departure 16 minutes - 30 minutes Increasing  "TM Initiatives:MIT:VOL"
  Airport Closures:
    LAX  start "May 27 at 18:26 UTC."  reopen "May 28 at 16:00 UTC."
         reason of 213 characters (cut to the first 200)
    SAN  not in the tiny dataset; never shown.
  ANC, MHT, BTV, BHB: no events.
"""

import json
import re
from pathlib import Path

import httpx
import pytest

import app.tools  # noqa: F401  (must register unmet_demand, data_info, live_status)
from app.measures import compute_measures
from app.tools.base import TOOLS, run_tool

UNMET = "unmet_demand"
INFO = "data_info"
LIVE = "live_status"

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "implementation-plan.md"
TOOLS_DOC = ROOT / "docs" / "tools.md"
SAMPLE = Path(__file__).resolve().parent / "fixtures" / "raw" / "faa_status_sample.xml"

ABOUT_KEYS = {"data_period", "filters", "missing", "assumptions"}
UNMET_KEYS = {"iata", "name", "city", "state", "passengers", "seats_offered", "load_factor", "estimates", "why"}
ESTIMATE_KEYS = {"target", "label", "missing_seats", "missing_flights", "missing_seats_pct", "months_over_target", "annual_vs_target"}
CAUSES = {"nas", "weather", "carrier", "late_aircraft", "security"}
ROUND = 0.051  # tolerance for grades rounded to 1 decimal

DELAY_TYPE = "General Arrival/Departure Delay Info"
CLOSURE_TYPE = "Airport Closures"
LAX_CLOSURE_REASON = (
    "!LAX 05/277 LAX AD AP CLSD TO NON SKED TRANSIENT GA ACFT EXC 24HR PPR CTC ATLANTIC AVIATION "
    "310-258-9884 OR SIGNATURE AVIATION 310-410-9605 PPR REQUESTS MUST INCLUDE ACFT TYPE AND TAIL "
    "NUMBER 2605271826-2705281600"
)  # 213 characters

# Hand-read from the sample file (see the table above).
BOS_DELAY = {
    "type": DELAY_TYPE,
    "reason": "ZBW / WX:Low Visibility",
    "direction": "Arrival",
    "min": "16 minutes",
    "max": "30 minutes",
    "trend": "Increasing",
}
SNA_DELAY = {
    "type": DELAY_TYPE,
    "reason": "TM Initiatives:MIT:WX",
    "direction": "Departure",
    "min": "31 minutes",
    "max": "45 minutes",
    "trend": "Decreasing",
}
LAX_DELAY = {
    "type": DELAY_TYPE,
    "reason": "TM Initiatives:MIT:VOL",
    "direction": "Departure",
    "min": "16 minutes",
    "max": "30 minutes",
    "trend": "Increasing",
}
LAX_CLOSURE = {
    "type": CLOSURE_TYPE,
    "reason": LAX_CLOSURE_REASON[:200],  # cut to 200: ends "...TAIL NUMBER 26052718"
    "start": "May 27 at 18:26 UTC.",
    "reopen": "May 28 at 16:00 UTC.",
}


# ---- helpers -------------------------------------------------------------------


def _ok(result):
    """The result of a tool that ran; fails with the error dict otherwise."""
    assert isinstance(result, dict), result
    assert "error" not in result, result
    assert set(result) == {"data", "about"}, result
    assert set(result["about"]) == ABOUT_KEYS, result["about"]
    return result


def _assert_error(result, allowed):
    assert isinstance(result, dict) and set(result) == {"error", "allowed"}, result
    assert isinstance(result["error"], str) and result["error"]
    assert result["allowed"] == allowed, result


def _unmet(con, airports, **settings):
    return _ok(run_tool(con, UNMET, {"airports": airports, **settings}))


def _entry(result, code):
    found = [e for e in result["data"]["airports"] if e["iata"] == code]
    assert len(found) == 1, result["data"]
    return found[0]


def _estimates(entry):
    """The estimates list of one airport, each checked for its keys."""
    for est in entry["estimates"]:
        assert set(est) == ESTIMATE_KEYS, est
    return entry["estimates"]


def _approx(expected, tol=1e-6):
    return None if expected is None else pytest.approx(expected, abs=tol)


def _check_estimate(est, target, label, seats, flights, pct):
    assert est["target"] == pytest.approx(target)
    assert est["label"] == label
    assert est["missing_seats"] == _approx(seats, 1e-3)
    assert est["missing_flights"] == _approx(flights, 1e-4)
    assert est["missing_seats_pct"] == _approx(pct, 1e-6)


def _norm(text):
    """Drop markdown marks (` and *) and squeeze spaces, so doc and result compare."""
    return " ".join(text.replace("`", "").replace("*", "").split())


def _plan_quotes(decision):
    """Every "quoted" text in one row of the decision table (e.g. "P52")."""
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {decision} |"):
            return re.findall(r'"([^"]+)"', line)
    raise AssertionError(f"{decision} not found in {PLAN}")


def _plan_text(decision, words, start=False):
    """The one quoted text in a decision row that contains (or, with start, begins with) `words`."""
    found = [q for q in _plan_quotes(decision) if (q.startswith(words) if start else words in q)]
    assert len(found) == 1, (decision, words, found)
    return found[0]


def _limit(keyword):
    """One bullet of tools.md "Known limits", found by its keyword."""
    text = TOOLS_DOC.read_text(encoding="utf-8")
    section = text.split("**Known limits", 1)[1].split("\n## ", 1)[0]
    bullets = [line[2:].strip() for line in section.splitlines() if line.startswith("- ")]
    found = [b for b in bullets if keyword in b]
    assert len(found) == 1, (keyword, bullets)
    return _norm(found[0])


def _national(n=100_000):
    return _norm(_plan_text("P35", "Grades are national").replace("N+", f"{n:,}+"))


def _texts(items):
    return [_norm(item) for item in items]


# -- live_status helpers --


def _sample_xml():
    return SAMPLE.read_text(encoding="utf-8")


class FakeFetch:
    """A stand-in for fetch_faa_status: returns the given text, or raises the given error."""

    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.text


def _live(con, monkeypatch, airport, fake):
    # string target: the module is imported here, so a missing module fails only this test
    monkeypatch.setattr("app.tools.live.fetch_faa_status", fake)
    result = _ok(run_tool(con, LIVE, {"airport": airport}))
    assert fake.calls >= 1  # the module-level fetch was looked up at call time (P54)
    return result


def _has(event, expected):
    """True when `event` holds every expected key with that value (other keys allowed)."""
    return all(event.get(key) == value for key, value in expected.items())


def _assert_events(events, expected):
    """`events` are exactly the expected ones, compared key by key, in any order."""
    assert len(events) == len(expected), events
    for want in expected:
        assert sum(1 for e in events if _has(e, want)) == 1, (want, events)


def _no_events_text(code):
    return _plan_text("P54", "No FAA delays").replace("X", code)


def _feed_down_text():
    return _plan_text("P54", "not available right now")


def _context_only_text():
    return _plan_text("P54", "context only")


# ---- the listed tests ------------------------------------------------------------


# 1
def test_unmet_range_80_and_85(tiny_db):
    result = _unmet(tiny_db, ["BOS", "MHT"])
    entries = result["data"]["airports"]
    assert [e["iata"] for e in entries] == ["BOS", "MHT"]  # the order asked

    bos = entries[0]
    assert set(bos) == UNMET_KEYS, bos
    assert bos["name"] == "General Edward Lawrence Logan International Airport"
    assert bos["city"] == "Boston"
    assert bos["state"] == "MA"
    assert bos["passengers"] == pytest.approx(3168)  # 1,400 + 1,768
    assert bos["seats_offered"] == pytest.approx(4000)  # 2,000 x 2 months
    assert bos["load_factor"] == pytest.approx(0.792)  # 3,168 / 4,000

    # Always both ends of the range, 80% first (decisions 7.17, P50, P51)
    ests = _estimates(bos)
    assert len(ests) == 2, ests
    # 80%: Jul 1,768/0.8 - 2,000 = 210; 210/100 = 2.1 flights; 210/4,000 = 0.0525
    _check_estimate(ests[0], 0.80, "high estimate", 210, 2.1, 0.0525)
    # 85%: Jul 1,768/0.85 - 2,000 = 80; 80/100 = 0.8 flights; 80/4,000 = 0.02
    _check_estimate(ests[1], 0.85, "low estimate", 80, 0.8, 0.02)

    mht = entries[1]
    ests = _estimates(mht)
    assert len(ests) == 2, ests
    # 80%: 50 + 200 = 250; 250/125 = 2.0; 250/2,000 = 0.125
    _check_estimate(ests[0], 0.80, "high estimate", 250, 2.0, 0.125)
    # 85%: Jan 0; Jul 960/0.85 - 1,000 = 129.412; /125 = 1.03529; /2,000 = 0.0647059
    _check_estimate(ests[1], 0.85, "low estimate", 960 / 0.85 - 1000, (960 / 0.85 - 1000) / 125,
                    (960 / 0.85 - 1000) / 2000)


def test_unmet_85_pct_equals_compute_measures(tiny_db):
    """At 0.85, missing_seats_pct is the same number as the shared measure list (P51)."""
    measures = compute_measures(tiny_db)
    for code in ["BOS", "MHT", "BTV", "LAX", "SNA", "ANC"]:
        entry = _entry(_unmet(tiny_db, [code]), code)
        at_85 = [e for e in _estimates(entry) if e["target"] == pytest.approx(0.85)]
        assert len(at_85) == 1, entry["estimates"]
        assert at_85[0]["missing_seats_pct"] == pytest.approx(measures[code]["missing_seats_pct"], abs=1e-9)


def test_unmet_accepts_names_and_shows_a_repeated_code_once(tiny_db):
    # "Boston" is the exact city of BOS (P25 rule 3); "bos" is the same airport again
    result = _unmet(tiny_db, ["Boston", "bos", "ANC"])
    assert [e["iata"] for e in result["data"]["airports"]] == ["BOS", "ANC"]


def test_unmet_too_many_airports_refused(tiny_db):
    result = run_tool(tiny_db, UNMET, {"airports": ["BOS", "MHT", "BTV", "LAX", "SNA", "ANC"]})
    _assert_error(result, [1, 5])


# 2
def test_unmet_custom_target(tiny_db):
    result = _unmet(tiny_db, ["BOS"], target_load_factor=0.75)
    ests = _estimates(_entry(result, "BOS"))
    assert len(ests) == 3, ests
    _check_estimate(ests[0], 0.80, "high estimate", 210, 2.1, 0.0525)
    _check_estimate(ests[1], 0.85, "low estimate", 80, 0.8, 0.02)
    # 75%: Jan 1,400/0.75 = 1,866.67 < 2,000 -> 0; Jul 1,768/0.75 - 2,000 = 357.333
    #      flights 357.333/100 = 3.57333; pct 357.333/4,000 = 0.0893333
    custom = 1768 / 0.75 - 2000
    _check_estimate(ests[2], 0.75, "custom target", custom, custom / 100, custom / 4000)


def test_unmet_custom_target_at_the_edges(tiny_db):
    # 0.70 and 0.95 are allowed (P50)
    low = _estimates(_entry(_unmet(tiny_db, ["BOS"], target_load_factor=0.70), "BOS"))
    assert len(low) == 3
    # 70%: Jan 1,400/0.7 = 2,000 - 2,000 = 0; Jul 1,768/0.7 - 2,000 = 525.714
    custom = 1768 / 0.70 - 2000
    _check_estimate(low[2], 0.70, "custom target", custom, custom / 100, custom / 4000)

    high = _estimates(_entry(_unmet(tiny_db, ["BOS"], target_load_factor=0.95), "BOS"))
    assert len(high) == 3
    # 95%: Jan 1,400/0.95 = 1,473.7 < 2,000; Jul 1,768/0.95 = 1,861.1 < 2,000 -> 0
    _check_estimate(high[2], 0.95, "custom target", 0, 0, 0)


@pytest.mark.parametrize("target", [0.80, 0.85])
def test_unmet_custom_target_80_or_85_not_repeated(tiny_db, target):
    ests = _estimates(_entry(_unmet(tiny_db, ["BOS"], target_load_factor=target), "BOS"))
    assert [e["label"] for e in ests] == ["high estimate", "low estimate"]
    assert [e["target"] for e in ests] == [pytest.approx(0.80), pytest.approx(0.85)]


# 3
@pytest.mark.parametrize("target", [0.69, 0.96, 0.5, 1.0, 85])
def test_unmet_target_outside_70_95_refused(tiny_db, target):
    # 85 is a percent, not a fraction (P11): refused too
    result = run_tool(tiny_db, UNMET, {"airports": ["BOS"], "target_load_factor": target})
    _assert_error(result, [0.7, 0.95])


# 4
def test_unmet_missing_flights(tiny_db):
    result = _unmet(tiny_db, ["ANC", "LAX", "MHT"])

    # ANC: 4,000 seats / 40 passenger departures = 100 seats per flight (cargo left out)
    anc = _estimates(_entry(result, "ANC"))
    # 80%: 160 x 2 = 320 seats -> 320/100 = 3.2 flights; 320/4,000 = 0.08
    _check_estimate(anc[0], 0.80, "high estimate", 320, 3.2, 0.08)
    # 85%: (1,728/0.85 - 2,000) x 2 = 65.88 -> 0.6588 flights
    anc_85 = (1728 / 0.85 - 2000) * 2
    _check_estimate(anc[1], 0.85, "low estimate", anc_85, anc_85 / 100, anc_85 / 4000)

    # LAX: 6,000 seats / 60 departures = 100; 80%: 75 x 2 = 150 -> 1.5; 85%: 0 -> 0
    lax = _estimates(_entry(result, "LAX"))
    _check_estimate(lax[0], 0.80, "high estimate", 150, 1.5, 150 / 6000)
    _check_estimate(lax[1], 0.85, "low estimate", 0, 0, 0)

    # MHT: 2,000 seats / 16 departures = 125; 80%: 250 / 125 = 2.0
    mht = _estimates(_entry(result, "MHT"))
    assert mht[0]["missing_flights"] == pytest.approx(2.0)


# 5
def test_unmet_why_has_monthly_load_factor_and_delay_split(tiny_db):
    result = _unmet(tiny_db, ["BOS", "LAX"])
    why = _entry(result, "BOS")["why"]
    assert set(why) == {"by_month", "delay_causes", "runway_and_taxi"}, why

    # by month, in month order: Jan 1,400/2,000 = 0.70; Jul 1,768/2,000 = 0.884
    months = why["by_month"]
    assert isinstance(months, list)
    assert [m["month"] for m in months] == [1, 7]
    for m in months:
        assert set(m) == {"month", "passengers", "seats", "load_factor"}, m
    assert months[0]["passengers"] == pytest.approx(1400)
    assert months[0]["seats"] == pytest.approx(2000)
    assert months[0]["load_factor"] == pytest.approx(0.70)
    assert months[1]["passengers"] == pytest.approx(1768)
    assert months[1]["seats"] == pytest.approx(2000)
    assert months[1]["load_factor"] == pytest.approx(0.884)

    # delay causes: arr rows, Jan + Jul; total 1,600 + 1,200 + 600 + 1,400 + 0 = 4,800
    causes = why["delay_causes"]
    assert set(causes) == CAUSES, causes
    expected = {
        "nas": (1600, 1600 / 4800),  # 800 x 2; 1/3
        "carrier": (1200, 0.25),  # 600 x 2; 1,200 / 4,800
        "weather": (600, 0.125),  # 300 x 2; 600 / 4,800
        "late_aircraft": (1400, 1400 / 4800),  # 700 x 2; 0.291667
        "security": (0, 0.0),
    }
    for cause, (minutes, share) in expected.items():
        assert set(causes[cause]) == {"minutes", "share"}, causes[cause]
        assert causes[cause]["minutes"] == pytest.approx(minutes)
        assert causes[cause]["share"] == pytest.approx(share, abs=1e-6)

    # LAX: total 2,000 + 1,400 + 200 + 1,600 + 20 = 5,220
    lax = _entry(result, "LAX")["why"]["delay_causes"]
    assert lax["nas"]["minutes"] == pytest.approx(2000)
    assert lax["nas"]["share"] == pytest.approx(2000 / 5220, abs=1e-6)  # 0.383142
    assert lax["security"]["minutes"] == pytest.approx(20)
    assert lax["security"]["share"] == pytest.approx(20 / 5220, abs=1e-6)  # 0.0038314

    # runway and taxi, with national grades (P29, pool of 6 / 5 with delay data)
    rt = why["runway_and_taxi"]
    assert set(rt) == {"departures_per_runway", "taxi_out_min"}, rt
    assert set(rt["departures_per_runway"]) == {"value", "grade", "level"}
    assert rt["departures_per_runway"]["value"] == pytest.approx(10)  # 40 / 4 runways
    assert rt["departures_per_runway"]["grade"] == pytest.approx(33.3, abs=ROUND)  # 2/6
    assert rt["taxi_out_min"]["value"] == pytest.approx(20)
    assert rt["taxi_out_min"]["grade"] == pytest.approx(60.0, abs=ROUND)  # 3/5


def test_unmet_btv_has_no_delay_causes(tiny_db):
    result = _unmet(tiny_db, ["BTV"])
    btv = _entry(result, "BTV")
    assert btv["why"]["delay_causes"] is None
    rt = btv["why"]["runway_and_taxi"]
    assert rt["departures_per_runway"]["value"] == pytest.approx(5)  # 10 / 2
    assert rt["departures_per_runway"]["grade"] == pytest.approx(0.0, abs=ROUND)  # lowest of 6
    assert rt["taxi_out_min"]["value"] is None
    assert rt["taxi_out_min"]["grade"] is None
    # about.missing says so (text not fixed by the plan: it names BTV)
    assert any("BTV" in note for note in result["about"]["missing"]), result["about"]

    # BTV's planes are never over 80% (Jan 0.70, Jul 0.756): both estimates 0
    ests = _estimates(btv)
    _check_estimate(ests[0], 0.80, "high estimate", 0, 0, 0)
    _check_estimate(ests[1], 0.85, "low estimate", 0, 0, 0)


# 6
def test_unmet_caveats_in_about(tiny_db):
    about = _unmet(tiny_db, ["BOS"])["about"]
    assert about["data_period"] == _plan_text("P52", "2025 by month", start=True)
    assumptions = _texts(about["assumptions"])
    expected = [
        _norm(_plan_text("P52", "This is an estimate")),
        _norm(_plan_text("P52", "today's prices")),
        _norm(_plan_text("P52", "Monthly averages")),
        _norm(_plan_text("P52", "Range:", start=True)),
        _national(),
        _limit("Delay measures"),
        _limit("taxi_out_min` is"),
    ]
    for text in expected:
        assert text in assumptions, (text, assumptions)
    # BOS has every kind of data: nothing missing
    assert about["missing"] == []


def test_unmet_result_survives_json(tiny_db):
    result = _unmet(tiny_db, ["BOS", "BTV"], target_load_factor=0.75)
    assert json.loads(json.dumps(result)) == result


# 7
def test_data_info_reads_data_sources_table(tiny_db):
    result = _ok(run_tool(tiny_db, INFO, {}))
    data = result["data"]
    assert set(data) == {"sources", "scope", "gaps"}, data
    sources = data["sources"]
    # sorted by source name; row_count as in TINY_DATA.md "Table data_sources"
    assert [s["source"] for s in sources] == ["BTS On-Time", "BTS T-100 Segment", "FAA enplanements", "OurAirports"]
    for s in sources:
        assert set(s) == {"source", "url", "period", "loaded_at", "row_count"}, s
        # loaded_at is text (so the result survives json.dumps); 2026-10-31 12:00:00
        assert isinstance(s["loaded_at"], str), s
        assert "2026-10-31" in s["loaded_at"]
        assert "12:00" in s["loaded_at"]
    by_name = {s["source"]: s for s in sources}
    assert by_name["BTS On-Time"]["row_count"] == 24  # 6 airports x 2 months x 2 directions
    assert by_name["BTS T-100 Segment"]["row_count"] == 66  # 11 routes x 3 years x 2 months
    assert by_name["FAA enplanements"]["row_count"] == 21  # 7 airports x 3 years
    assert by_name["OurAirports"]["row_count"] == 7
    assert by_name["BTS On-Time"]["period"] == "2025"
    assert by_name["BTS T-100 Segment"]["period"] == "2019, 2024, 2025"
    assert by_name["FAA enplanements"]["period"] == "2023, 2024, 2025"
    assert by_name["OurAirports"]["period"] == "current"
    assert by_name["OurAirports"]["url"] == "https://davidmegginson.github.io/ourairports-data/airports.csv"
    assert by_name["FAA enplanements"]["url"].endswith("arp-cy2025-commercial-service-enplanements.xlsx")

    assert json.loads(json.dumps(result)) == result


# 8
def test_data_info_states_scope_and_gaps(tiny_db):
    data = _ok(run_tool(tiny_db, INFO, {}))["data"]
    scope = data["scope"]
    assert set(scope) == {"airports", "text"}, scope
    assert scope["airports"] == 7  # count of the tiny airports table, not a fixed 679
    assert scope["text"] == _plan_text("P53", "US airports with scheduled")

    gaps = data["gaps"]
    assert isinstance(gaps, list) and all(isinstance(g, str) and g for g in gaps), gaps
    # P53's fixed list (its wording is not fixed by the plan; checked by keyword)
    text = " ".join(gaps).lower()
    for word in ["terminal", "gate", "ticket price", "financ", "domestic", "live", "score"]:
        assert word in text, (word, gaps)


def test_data_info_takes_no_settings(tiny_db):
    _assert_error(run_tool(tiny_db, INFO, {"airports": ["BOS"]}), [])


# 9
def test_live_status_parses_sample(tiny_db, monkeypatch):
    sample = _sample_xml()
    assert LAX_CLOSURE_REASON in sample and len(LAX_CLOSURE_REASON) > 200

    result = _live(tiny_db, monkeypatch, "LAX", FakeFetch(sample))
    data = result["data"]
    assert set(data) == {"airport", "feed_available", "updated", "events"}, data
    assert data["airport"] == "LAX"
    assert data["feed_available"] is True
    assert data["updated"] == "Sat Oct 31 16:18:30 2026 GMT"
    # LAX has one event of each format; SAN's closure is not LAX's
    _assert_events(data["events"], [LAX_DELAY, LAX_CLOSURE])
    closure = [e for e in data["events"] if e["type"] == CLOSURE_TYPE][0]
    assert len(closure["reason"]) == 200  # 213 characters cut to 200

    assert _norm(_context_only_text()) in _texts(result["about"]["assumptions"])
    assert _no_events_text("LAX") not in result["about"]["missing"]
    assert json.loads(json.dumps(result)) == result

    # BOS: one arrival delay
    bos = _live(tiny_db, monkeypatch, "BOS", FakeFetch(sample))["data"]
    _assert_events(bos["events"], [BOS_DELAY])
    # SNA by name (P28): "Santa Ana" is SNA's city
    sna = _live(tiny_db, monkeypatch, "Santa Ana", FakeFetch(sample))["data"]
    assert sna["airport"] == "SNA"
    _assert_events(sna["events"], [SNA_DELAY])


def test_live_status_parses_the_one_line_layout(tiny_db, monkeypatch):
    """The real feed comes as one line, with no spaces between tags; same events expected."""
    compact = re.sub(r">\s+<", "><", _sample_xml())
    assert "\n" not in compact.strip()
    lax = _live(tiny_db, monkeypatch, "LAX", FakeFetch(compact))["data"]
    _assert_events(lax["events"], [LAX_DELAY, LAX_CLOSURE])
    bos = _live(tiny_db, monkeypatch, "BOS", FakeFetch(compact))["data"]
    _assert_events(bos["events"], [BOS_DELAY])


def test_live_status_takes_a_fetch_function(tiny_db):
    """P54: live_status(con, settings, fetch=None); a passed fetch is used instead of the feed."""
    tool = TOOLS[LIVE]
    settings = tool.settings_model(airport="BOS")
    fake = FakeFetch(_sample_xml())
    result = _ok(tool.fn(tiny_db, settings, fetch=fake).to_dict())
    assert fake.calls == 1
    assert result["data"]["feed_available"] is True
    _assert_events(result["data"]["events"], [BOS_DELAY])


# 10
def test_live_status_airport_with_no_events(tiny_db, monkeypatch):
    result = _live(tiny_db, monkeypatch, "ANC", FakeFetch(_sample_xml()))
    data = result["data"]
    assert data["airport"] == "ANC"
    assert data["feed_available"] is True
    assert data["updated"] == "Sat Oct 31 16:18:30 2026 GMT"
    assert data["events"] == []
    # "No FAA delays or closures reported for X right now." with X = ANC
    assert _no_events_text("ANC") in result["about"]["missing"], result["about"]
    assert _feed_down_text() not in result["about"]["missing"]
    assert _norm(_context_only_text()) in _texts(result["about"]["assumptions"])


# 11
@pytest.mark.parametrize(
    "fake",
    [
        FakeFetch(error=httpx.ConnectTimeout("timed out")),
        FakeFetch(error=httpx.ConnectError("connection refused")),
        FakeFetch(
            error=httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=httpx.Request("GET", "https://nasstatus.faa.gov/api/airport-status-information"),
                response=httpx.Response(503),
            )
        ),
        FakeFetch("<AIRPORT_STATUS_INFORMATION><Update_Time>Sat Oct 31"),  # broken XML (cut off)
        FakeFetch(""),  # empty reply
    ],
    ids=["timeout", "connect-error", "http-503", "broken-xml", "empty"],
)
def test_live_status_feed_down_message(tiny_db, monkeypatch, fake):
    fake.calls = 0
    # a normal result, never an error and never a crash (P54)
    result = _live(tiny_db, monkeypatch, "BOS", fake)
    data = result["data"]
    assert data["airport"] == "BOS"
    assert data["feed_available"] is False
    assert data["events"] == []
    assert _feed_down_text() in result["about"]["missing"], result["about"]
    # the feed being down must not claim there are no delays
    assert _no_events_text("BOS") not in result["about"]["missing"]
    assert _norm(_context_only_text()) in _texts(result["about"]["assumptions"])
    assert json.loads(json.dumps(result)) == result


def test_three_tools_registered():
    assert {UNMET, INFO, LIVE} <= set(TOOLS)


# ---- real data -----------------------------------------------------------------------


@pytest.mark.realdata
def test_real_sfo_unmet_demand(real_db):
    result = _unmet(real_db, ["SFO"])
    sfo = _entry(result, "SFO")
    ests = _estimates(sfo)
    # docs/tools.md "Unmet demand": SFO 2025, 1,063,000 at 80%, 150,000 at 85% (within 1%)
    assert ests[0]["target"] == pytest.approx(0.80)
    assert ests[0]["missing_seats"] == pytest.approx(1_063_000, rel=0.01)
    assert ests[1]["target"] == pytest.approx(0.85)
    assert ests[1]["missing_seats"] == pytest.approx(150_000, rel=0.01)
    print("\nSFO unmet demand 2025:")
    for est in ests:
        print(
            f"  {est['label']} ({est['target']:.0%}): {est['missing_seats']:,.0f} seats, "
            f"{est['missing_flights']:,.0f} flights, {est['missing_seats_pct']:.2%} of seats"
        )
    print("  load factor by month:", [(m["month"], round(m["load_factor"], 3)) for m in sfo["why"]["by_month"]])
    print("  delay causes:", sfo["why"]["delay_causes"])
    print("  runway and taxi:", sfo["why"]["runway_and_taxi"])
    assert json.loads(json.dumps(result)) == result


@pytest.mark.realdata
def test_real_live_status_one_call(real_db):
    """One real call to the FAA feed. The feed may really be down, so only the shape is checked."""
    result = _ok(run_tool(real_db, LIVE, {"airport": "SFO"}))
    data = result["data"]
    assert data["airport"] == "SFO"
    assert isinstance(data["feed_available"], bool)
    assert isinstance(data["events"], list)
    print("\nFAA live status, SFO:", data, result["about"]["missing"])
