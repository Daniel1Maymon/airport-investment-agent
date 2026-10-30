# Architecture

The parts of the system and how they connect. Reasons for each choice are in [decisions.md](decisions.md).

```
 ONE-TIME (on a laptop)                    ALWAYS RUNNING
 ──────────────────────                    ──────────────

 Public data sources                       Vercel              Railway
 (OurAirports, FAA,                        ┌────────────┐ HTTP ┌──────────────────────────┐
  BTS T-100, On-Time)                      │ Chat page  │ ───► │ FastAPI                  │
         │                                 │ (browser,  │ ◄─── │  ├─ Agent loop ◄─► AI    │
         ▼                                 │ keeps only │      │  │  (OpenRouter)         │
   Loader script                           │ the chat   │      │  ├─ Tools + name resolver│
         │                                 │ ID)        │      │  ├─ Scoring (Python)     │
         ▼                                 └────────────┘      │  ├─ airports.duckdb      │
   airports.duckdb ── copied into the Railway container ─────► │  │  (read only)          │
                                                               │  └─ chat.sqlite          │
                                                               │     (on a Railway disk)  │
                                                               └──────────────────────────┘
```

## The six parts

1. **Loader.** A script run once, outside the web app. Downloads the public data ([data-sources.md](data-sources.md)), reduces it to totals, translates airport codes, checks consistency, and writes one DuckDB file ([schema.md](schema.md), part 1).
2. **Scoring.** Plain Python reading the database. Computes the measures, grades and final score ([scoring.md](scoring.md)). No AI, so the same question always gives the same ranking.
3. **Tools.** Nine Python functions the AI may call, built over one shared list of measures so they answer any investor question our data supports, not only the exam examples: find, rank, profile/compare, trend over time, route mix, delay causes, unmet demand, data info, live status ([tools.md](tools.md)). The AI sends only a tool name and settings; Python checks them and runs SQL written in advance. A **name resolver** first turns names ("LA", "New England") into airport codes from our own list. Each tool returns the numbers plus an `about` part: data period, filters, missing data, assumptions.
4. **Agent loop.** Our own loop on OpenRouter. Each turn: load the chat so far → the AI asks for tools → Python runs them → results go back → repeat (at most 5 rounds) until the AI answers → save the new steps. Detail: [agent.md](agent.md).
5. **Conversation store.** The SQLite file `chat.sqlite` on a Railway disk that survives deploys ([schema.md](schema.md), part 2). The only thing the app writes. The browser keeps only the chat ID.
6. **Chat page.** Plain HTML + JavaScript on Vercel, calling the Railway backend over HTTP through three addresses ([api.md](api.md)) (backend must allow the Vercel origin, CORS). Voice input (exam bonus) possible via the browser's built-in speech recognition.

## Where AI is used

1. Understanding the question.
2. Choosing which tools to call, and with what settings.
3. Helping the name resolver, only by picking from our own airport list.
4. Writing the answer in plain words, including the assumptions and gaps the tools report.

All numbers and rankings come from Python.
