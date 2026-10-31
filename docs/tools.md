# Agent tools

The tools are the only way the AI gets data. Reasons for each choice are in [decisions.md](decisions.md) (7.13, 7.15, 7.16–7.18). How the loop calls them: [agent.md](agent.md). The score formula: [scoring.md](scoring.md).

## How a tool call works

The AI never writes or sends a query. It sends a **request**: a tool name and a few settings.

```json
{ "tool": "rank_airports",
  "settings": { "states": ["TX"], "sort_by": "growth_short", "top_n": 5 } }
```

1. Our agent loop (Python) reads the request.
2. Python **checks the settings**: known airport codes, known states/regions, known measure names, numbers within limits. If a setting is wrong, the AI gets an error that lists the allowed values, and nothing runs.
3. Python runs **SQL written in advance** inside that tool. The AI's values only fill in the blanks (`state = ?`).
4. Python returns a small result (`data` + `about`, see [agent.md](agent.md)) to the AI, which writes the answer.

The AI can only choose **which** tool and **which values**. It cannot change a query, read other tables, or write to the database.

## Designed for any question, not only the exam examples

The four exam questions are examples. The tools are general building blocks over **one shared list of measures**, so most questions an investor would ask are a tool call or a combination of two or three (the loop allows up to 5 rounds).

Questions that need data we did not load (ticket prices, terminal size, gates, airport finances) get the fixed "no data" message, never a guess.

## The shared measure list

Every measure is calculated per airport for **2025** unless stated, and can be shown with a **national grade** (0–100 percentile among airports with 100,000+ enplanements, as in [scoring.md](scoring.md)).

| Group | Measure | Formula | Source table |
|---|---|---|---|
| Size | `enplanements` | Passengers who boarded (FAA) | `enplanements` |
| | `passengers`, `departures`, `seats` | Departing totals, passenger flights | `route_traffic` |
| Growth | `growth_short` (D2) | Enplanements 2024 → 2025 | `enplanements` |
| | `growth_long` (D1) | T-100 passengers 2019 → 2025 | `route_traffic` |
| Crowding | `load_factor` (S1) | Passengers ÷ seats | `route_traffic` |
| | `nas_delay_per_flight` (S2) | Airspace/airport delay minutes ÷ arriving flights | `airport_delays` |
| | `taxi_out_min` (S3) | Average minutes from gate to takeoff | `airport_delays` |
| | `departures_per_runway` (S4) | All departures (passenger and cargo) ÷ open runways | `route_traffic`, `airports` |
| | `late_share` | Departures 15+ minutes late ÷ departures | `airport_delays` |
| | `cancel_rate` | Cancelled ÷ scheduled departures | `airport_delays` |
| Flight mix | `long_haul_share` | Passenger departures of 3,000+ miles (adjustable) ÷ passenger departures | `route_traffic` |
| | `international_share` | Passenger departures to another country ÷ passenger departures | `route_traffic` |
| | `cargo_share` | Departures without passengers ÷ all departures | `route_traffic` |
| Airline dependence | `top_airline_share` | Departures by the biggest airline ÷ passenger departures | `route_traffic` |
| Unmet demand | `missing_seats_pct` | Missing seats ÷ seats offered (method below) | `route_traffic` |
| Score | `score`, `demand_score`, `strain_score` | [scoring.md](scoring.md) | all |

**Known limits, stated in the `about` part when used:**
- Delay measures (S2, S3, `late_share`, `cancel_rate`) cover only domestic flights by the larger US airlines; small airports may have none.
- `taxi_out_min` is the total time from gate to takeoff, so part of it is the distance to the runway, not the queue. Big airports score higher partly for that reason.
- `top_airline_share` uses the airline that **operates** the flight. A regional airline flying for a major (e.g. SkyWest for United) counts separately, so dependence on a major can be understated.

## The tools

### 1. `find_airports`
Finds airports in our list.

