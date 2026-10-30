# Design: Airport Investment Intelligence Agent

A chat agent for a US airport-modernization investment firm. It finds and compares airports where renovation is most likely to pay off, based on growth in flights and passengers, and explains why.

This is the short version. Every decision, with the options considered, is in [docs/decisions.md](docs/decisions.md).

## 1. The approach in one paragraph

Public aviation data is downloaded **once** into a small analysis database. **Python** calculates every number, score and ranking with fixed formulas. The **AI** understands the question, chooses which of nine tools to call, and explains the results in plain words. It never writes SQL, never touches the database, and never states a number that a tool did not return. Every tool result carries its own data period, filters, missing data and assumptions, and the AI must pass them on.

## 2. Architecture

```
 ONE-TIME (on a laptop)                    ALWAYS RUNNING
 Public data sources                       Vercel              Railway
 (OurAirports, FAA,                        ┌────────────┐ HTTP ┌──────────────────────────┐
  BTS T-100, On-Time)                      │ Chat page  │ ───► │ FastAPI                  │
         │                                 │ (keeps only│ ◄─── │  ├─ Agent loop ◄─► AI    │
         ▼                                 │ the chat   │      │  │  (OpenRouter)         │
   Loader script                           │ ID)        │      │  ├─ 9 tools + resolver   │
         │                                 └────────────┘      │  ├─ Scoring (Python)     │
         ▼                                                     │  ├─ airports.duckdb (RO) │
   airports.duckdb ── copied into the container ─────────────► │  └─ chat.sqlite (disk)   │
                                                               └──────────────────────────┘
```

| Part | Job | Detail |
|---|---|---|
| Loader | Downloads 4 public sources, reduces ~3 GB of single flights to monthly totals per airport, converts FAA codes to IATA, checks totals | [data-sources.md](docs/data-sources.md), [schema.md](docs/schema.md) |
| Scoring | Measures → national percentile grades → weighted score | [scoring.md](docs/scoring.md) |
| Tools | 9 general tools over one shared list of measures | [tools.md](docs/tools.md) |
| Agent loop | Our own loop: AI asks for tools, Python runs them, up to 5 rounds per question | [agent.md](docs/agent.md) |
| Conversation store | Every step of every chat in SQLite, with token cost per AI reply | [schema.md](docs/schema.md) |
| Chat page + API | Plain HTML/JS; 3 backend addresses; tables and "How I got this" built by Python | [api.md](docs/api.md) |

**Data:** OurAirports (airports, runways), FAA passenger boardings (2023–2025), BTS T-100 (every airline's monthly flights, seats, passengers and distance per route; 2019, 2024, 2025), BTS On-Time (every domestic flight's delay, cause and taxi time; 2025). All verified by real download. **Scope:** 679 US airports with scheduled service; territories excluded.

## 3. Scoring method

An airport is a strong renovation candidate when **demand is growing** and **the airport is already under strain**. Growth alone means there is still room; strain alone may fix itself.

| | Measure | Weight |
|---|---|---|
| **Demand 40%** | D1 passenger growth 2019 → 2025 · D2 boardings growth 2024 → 2025 | 20% · 20% |
| **Strain 60%** | S1 how full planes are · S2 airspace/airport delay minutes per flight · S3 taxi-out time · S4 departures per runway | 20% · 15% · 10% · 15% |

- Each measure becomes a **national percentile grade** (0–100) among airports with 100,000+ boardings, so measures in different units can be combined, and a grade means the same in every answer.
- Score = weighted sum of grades. Weights are settings: "what if growth matters more?" reruns the formula.
- No delay data for an airport → S2 and S3 are skipped and the weights rescaled, and the answer says so.
- Deterministic: the same question always gives the same ranking.

**Unmet demand** has no direct data, so it is estimated as **missing seats**: per month, passengers ÷ target load factor − seats offered. The result depends strongly on the target, so it is reported as a **range** (80% to 85%). Real 2025 data, SFO: **150,000–1,060,000 missing seats a year**. Rankings use missing seats as a % of seats, so size alone doesn't win.

**Congestion** uses the strain measures plus % late and cancellations, summarized by the strain half of the score, so a congestion answer never contradicts a ranking answer.

## 4. Where AI is used, and where it is not

| AI does | Python does |
|---|---|
| Understands the question | Every number, grade, score and ranking |
| Chooses tools and their settings | Checks every setting before running |
| Picks an airport from our list when a name isn't an exact match | Runs SQL written in advance, values passed separately |
| Writes the answer, including the caveats | Builds the tables and the "How I got this" steps shown on the page |

Safety does not depend on the AI obeying: the database is read-only, the chat history is kept by the server, no secret is in anything the AI sees, and the numbers in tables never pass through the AI ([agent.md](docs/agent.md), Safety).

## 5. Key tradeoffs

| Choice | Instead of | Why | Cost we accept |
|---|---|---|---|
| Load once, then read | Live API calls per question | Same question → same answer; investment data is monthly/yearly anyway | Data is as fresh as the last load |
| DuckDB file in the container | Hosted PostgreSQL | Fast analysis, $0, nothing to run | Refreshing data means a redeploy |
| Weighted percentile score | Rule tiers, ML, capacity-gap model | Explainable and adjustable; no labels or gate data exist | Weights are a judgment, so they are stated and adjustable |
| Fixed tools, no AI-written SQL | AI writes SQL | Safe and correct by construction | Questions outside the tools get "no data" |
| Own agent loop with memory | Single-shot pipeline, agent SDK | Follow-ups and multi-step questions; the whole loop is readable | Up to 6 AI calls per question, capped |
| SQLite on a disk for chats | Browser-held history, PostgreSQL | Server owns the record; nothing extra to run | Moves to PostgreSQL if we run more than one server |
| Whole answer at once | Streaming | Simpler everywhere | A 5–20 s wait with "Working…" |

## 6. Assumptions, uncertainty and scope

- **"Profitable" is approximated by demand pressure.** No public source has renovation cost or airport revenue.
- **No terminal size or gate data exists publicly.** Runways and traffic are used as stand-ins, and answers say so.
- **Delay data covers only domestic flights by the larger US airlines.**
- **Definitions change answers.** Example: 31% of Anchorage departures fly 3,000+ miles, but only 2.8% of passenger flights do (most long flights there are cargo). Every answer states the definition it used.
- Data period: 2025 (2019 as the pre-COVID baseline). Every answer states it.

## 7. Testing

- **`pytest`** on a tiny made-up dataset with known answers: scoring, unmet-demand math, name resolver, tool setting checks.
- **A question script** that runs the exam questions, follow-ups, other investor questions, no-data questions and prompt-injection attempts through the real agent, and saves every answer with its tools and cost.

## 8. Future work

Streaming answers; AI-written SQL behind a read-only checker for questions outside the tools; ticket prices and regional population growth as extra demand signals; scheduled data refreshes (then PostgreSQL).
