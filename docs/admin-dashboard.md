# Admin dashboard

A private page for the owner of the site: how the agent is used, what it costs, how often it refuses, which tools the AI picks, and one switch that turns the AI off. Decisions: [decisions.md](decisions.md) 7.26 and 7.27. Small details: [implementation-plan.md](implementation-plan.md) P122–P141. Built in Step 19.

## Why it exists

The agent is public and every answer costs money (the AI is paid per token). Three questions come up as soon as real people use it:

1. **What does it cost?** Per question and in total.
2. **What are people asking, and what did they get?** Real questions show gaps that our own question list (7.21) missed.
3. **Does the AI use the tools well?** If one of the nine tools is never picked, or a tool is picked for the wrong kind of question, the prompt or the tool description needs work.

The dashboard answers these from data the app already saves, plus one small log table. And if something goes wrong (a spending spike, a stream of abuse), one button stops all AI calls at once.

## What the page shows

```
[ Admin login: token box ]
────────────────────────────────────────────────────────────────
AI answering: ON                                    [ Turn off ]
[Questions] [Chats] [Visitors] [Refusal rate] [Cost $] [Cost per question] [Tokens] [Time p50 / p95]
Questions per day (last 30 days)      ▁▃▅▂▇▁▃
Refusals by cause                      Tools the AI picked
  airport_not_found ███                  rank_airports  ██████
  out_of_scope      ██                   unmet_demand   ███
Recent questions
  ▸ time | visitor | chat | question | answered / refused (cause) | tool names | cost
    (click a row: the answer, and the "How I got this" steps)
  ‹ Previous  [1] 2 3 4 5  Next ›   Page 1 of 5 · 136 questions   (30 per page)
  (click a column name to sort by it; click again to flip the order)
```

| Part | Where the numbers come from |
|---|---|
| **Questions**, **Chats** | `messages` rows with role `user`; rows in `conversations` |
| **Visitors** | different `visitor_id` values in `chat_events` (since the dashboard was deployed) |
| **Cost**, **Tokens**, **Cost per question** | `cost_usd`, `input_tokens`, `output_tokens` on `assistant` steps; cost per question = total cost ÷ questions |
| **Refusal rate**, **Refusals by cause**, **Time p50 / p95** | the new `chat_events` table (below). p50 = the middle time (half the questions were faster); p95 = 95 of 100 questions were faster than this |
| **Questions per day** | `messages` rows with role `user`, grouped by day (UTC), last 30 days, days with no questions shown as 0 |
| **Tools the AI picked** | the tool names inside `tool_calls` on `assistant` steps, counted |
| **Recent questions** | 30 per page, newest first unless sorted by another column (the server sorts all questions, then cuts the page; Refresh and the page buttons keep the choice; opening or reloading the page starts again with newest first). Each `user` step, with its chat ID and the chat's visitor ID (first 8 characters; the whole ID on hover), with the last `assistant` text of that turn, the tool steps of that turn (built by the same `build_steps` the chat page uses) and the turn's cost |

Everything is read from `chat.sqlite`. The airport database is not touched.

**Since when.** The `chat_events` table starts on the day the dashboard is deployed, so chats from before that day have no refusal cause and no time. The page says so next to those three numbers ("since <date>"). Questions, chats, cost, tokens, tools and recent questions cover all chats.

## The new data

Two small tables in `chat.sqlite`, added with `CREATE TABLE IF NOT EXISTS`. The two existing tables are not changed. Details: [schema.md](schema.md) part 3.

- **`chat_events`**: one row per `POST /chat` request: when, which chat, the result (`answered`, `refused` or `error`), the refusal cause, and how long it took. **The question text is not stored here**; it is already in `messages` for every question the agent ran, and a question refused before the agent (for example one over 1,000 characters) stays unsaved, as before (P82).
- **`app_settings`**: one row per setting the owner can change while the site runs. Version 1 has one: `ai_enabled`.

Why a log table at all: some refusals never reach `messages` (a question too long, "still answering", an unknown chat, no AI key) and neither do timeouts or crashes. Counting only `messages` would show a refusal rate lower than the real one.

