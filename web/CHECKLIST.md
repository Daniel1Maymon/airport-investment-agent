Step 17 hand checklist: checked by hand in a browser after the chat page is built (implementation plan, Step 17).

# Chat page: hand checklist

Each check says **how to do it** and **what you must see**. Tick the box when it passes and fill in the "Result:" line (pass / fail, and a short note if it fails).

Design: [docs/api.md](../docs/api.md), [docs/agent.md](../docs/agent.md) (refusal messages), implementation plan P92–P98.

## How to run locally

Open two terminals in the main project folder.

1. **Backend** (the Python server that answers questions), on port 8000:
   ```bash
   set -a; source .env; set +a; ALLOWED_ORIGIN=http://localhost:5500 .venv/bin/uvicorn --factory app.api:main_app --port 8000
   ```
   `ALLOWED_ORIGIN` is the one web address the backend accepts calls from. This browser rule is called **CORS**: the backend tells the browser which pages may call it, and the browser blocks every other page.
2. **Page**, on port 5500 (Python's built-in file server, serving the `web/` folder):
   ```bash
   .venv/bin/python -m http.server 5500 --directory web
   ```
3. Open **`http://localhost:5500`** in the browser. Use `localhost`, **not** `127.0.0.1`: CORS compares the address as exact text, so `127.0.0.1` is refused (P93).

Useful browser tool: **DevTools** (the browser's built-in developer panel, opened with F12 or Cmd+Option+I). Its **Application** tab shows **localStorage** (a small store inside the browser where the page keeps the chat ID between visits).

Use Chrome for the checks, unless a check says another browser.

---

## Checks from the plan (Step 17)

### 1. A question shows "Working…", then the answer, tables and steps
- [ ] **How:** type `Which New England airports are strong candidates for terminal expansion?` and press Send.
- **You must see:**
  - your question in the chat at once;
  - the text **Working…** while you wait (a turn takes about 5–20 seconds);
  - then "Working…" goes away and the answer text appears (not empty);
  - below it at least one table, with a title (for example "Airports ranked by …") and column headings;
  - a list titled **How I got this** with plain-words lines such as `Ranked airports (region: New England; …)`.
- Result:

### 2. Send is disabled while waiting
- [ ] **How:** send any question (for example `Compare congestion at LAX and SNA.`). While "Working…" shows, try to click Send again.
- **You must see:** the Send button looks disabled (greyed out) and a click does nothing: no second question appears in the chat. When the answer arrives, Send works again.
- Result:

### 3. A refusal shows its message, not an empty answer
- [ ] **How (a), too long:** paste a question longer than 1,000 characters (for example the sentence `Tell me about Boston airport. ` repeated 40 times, which is 1,200 characters) and press Send.
- **You must see (a):** this exact message, shown where the answer would be:
  `Your question is too long (over 1,000 characters). Please shorten it.`
  No empty answer bubble, no table.
- [ ] **How (b), out of scope:** type `What is the best pizza in Boston?` and press Send.
- **You must see (b):** this exact message:
  `I can only answer questions about US airports. Please ask about US airports.`
  (This one depends on the AI choosing the fixed sentence. If the AI answers in its own words instead, note it here; it is not a page bug.)
- Result:

### 4. Reloading the page shows the same chat
- [ ] **How:** after checks 1–3 (several questions in one chat), press reload (F5 or Cmd+R).
- **You must see:** the same questions, in the same order, each with its answer (or refusal message), its tables (same titles, same numbers, same formatting) and its "How I got this" list, as before the reload.
- Result:

### 5. "New chat" starts an empty chat
- [ ] **How:** press **New chat**. Then reload the page.
- **You must see:** right after the click, no messages at all. After the reload, still empty (the old chat does not come back). In DevTools > Application > Local Storage > `http://localhost:5500`, the chat ID is gone. Send a new question: it works and starts a new chat.
- Result:

### 6. The page works at phone width
- [ ] **How:** in DevTools, turn on the device toolbar (Cmd+Shift+M / Ctrl+Shift+M) and pick a phone of about 375 pixels wide (for example iPhone SE). Ask `Which New England airports are strong candidates for terminal expansion?`.
- **You must see:**
  - the message box and the Send button are fully visible and usable;
  - text wraps to the screen width;
  - the **whole page never scrolls sideways**; a wide table scrolls sideways **inside its own box** only (P97).
- Result:

### 7. Voice input fills the message box (browser with speech recognition)
- [ ] **How:** in Chrome, click the microphone button, allow the microphone when the browser asks, and say "Which airports in Texas have the most passengers".
- **You must see:** the spoken words appear in the message box as text. The question is **not** sent by itself; it is sent only when you press Send.
- Result:

---

## More checks (from P93–P98)

### 8. Enter does not send while waiting
- [ ] **How:** send a question. While "Working…" shows, type more text in the message box and press Enter.
- **You must see:** nothing is sent: no new question appears in the chat, and the text stays in the box. When the answer has arrived, Enter sends again.
- Result:

### 9. Text from the server is shown as text, never as HTML
Why: AI text and downloaded data must never be able to change or attack the page (P95, agent.md "Safety").
- [ ] **How:** send this question exactly: `<b>hi</b> <img src=x onerror=alert(1)> Is LAX busy?` Then reload the page.
- **You must see:**
  - in the question bubble, the characters `<b>hi</b> <img src=x onerror=alert(1)>` shown literally: "hi" is **not** bold, no broken-image icon appears;
  - **no pop-up dialog** ever appears;
  - the same after the reload (now the question text comes back from the server).
- [ ] **Also:** in the answer, `**bold**` words are shown bold, lines starting with `- ` are shown as a bullet list (the small safe set from P95); no `**` signs are left visible around bold words.
- Result:

### 10. Numbers are formatted by their unit
- [ ] **How:** ask these three questions and look at the tables:
  - `What % of flights out of Anchorage are long-haul?`
  - `What is the unmet flight demand at SFO, and why?`
  - `Which New England airports are strong candidates for terminal expansion?`
- **You must see** (P96):
  - **shares** as a percent with 1 decimal: for example `Long-haul share` like `2.8%`, `Target load factor` like `80.0%` and `85.0%`, `Load factor` like `82.3%`. Never `0.823`;
  - **counts** (passengers, departures, seats) as whole numbers with commas: for example `Missing seats` like `1,063,000`, never `1063000` or `1063000.0`;
  - **months** as names: `Jan`, `Feb`, … `Dec` in the "Load factor by month, 2025" table, never `1`…`12`;
  - **scores, grades, minutes, miles** with 1 decimal (for example `71.4`);
  - **ranks and years** as plain numbers (`3`, `2025`, never `2,025`);
  - an empty value shown as `–` (for example the Grade of the score rows in an airport profile), never `null` or `None`.
- Result:

### 11. Each table has a closed "About this data" box
- [ ] **How:** look under any table from check 10, then click **About this data**.
- **You must see:** the order is: table title, then the table, then "About this data". The box is **closed** at first. When opened it shows the data period (for example `2025`) and, when there are any, the filters, the missing data and the assumptions. Parts with nothing in them are not shown (no empty "Missing:" heading).
- Result:

### 12. A failed connection shows a clear message
- [ ] **How:** stop the backend (Ctrl+C in its terminal). Keep the page open and send `Is LAX busy?`.
- **You must see:** "Working…" goes away and this exact message appears:
  `Could not reach the server. Try again.`
  Send works again afterwards. Start the backend again before the next checks.
- Result:

### 13. A chat ID the server doesn't know is cleared
- [ ] **How:** in DevTools > Application > Local Storage > `http://localhost:5500`, change the stored chat ID's value to `not-a-real-id`. Reload the page.
- **You must see:** an empty chat (no error text, no broken page). In Local Storage the chat ID is gone. Sending a question works and starts a new chat.
- Result:

### 14. The microphone button is hidden without speech recognition
- [ ] **How:** open `http://localhost:5500` in Firefox (it has no speech recognition).
- **You must see:** no microphone button at all. Typing and sending a question still work.
- Result:

### 15. The backend address is one line at the top of app.js
- [ ] **How:** open `web/app.js` and look at the top. Then search the `web/` folder for the address: `grep -rn "localhost:8000" web/`.
- **You must see:** near the top of `web/app.js` exactly this line:
  `const BACKEND_URL = "http://localhost:8000";`
  The search finds the address **only** in that line (and in this checklist), nowhere else in `index.html` or `app.js`. Step 18 changes only this line (P94).
- Result:

---

## Real-data check: the four exam questions

Ask each question in a **new chat** (press New chat first), through the local backend. For each one: the answer is not empty, it names the data period, the tables appear with formatted numbers, and "How I got this" lists the tools used. Known real numbers (from the docs) to compare with:

- [ ] **Q1:** `Which New England airports are strong candidates for terminal expansion?`
  **You must see:** a ranking table of New England airports (states CT, ME, MA, NH, RI, VT only), with final score, grade, demand score and strain score.
  Result:
- [ ] **Q2:** `Compare congestion at LA (LAX) and Santa Ana (SNA).`
  **You must see:** tables with both `LAX` and `SNA` (for example an airport profile with crowding measures, or delay causes).
  Result:
- [ ] **Q3:** `What % of flights out of Anchorage are long-haul?`
  **You must see:** a table "ANC flight mix, 2025" with `Long-haul share` about `2.8%` (passenger flights, 3,000+ miles, decisions.md); the answer states this definition.
  Result:
- [ ] **Q4:** `What is the unmet flight demand at SFO, and why?`
  **You must see:** the table "Unmet demand estimates, 2025" with missing seats as a range: about `150,000` at an 85% target and about `1,063,000` at an 80% target (plan, Step 12); the "Load factor by month, 2025" table with months `Jan`…`Dec`; a 2025 load factor of about `82.3%`.
  Result:
