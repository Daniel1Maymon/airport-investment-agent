# API between the chat page and the backend

The chat page (Vercel) talks to the backend (Railway) through three addresses. Decisions: [decisions.md](decisions.md) (7.22, 7.23). What happens inside one turn: [agent.md](agent.md).

## 1. `POST /chat`: send a message, get the answer

Request:

```json
{ "conversation_id": "c7f3a9e2-…",
  "message": "Which New England airports are strong candidates for terminal expansion?" }
```

`conversation_id` is left out on the first message; the backend starts a new chat and returns its ID. The page keeps only this ID.

Reply:

```json
{ "conversation_id": "c7f3a9e2-…",
  "answer": "The strongest candidates are …",
  "tables": [ { "title": "New England airports ranked by score",
                "columns": ["Airport", "Score", "Growth 2024→25", "Load factor"],
                "rows": [["MHT", 71, "+8.3%", "84%"]],
                "about": { "data_period": "2025", "filters": ["…"], "missing": [], "assumptions": ["…"] } } ],
  "steps": [ "Found airports in New England (6 states)",
             "Ranked airports by score, default weights" ],
  "refusal": null }
```

*(Numbers are examples of the format only.)*

| Field | Meaning |
|---|---|
| `answer` | The AI's text. Empty when the agent refuses. |
| `tables` | One per tool result of this turn, built by Python **straight from the tool result**, never through the AI, so table numbers cannot be changed by the AI (decisions 7.19). |
| `steps` | Plain-words list of the tools used and their settings, written by Python from the tool requests. The page shows it under the answer as "How I got this". It shows the real reasoning path, not the AI's description of it. |
| `refusal` | `null`, or `{ "cause": "airport_not_found", "message": "…" }` with the fixed message for that cause ([agent.md](agent.md)). |

## 2. `GET /chat/{conversation_id}`: reload a chat

Returns every question, answer, table and step list of the chat, in order, so the page can show it again after a reload. Nothing extra is stored: tables and steps are rebuilt from the saved tool requests and results in `chat.sqlite` ([schema.md](schema.md)). Unknown ID → the "chat not found" refusal.

## 3. `GET /health`

Returns `{"status": "ok"}` when the server is up and the airport database opens. Railway calls it to check the server.

## Rules

- **The whole answer at once (no streaming).** A turn with 2–3 tools takes about 5–20 seconds; the page shows "Working…" until the reply arrives. Streaming the text word by word is future work.
- **One message at a time per chat.** The page disables Send while waiting. If a second message for the same chat arrives anyway (e.g. a double click), the backend refuses it with "still answering your last question". One server, so an in-memory lock per chat is enough.
- **Only our Vercel page may call the backend** (CORS).
- **Question length:** at most 1,000 characters, refused before the AI sees it.
- **Answer length:** the AI is told to write at most about 800 words per answer, and each AI call has a token limit (4,000 tokens, which leaves room for the model's hidden "thinking"). Enough for a comparison with its caveats; too short to make the app a free writing tool. If an answer still reaches the limit, a fixed note says it was cut off (implementation plan P61, P68).
- **Time limit:** a whole turn may take at most 60 seconds; after that the "internal error" message is returned.
- **Voice** (exam bonus) needs nothing from the API: the browser turns speech into text and the page sends it like a typed message.
