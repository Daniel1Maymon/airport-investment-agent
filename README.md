# Airport Investment Intelligence Agent

A chat agent that helps a US airport-modernization investment firm find the
airports where renovation will most likely pay off.

It loads public US aviation data once (FAA, BTS, OurAirports), scores every
airport with a fixed, explainable formula in Python, and answers questions
like *"Which New England airports are strong candidates for terminal
expansion?"* in a chat. The AI chooses tools and explains the results. It
never writes SQL and never makes up a number.

> **Status:** design complete, code not started. Everything below is the
> design. The short design document for reviewers is [DESIGN.md](DESIGN.md).

## The whole system in one picture

```
  Public data (downloaded once)
  OurAirports · FAA boardings · BTS T-100 · BTS On-Time
        │
        │  loader script, run on a laptop
        │  ~3 GB of single flights → monthly totals per airport
        ▼
 ┌───────────────────────────────┐
 │ airports.duckdb               │
 │  airports, enplanements,      │
 │  route_traffic,               │
 │  airport_delays, data_sources │
 └───────────────┬───────────────┘
                 │  copied into the container, opened READ-ONLY
                 ▼
 ┌───────────────────────────────┐        ┌──────────────────┐
 │ FastAPI backend   (Railway)   │ ◄────► │ AI (OpenRouter)  │
 │  agent loop                   │        │ picks tools,     │
 │  9 tools + name resolver      │        │ writes the answer│
 │  scoring (plain Python)       │        └──────────────────┘
 │  chat.sqlite (chat history,   │
 │   on a Railway disk)          │
 └───────────────┬───────────────┘
                 │  JSON over HTTP: POST /chat, GET /chat/{id}, GET /health
                 ▼
 ┌───────────────────────────────┐
 │ Chat page          (Vercel)   │
 │ plain HTML + JS, voice input  │
 │ keeps only the chat ID        │
 └───────────────────────────────┘
```

## One question, step by step

*"What is the unmet flight demand at SFO, and why?"*

The numbers below come from the real 2025 BTS T-100 data, checked during
design. The flow is the design.

```
 1. Chat page sends   { conversation_id, message }
 2. Backend loads the earlier steps of this chat from chat.sqlite
 3. AI reads the question and asks for a tool:
       unmet_demand    { airports: ["SFO"] }
 4. Python checks the settings and runs SQL written in advance:
       per month of 2025:  missing seats = passengers ÷ target − seats (min 0)
       target 80% → 1,063,000 missing seats (≈ 6,200 flights)
       target 85% →   150,000 missing seats (≈   880 flights)
       why: planes 82.3% full over the year, 89.5% in June;
            delay causes and runway load grades
       about: data period 2025, the target is an assumption,
              monthly averages hide daily peaks
 5. AI writes the answer from these numbers only, with the caveats
 6. Python builds the tables and the "How I got this" steps
 7. Every step is saved to chat.sqlite, with the AI cost
```

## The parts

| Part | What it does | Design |
|---|---|---|
| Loader | Downloads 4 public sources, reduces them to monthly totals, converts FAA codes to IATA, checks totals | [data-sources.md](docs/data-sources.md), [schema.md](docs/schema.md) |
| Scoring | Measures → national percentile grades → weighted score (Demand 40%, Strain 60%) | [scoring.md](docs/scoring.md) |
| Tools | 9 general tools over one shared list of measures | [tools.md](docs/tools.md) |
| Agent loop | AI asks for tools, Python runs them, at most 5 rounds per question | [agent.md](docs/agent.md) |
| Chat history | Every step of every chat in SQLite, with cost per AI reply | [schema.md](docs/schema.md) |
| API + chat page | 3 addresses; tables built by Python straight from tool results | [api.md](docs/api.md) |

## How the data serves the investment question

Every table answers one investor question: **which airports need renovation
most, and will the money pay off?** The answer has two halves:

- **Demand:** are more people coming?
- **Strain:** is the airport already too crowded?

An airport that scores high on both is a strong renovation candidate.

