# Scoring method

How the app ranks airports as renovation candidates. The reasons for choosing a weighted score over other methods are in [decisions.md](decisions.md) (section 7.2).

## What the score is for

The firm asks "which airports should we invest in?". Answering needs a **ranked list**. The ranking comes from fixed formulas in Python, not from the AI, so:

- the same question always gives the same ranking;
- every rank can be explained and checked;
- the exam requirement for deterministic scoring is met.

The AI only reads the result and explains it.

## The idea

An airport is a strong renovation candidate when **both** are true:

1. **Demand is growing**: more passengers each year.
2. **The airport is already under strain**: full planes, delays because the airport or airspace is too busy, long waits to take off.

Growth without strain means the airport still has room. Strain without growth may fix itself. Both together means new capacity will be used.

**Stated assumption:** "profitable" is approximated by this demand pressure, because no public source has renovation cost or airport revenue.

## 1. The measures

| # | Measure | Formula | Table(s) | Weight |
|---|---|---|---|---|
| **Demand** | | | | **40%** |
| D1 | Long-term growth | (passengers 2025 − passengers 2019) ÷ passengers 2019 | `route_traffic` | 20% |
| D2 | Recent growth | (enplanements 2025 − enplanements 2024) ÷ enplanements 2024 | `enplanements` | 20% |
| **Strain** | | | | **60%** |
| S1 | How full planes are (load factor) | passengers ÷ seats, departures in 2025 | `route_traffic` | 20% |
| S2 | Airport/airspace delay | NAS delay minutes ÷ arriving flights, 2025 | `airport_delays` | 15% |
| S3 | Taxi-out time | average minutes from gate to takeoff, 2025 | `airport_delays` | 10% |
| S4 | Runway load | all departures in 2025 (passenger and cargo) ÷ number of open runways | `route_traffic`, `airports` | 15% |

**Why strain weighs more (60%):** growth only matters when the airport is running out of room.

**NAS** (National Airspace System) is the delay cause meaning "the airport or its airspace was too busy", for example too many planes landing at once or a closed runway. It is the only delay cause that points at missing capacity; the others are the airline's fault, weather, a late incoming plane, or security.

**Limit of S3:** the data gives only the total time from gate to takeoff. Part of it is driving to the runway, not waiting in line, so large airports score higher partly because they are large. That is why S3 has the smallest weight and is never used alone.

**Why S4 counts cargo flights:** cargo planes use the same runways. At Anchorage 54% of departures are cargo, so counting passenger flights only would hide most of its runway load.

**Why S2 is per flight, not a share:** "NAS share of all delay" makes a quiet airport with 3 delays a year, 2 of them NAS, look 67% congested. Minutes per flight measures how much congestion each passenger actually feels.

## 2. Grades (0–100)

The measures have different units (%, minutes, ratios), so each is turned into a **percentile grade** compared with all US airports that pass the filter. A grade of 80 means "higher than 80% of US airports".

Grades are always national, even when the question is about one region. A New England airport's grade means the same in every answer.

## 3. Final score

```
final_score = 0.20·D1 + 0.20·D2 + 0.20·S1 + 0.15·S2 + 0.10·S3 + 0.15·S4
```

using the **grades** of each measure. Higher means a stronger candidate; airports are ranked by this number.

The weights are **settings**. A follow-up such as "what if growth matters more?" reruns the formula with new weights and the agent shows whether the ranking changes.

## 4. Filters and missing data

- **Size filter:** at least **100,000 enplanements in 2025**. Below that, a few new flights look like huge growth.
- **Missing delay data:** On-Time data covers only airports served by the larger US airlines. If an airport has no delay data, S2 and S3 are skipped, the remaining weights are scaled up to total 100%, and the answer says "scored without delay data".
- **Any other missing measure** (for example no runway data, or no 2019 traffic): the same rule. The measure is skipped, the other weights are scaled up, and the answer lists which measure was missing. No airport is dropped for a gap in its data.
- **Flags:** plain-word notes next to the score, e.g. "planes over 85% full" or "NAS delays in the top 10% nationally", to help the agent explain.

## 5. Where the score lives

**Nothing is stored in the database.** When a question needs a ranking, Python builds a temporary table, sends the requested rows to the AI (at most 25, see [tools.md](tools.md)), and discards it:

| Column group | Example columns | Purpose |
|---|---|---|
| Raw measures | `growth_long_pct`, `load_factor`, `nas_min_per_flight`, … | The real numbers |
| Grades | `growth_long_grade`, `load_factor_grade`, … | 0–100 per measure, so the AI can explain *why* |
| Result | `final_score`, `rank`, `flags` | The ranking |

It is not stored because it depends on settings (weights, filters) that can change during the chat, and recalculating takes milliseconds.

## 6. Tools that use it

`rank_airports` ranks by `final_score` (or any other measure), and `airport_profile` shows one airport's raw measures and grades. The two halves of the score are also shown on their own: `demand_score` (D1, D2) and `strain_score` (S1–S4, weights rescaled to total 100%). `strain_score` is the summary number for congestion questions. Full tool list: [tools.md](tools.md).