| Input | Meaning |
|---|---|
| `text` | Name, city or code: "Santa Ana", "LA", "BOS" |
| `states` / `region` | Two-letter states, or a region name (below) |
| `size` | FAA hub size: large / medium / small / non-hub |
| `near_airport`, `within_miles` | Airports within a distance of another airport in our list |

Output: code, name, city, state, size. Several matches → all are returned and the AI picks one. No match → "airport not found". This is the name resolver ([agent.md](agent.md)).

Every other tool also accepts an airport code or a name, and Python turns it into a code before running (agent.md, step 3), using the same name resolver. It must find exactly one airport; if it finds several, the AI gets their codes and picks one (implementation plan P25, P28). So "SFO" or "Santa Ana" needs no `find_airports` call first; `find_airports` is for unclear names ("LA"), places and regions.

**Size** is the FAA hub size of 2025 (implementation plan P26); airports with no FAA hub size for 2025 have no size.

**Regions** use the US Census Bureau regions and divisions (e.g. *New England* = CT, ME, MA, NH, RI, VT; *South*, *Midwest*, *West*, *Pacific*, …), so every region has a published, checkable definition.

### 2. `rank_airports`
Ranks airports by any measure.

| Input | Default | Limit |
|---|---|---|
| `states` / `region` / `size` | all US | |
| `sort_by` | `score` | any measure in the list |
| `order` | highest first | |
| `weights` | scoring.md weights | only with `score`; must total 100% |
| `min_enplanements` | 100,000 | |
| `top_n` | 10 | at most 25 |

Output: one row per airport with the sorted measure, its grade, its `national_rank` (place among all US airports in the size filter) and its `region_rank` (place among the airports that match the filters, so the AI never counts ranks itself), and (for `score`) the six measure grades and the flags. Every result that holds grades (this tool, `airport_profile`, `unmet_demand`) also says in `about` what a grade means: a higher grade = a higher value; for strain measures, more strain. Details: implementation-plan.md P71.

Added after a review of the question run (P75, P76, P78), so the AI copies the meaning instead of working it out:
- `measure_label`: the plain name of the sorted measure, e.g. "Final score (demand 40% + strain 60% by default)".
- `level` on every row: the level word of its grade (high = 67+, low = 33 or less, else middle; none for the score sorts); for `score` also `levels`, one word per measure grade.
- `demand_points` and `strain_points` on every row: how many points each measure adds to the demand and strain halves of the score. They add up to that half's score, so the measure with the most points is the biggest reason for it.
Examples: "Which New England airports are strong candidates for terminal expansion?", "10 most delayed airports", "rank again with growth at 60%".

### 3. `airport_profile`
Every measure, with its national grade, for **1 to 5 airports** side by side, plus the score and flags.
Examples: "Compare congestion at LAX and SNA", "Tell me about Nashville", "Why is BTV ranked 3rd?".

Output: per airport, each measure as {`value`, `grade`, `level`} (the level word as in `rank_airports`), the final score with `demand_score` and `strain_score`, `demand_points` and `strain_points` (default weights; empty for an airport under the size filter, which has no score), the national rank, the flags, and the `congestion` block below (P75, P76).

**Congestion** means the crowding measures: `departures_per_runway`, `nas_delay_per_flight`, `taxi_out_min`, `late_share`, `cancel_rate`. The summary number is `strain_score`, the strain half of the ranking score, so a congestion answer and a ranking answer use the same rules (decisions 7.18).

### 4. `traffic_trend`
One measure over time for 1–5 airports, or the total for a region.

| Input | Allowed |
|---|---|
| `measure` | `passengers`, `departures`, `seats`, `load_factor` (2019, 2024, 2025, by month); `enplanements` (2023–2025, by year); delay measures (2025, by month) |
| `by` | `year` or `month` |

Examples: "Has Denver recovered since 2019?", "Which months are busiest at Orlando?".

### 5. `route_mix`
Splits one airport's departures into groups.