```
                         "Where should we invest in renovation?"
                                         │
                ┌────────────────────────┴────────────────────────┐
                ▼                                                 ▼
       DEMAND (40% of score)                            STRAIN (60% of score)
     "Are more people coming?"                     "Is it already overcrowded?"
                │                                                 │
     ┌──────────┴──────────┐                ┌──────────┬──────────┼──────────────┐
     ▼                     ▼                ▼          ▼          ▼              ▼
 D1 passenger         D2 boardings      S1 planes   S2 delay   S3 taxi-out   S4 flights
 growth 2019→2025     growth 2024→2025  how full    from air-  time (waiting per runway
                                        (load       traffic    to take off)
                                        factor)     crowding
     │                     │                │          │          │              │
     ▼                     ▼                ▼          ▼          ▼              ▼
 route_traffic        enplanements     route_traffic  airport_   airport_    route_traffic
                                                      delays     delays      + airports
```

The **load factor** is the share of seats that are filled: a plane with 100
seats and 85 passengers has a load factor of 85%.

| Table | What it tells the investor |
|---|---|
| `airports` | **Where** it is and **how big**: city, state, runways. Needed for regions ("New England") and for flights per runway. |
| `enplanements` | **How many people board** each year. Growth means rising demand. Also the size filter: under 100,000 boardings a year is too small to rank. |
| `route_traffic` | **Flights, seats and passengers** per route, airline and month. Shows whether planes are full (no room left) and how traffic grew since 2019, plus long-haul and international routes. |
| `airport_delays` | **Signs of crowding**: delays caused by air-traffic and airport congestion (NAS delay), and long waits to take off. One row per airport, month and direction (leaving or arriving). |
| `data_sources` | **Where the numbers came from** and which period, so every answer states its source. |

The four exam questions use the tables like this:

```
 Q1 "Best New England airports for terminal expansion?"
     → airports (region) + all score measures → ranking

 Q2 "Compare congestion at LAX and SNA"
     → airport_delays (delays, taxi time) + route_traffic (how full, flights per runway)

 Q3 "What % of Anchorage flights are long-haul?"
     → route_traffic (distance of each route)

 Q4 "How much unmet demand at SFO, and why?"
     → route_traffic: months where planes were too full = seats missing
     → airport_delays: the "why" (crowding, delays)
```

The full chain:

```
 public data files ──► 5 tables ──► measures ──► score ──► AI explains it in chat
   (loader)           airports.duckdb  (Python)    (Python)
```

## The AI agent

```
 question ─► ask the AI ─► tool requests? ── yes ─► Python checks settings,
                ▲                                     runs fixed SQL,
                │                                     returns data + "about"
                └──────────── results ◄───────────────────┘
                                 (at most 5 rounds)
              final text ─► answer + tables + steps ─► chat page
```

| The AI does | Python does |
|---|---|
| Understands the question | Every number, grade, score and ranking |
| Chooses tools and settings | Checks every setting before running |
| Writes the answer and the caveats | Builds the tables shown on the page |

## Safety

The protections live in Python, not in the AI's instructions:

- The AI picks a tool and fills in values. It never writes SQL.
- The airport database is opened **read-only**.
- The server keeps the chat history; the browser sends only the chat ID.
- Tables on the page come straight from tool results, never through the AI.
- No secrets in anything the AI sees; errors show a fixed message.
- Question length, answer length and tool rounds are capped.

Details: [agent.md](docs/agent.md), Safety.

## Quick Start

Coming with the first code layer.

## Docs

| File | Contents |
|---|---|
| [DESIGN.md](DESIGN.md) | The short design document: scoring, tradeoffs, where AI is used |
| [docs/decisions.md](docs/decisions.md) | Every decision with options, tradeoffs and reasons |
| [docs/architecture.md](docs/architecture.md) | The six parts and how they connect |
| [docs/agent.md](docs/agent.md) | One chat turn, memory, AI rules, refusal messages, safety |
| [docs/tools.md](docs/tools.md) | The 9 tools, the measure list, unmet demand and congestion |
| [docs/api.md](docs/api.md) | The 3 addresses between the chat page and the backend |
| [docs/schema.md](docs/schema.md) | Database tables |
| [docs/scoring.md](docs/scoring.md) | The ranking formula |
| [docs/data-sources.md](docs/data-sources.md) | Source URLs and tested download methods |