## The AI on/off switch

- **Off** means `POST /chat` gives the existing "AI service is not available" refusal (`ai_unavailable`) before any AI call. No tokens are spent. Reloading old chats, `/health` and the airport data are not affected.
- The page sends the **wanted state** (`{"enabled": false}`), never "flip it". Pressing "off" twice leaves it off, and two open dashboards cannot undo each other by accident.
- The state lives in `chat.sqlite`, so it survives a redeploy, and every open dashboard shows the same state after a refresh.
- **No row means ON.** If the switch can't be read (for example a disk error), the chat also treats it as ON: a dashboard problem must never stop the chat (P134).

## Who can open it

- A new setting **`ADMIN_TOKEN`** (a long random password, set on Railway, never in git).
- Every admin address needs the header `Authorization: Bearer <token>`. A missing or wrong token gets HTTP 401 and only the word "unauthorized".
- **If `ADMIN_TOKEN` is not set, every admin request is refused.** Forgetting the setting locks the dashboard; it never opens it.
- The token is compared with `secrets.compare_digest`, which takes the same time whether the first or the last character is wrong, so the token can't be guessed one character at a time by timing the replies.
- The browser keeps the token in `sessionStorage` (forgotten when the tab is closed) and sends it only to the backend.
- CORS (the browser's list of which pages may call the backend, and what they may send) must now also allow the `Authorization` header. The allowed page address stays the same one Vercel address.

**Visitors.** The chat page makes a random ID once per browser (`crypto.randomUUID()`), keeps it in `localStorage`, and sends it with every question. "New chat" keeps the same ID, so one visitor's chats can be grouped. It is a random number: no name, no place. Private mode, a cleared browser or a second browser counts as a new visitor.

What we don't collect: no IP addresses and no countries. The dashboard doesn't need them, they are personal data, and a country needs an outside lookup service.

## The four admin addresses

All four need the token. Full request and reply format: [api.md](api.md) section 4.

| Address | What it does |
|---|---|
| `GET /admin/metrics` | The numbers, the per-day counts, the refusal causes and the tool counts |
| `GET /admin/events?limit=100` | The most recent questions, newest first (limit 1–500) |
| `GET /admin/ai` | The switch: `{"enabled": true, "updated_at": …, "note": …}` |
| `POST /admin/ai` | Set the switch: `{"enabled": false, "note": "cost check"}` |

## The page

- `web/admin.html` + `web/admin.js`, plain HTML and JavaScript like the chat page, on the same Vercel site at `/admin.html`. No chart library: the bars are plain HTML boxes with a width.
- Not linked from the chat page, and marked `noindex` so search engines skip it. This is not the protection (the token is); it only keeps the page out of sight.
- Everything from the server is shown as text, never as HTML (P95), because questions are written by strangers.
- A **Refresh** button reloads the numbers. No automatic refresh.
- Turning the AI **off** asks once more on the page ("Turn the AI off for everyone?") before sending.

## Keeping the live site safe

The site is already in use (the link was sent to a recruiter). The rules for this change, approved 2026-11-01 (decisions 7.27):

1. **Nothing goes live by itself.** The page (Vercel) and the backend (Railway) are updated only by deploy commands run on the laptop; a push or a merge on GitHub changes nothing online. Each deploy needs the user's yes.
2. **The chat keeps working even if the new parts fail.** Saving a log row is wrapped so an error is only written to the log; the chat answer still goes out. A switch that can't be read counts as ON.
3. **Small changes to the chat code.** `app/api.py` changes in three places only: the CORS header, the switch check, the log row. Everything else is new files.
4. **All tests pass first.** The existing tests, unchanged, plus the new ones.
5. **A full run on the laptop first.** Backend and both pages locally; the smoke test and the four exam questions.
6. **Old chats are kept.** Only new tables are added; nothing existing is changed or deleted.
7. **A way back.** Before deploying, write down the live Vercel deployment and Railway deployment. If anything looks wrong: `vercel rollback` and a redeploy of the old Railway deployment.
8. **A check right after.** The smoke test against the live address, and the four exam questions on the live page.
