# Database schema

Two separate databases:

1. **Airport data**: the DuckDB file `airports.duckdb`, below.
2. **Conversations**: the SQLite file `chat.sqlite`, at the end of this file.

## Part 1: airport data (`airports.duckdb`)

Built once by the loader and then only read by the app. Decisions behind it are in [decisions.md](decisions.md) (sections 6, 7.6, 7.7).

All airport codes are IATA codes (see 7.6). Primary keys yes, foreign keys no (see 7.7). **Scores are not stored**: they are calculated per question, because weights and filters can change during the chat.

**`airports`**: one row per airport (~679 rows). Source: OurAirports, with runways folded in.

| Column | Example | Meaning |
|---|---|---|
| `iata` (PK) | `SFO` | 3-letter airport code |
| `name`, `city` | San Francisco Intl, San Francisco | |
| `state` | `CA` | Used for region filters such as New England |
| `lat`, `lon` | 37.62, -122.38 | Location |
| `size_class` | large / medium / small | OurAirports label |
| `runway_count` | 4 | Stand-in for physical capacity |
| `longest_runway_ft` | 11870 | |

**`enplanements`**: one row per airport per year (2023–2025). Source: FAA.

| Column | Example | Meaning |
|---|---|---|
| `iata`, `year` (PK) | `SFO`, 2025 | |
| `enplanements` | 25000000 | Passengers who boarded |
| `hub_type` | L / M / S / N | FAA size group |

**`route_traffic`**: one row per airline × route × month × aircraft type (2019, 2024, 2025; ~1.7M rows). Source: BTS T-100 Segment, All Carriers, stored almost as downloaded so unexpected follow-up questions can still be answered.

| Column | Meaning |
|---|---|
| `year`, `month` | |
| `origin`, `dest`, `dest_country` | Route; `dest_country` gives international share |
| `carrier` | Airline |
| `aircraft_type` | |
| `departures`, `seats`, `passengers`, `freight_lbs` | Monthly totals for the route |
| `distance_mi` | Used for long-haul (3,000+ miles) |
| `is_passenger` | True if the flight carried at least one passenger |

No natural primary key (BTS can report the same combination twice); the loader checks totals instead.

**`airport_delays`**: one row per airport × month × direction (2025; ~10K rows). Source: BTS On-Time, reduced from ~3 GB of single flights to totals while loading.

| Column | Meaning |
|---|---|
| `iata`, `year`, `month`, `direction` (PK) | `direction` = `dep` or `arr` |
| `flights`, `cancelled`, `delayed_15` | Counts; delayed = 15+ minutes late |
| `avg_taxi_min` | Taxi-out for departures, taxi-in for arrivals |
| `nas_delay_min`, `carrier_delay_min`, `weather_delay_min`, `late_aircraft_delay_min`, `security_delay_min` | Delay minutes by cause (on arrival rows, where BTS records causes) |

**`data_sources`**: one row per source, so every answer can state its data period.

| Column | Example |
|---|---|
| `source` (PK), `url` | BTS T-100 Segment, … |
| `period` | 2019, 2024, 2025 |
| `loaded_at`, `row_count` | |

## Part 2: conversations (`chat.sqlite`)

The only data the app writes. Kept on a Railway disk that survives deploys. Decisions: [decisions.md](decisions.md) (7.9, 7.10). How it is used: [agent.md](agent.md).

**`conversations`**: one row per chat.

| Column | Example | Meaning |
|---|---|---|
| `id` (PK) | `c7f3a9e2-…` | Long random ID; the browser keeps only this |
| `created_at` | 2026-10-30 11:02 | |
| `last_active_at` | 2026-10-30 11:15 | Updated every turn |

**`messages`**: one row per step of a chat (a question, a tool request, a tool result or an answer).

| Column | Example | Meaning |
|---|---|---|
| `conversation_id`, `seq` (PK) | `c7f3a9e2-…`, 3 | Which chat, and the step's position. Steps are sent back to the AI in this order. |
| `role` | `user` / `assistant` / `tool` | Who wrote the step |
| `content` | text, or the tool result as JSON | |
| `tool_calls` | `[{"id":"t1","name":"rank_airports","args":{...}}]` | JSON; only on an `assistant` step that asks for tools |
| `tool_call_id` | `t1` | Only on a `tool` step; links the result to its request (the AI service rejects a history without this link) |
| `model` | the model name | Only on `assistant` steps |
| `input_tokens`, `output_tokens` | 1840, 210 | Only on `assistant` steps; tokens are the units the AI service charges by |
| `cost_usd` | 0.0031 | Only on `assistant` steps, when OpenRouter reports it; otherwise empty |
| `created_at` | | |

**Example**: one exam question stored as 4 steps:

```
seq 1  user       "What is the unmet flight demand at SFO and why?"
seq 2  assistant  tool_calls: [{id: t1, name: unmet_demand, args: {airports: ["SFO"]}}]
seq 3  tool       tool_call_id: t1, content: {data: {...}, about: {...}}
seq 4  assistant  "SFO is short of about 150,000 to 1,060,000 seats a year ..."
```

A follow-up adds steps 5, 6, … and the AI sees steps 1–4, including the SFO numbers.

No automatic deletion of old chats in version 1.