| Input | Allowed | Default |
|---|---|---|
| `group_by` | `destination`, `country`, `airline`, `distance_band`, `aircraft_size` | `destination` |
| `passengers_only` | true / false | true |
| `long_haul_miles` | 500–6,000 | 3,000 |
| `year` | 2019, 2024, 2025 | 2025 |
| `top_n` | at most 25 | 10 |

Output: departures, seats and passengers per group with their share, plus `long_haul_share`, `international_share` and `cargo_share`. `aircraft_size` is by seats per flight: regional (under 100), single-aisle (100–229), wide-body (230+).
Examples: "What % of flights out of Anchorage are long-haul?", "How dependent is Charlotte on one airline?".

### 6. `delay_causes`
Delay minutes for 1–5 airports, split by cause: airline, weather, airspace/airport (NAS), late incoming plane, security. Totals and minutes per flight; by month if asked. 2025, arriving flights (where BTS records causes).
Example: "Why are flights at Newark late?".

### 7. `unmet_demand`
An estimate of the seats airlines would sell if they flew more, for 1–5 airports. Method below.
Example: "What is the unmet flight demand at SFO, and why?".

Output: per airport, the 2025 passengers, seats and load factor; `estimates`, one per target (80%, 85%, and an optional custom one), each with missing seats, missing flights, `months_over_target` (the months that miss seats at that target, with their load factor and missing seats) and `annual_vs_target`, a ready-made sentence such as "The 2025 load factor (79.2%) is below the 80% target; 1 month is above it: Jul." (P77); and the `why`: load factor by month, delay minutes by cause, and `runway_and_taxi` cells {`value`, `grade`, `level`}.

### 8. `data_info`
No input. Sources, periods loaded, load date, scope (679 US airports with scheduled service; territories excluded), and what we do not have.

### 9. `live_status`
Today's FAA delays and closures for one airport. Optional context, **never part of any score**. If the FAA feed is down, the tool says so.

## Unmet demand: how it becomes an amount

No dataset counts people who wanted to fly and couldn't. We estimate it from **how full planes are**: when planes are more full than a target on average, some people could not get a seat on the flight they wanted, especially at peak times.

For each month of 2025, passenger flights departing the airport:

```
seats needed  = passengers ÷ target load factor
missing seats = seats needed − seats offered   (0 if negative)
```

The 12 months are added up. Months, not the year, because a busy summer is hidden in a yearly average. Missing flights = missing seats ÷ average seats per flight at that airport.

**The target is an assumption, and the result depends on it strongly**, so the tool reports a **range: 80% (high estimate) to 85% (low estimate)**. A user can ask for another target (70%–95%).

Checked on real 2025 T-100 data, SFO:

| Target | Missing seats | ≈ Missing flights |
|---|---|---|
| 80% | 1,063,000 | 6,200 |
| 85% | 150,000 | 880 |

SFO planes were 82.3% full over the year, and 89.5% in June. At 85%, SFO ranks 2nd of the 105 airports with 1M+ passengers (after EWR); at 80%, 8th, because at 80% most large airports (88 of 105) show some missing seats.

**Ranking uses `missing_seats_pct`** (missing seats ÷ seats offered), not the raw amount, so big airports don't win only by being big.

**The "why"** comes in the same result: the load factor by month, the delay-cause split (airspace/airport vs weather), and the national grades of `departures_per_runway` and `taxi_out_min`. Together these show whether airlines are not adding flights because the airport cannot take more.

**Stated in every answer:** this is an estimate; it counts only people who would have flown at today's prices; monthly averages hide daily peaks, so the true peak shortage is likely larger.

## Limits that apply to every tool

- At most 25 rows and 5 airports per call, so results stay small. Everything a tool returns is sent to the AI, and we pay for every word it reads.
- Grades are national, even when the question is about one region.
- Each result carries its `about` part (data period, filters, missing data, assumptions).
