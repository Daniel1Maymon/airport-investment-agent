Step 19 hand checklist: checked by hand in a browser after the admin page is built (implementation plan, Step 19, P141).

# Admin page: hand checklist

Each check says **how to do it** and **what you must see**. Tick the box when it passes and fill in the "Result:" line (pass / fail, and a short note if it fails).

Design: [docs/admin-dashboard.md](../docs/admin-dashboard.md), [docs/api.md](../docs/api.md) section 4, implementation plan P122–P141.

## How to run locally

Open two terminals in the main project folder. Use a **copy** of the real `chat.sqlite` (or a new empty file), never the live one.

1. **Backend** (the Python server), on port 8000, with an admin token (a made-up long random text for the local run):
   ```bash
   set -a; source .env; set +a; ALLOWED_ORIGIN=http://localhost:5500 ADMIN_TOKEN=local-test-token-0123456789abcdef CHAT_DB=chat-copy.sqlite .venv/bin/uvicorn --factory app.api:main_app --port 8000
   ```
   `ADMIN_TOKEN` is the dashboard's password. Without it every admin request is refused (the page stays locked).
2. **Pages**, on port 5500 (Python's built-in file server, serving the `web/` folder):
   ```bash
   .venv/bin/python -m http.server 5500 --directory web
   ```
3. For a local run, set `BACKEND_URL` in both `web/app.js` and `web/admin.js` to `"http://localhost:8000"` (and set both back afterwards; a test checks they are the same).
4. Open **`http://localhost:5500/admin.html`**. Use `localhost`, **not** `127.0.0.1` (CORS compares the address as exact text, P93).

Useful browser tool: **DevTools** (F12 or Cmd+Option+I). Its **Application** tab shows **Session Storage** (a small store inside the browser that is forgotten when the tab is closed; the page keeps the token there).

Use Chrome for the checks, unless a check says another browser.

---

## Checks from the plan (P141)

### 1. The login box comes first
- [ ] **How:** open `http://localhost:5500/admin.html` in a new tab.
- **You must see:** only a password box and a "Log in" button. No numbers, no switch, no questions.
- Result:

### 2. A wrong token is refused
- [ ] **How:** type `wrong-token` in the box and press Log in.
- **You must see:** the box again, with the message **Wrong token**. In DevTools > Application > Session Storage, there is no `admin_token`.
- Result:

### 3. The numbers and the bars are shown
- [ ] **How:** type the right token (the `ADMIN_TOKEN` of step 1) and press Log in. If the file is new, first ask two or three questions on the chat page (`http://localhost:5500`), then press **Refresh** on the admin page.
- **You must see:**
  - the cards Questions, Chats, Refusal rate, Cost, Cost per question, Tokens, Time p50 / p95, with numbers;
  - "since <date>" next to the refusal rate and the times;
  - the bars "Refusals by cause" (or "None yet") and "Tools the AI picked", with all nine tools listed (unused ones with 0);
  - in DevTools > Application > Session Storage, the key `admin_token`.
- Result:

### 4. Questions per day has 30 bars
- [ ] **How:** look at "Questions per day (last 30 days)".
- **You must see:** 30 day rows, oldest first, ending with today (UTC); days with no questions show 0.
- Result:

### 5. A recent question opens to its answer and steps
- [ ] **How:** in "Recent questions", click a row of a question that used tools.
- **You must see:** under the row, the answer text and the "How I got this" lines (for example `Ranked airports (region: New England; …)`). Click again: it closes. A refused question shows its cause and the fixed refusal message.
- Result:

### 6. The switch turns off in two steps, and the chat page then refuses
- [ ] **How:** press **Turn off**. Then press **Yes, turn the AI off for everyone**. Then ask any question on the chat page.
- **You must see:** after the first press, a second button "Yes, turn the AI off for everyone" (and a Cancel), with no browser pop-up; nothing is sent yet. After the second press, "AI answering: OFF". On the chat page, the answer is the message `The AI service is not available right now. The airport data is fine; please try again later.`
- Result:

### 7. The switch turns back on
- [ ] **How:** press **Turn on** on the admin page, then ask a question on the chat page.
- **You must see:** "AI answering: ON", and the chat page answers normally again.
- Result:

### 8. The page works at phone width
- [ ] **How:** in DevTools, turn on the device toolbar (Cmd+Shift+M / Ctrl+Shift+M) and pick a phone of about 375 pixels wide (for example iPhone SE). Reload the admin page and log in.
- **You must see:** no sideways scroll of the whole page; the cards wrap onto several lines; the bars fit; the recent questions table scrolls sideways inside its own box only.
- Result:

### 9. A question with HTML in it shows as plain text
- [ ] **How:** on the chat page, ask `Tell me about <b>hi</b> BOS`. Then press **Refresh** on the admin page and open that question in "Recent questions".
- **You must see:** the text `<b>hi</b>` exactly as typed, with the angle brackets; nothing bold.
- Result:

### 10. Network down keeps the token
- [ ] **How:** stop the backend (Ctrl+C in its terminal), then press **Refresh**.
- **You must see:** the message **Could not reach the server**; the page stays logged in (the token is still in Session Storage). Start the backend again and press Refresh: the numbers come back.
- Result:
