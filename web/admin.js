/*
What:       All the behaviour of the admin page (Step 19).
Why:        Logs in with the admin token, loads the dashboard numbers, the recent questions
            and the AI switch from the backend, draws them, and sets the switch.
Used by:    admin.html.
Uses:       The four admin addresses of the backend (docs/api.md section 4):
            GET /admin/metrics, GET /admin/events, GET /admin/ai, POST /admin/ai.
            The browser's sessionStorage (the token, key "admin_token"; forgotten when the
            tab is closed). No library.
Main parts: storage helpers, the request helper, number formats, the cards, the bars,
            the recent questions table, the AI switch, login / logout / refresh.
Design:     docs/admin-dashboard.md; implementation plan P136-P138.
            P136: the backend address is the one line right below this comment, the same
                 value as in app.js (a test checks they match).
            P137: everything from the server goes in as plain text (textContent), never as
                 HTML, because questions are written by strangers. Bars are plain boxes with
                 a width. A Refresh button, no automatic refresh. Turning the AI off takes
                 two presses on the page, never a browser pop-up.
            P138: a 401 clears the token and shows the login box with "Wrong token"; a
                 failed request shows "Could not reach the server" and keeps the token.

How a visit works, in short (example: the owner opens /admin.html):
  1. No token saved in this tab → only the login box is shown.
  2. The owner types the token. The page asks GET /admin/ai, /admin/metrics and
     /admin/events?limit=30&offset=0, each with "Authorization: Bearer <token>".
  3. 401 on any of them → the token is wrong: it is forgotten, the login box comes back
     with "Wrong token". All good → the token is kept in sessionStorage and the dashboard
     is drawn: the switch, the cards, the 30 day bars, refusals and tools, the questions.
  4. Refresh asks the three addresses again (the questions table stays on the same page).
     The page numbers and "Previous" / "Next" load 30 questions with ?offset=. A click on a column name
     sorts all questions by it (?sort=&order=); a page load always starts newest first. "Turn off" → "Yes, turn the AI off for
     everyone" sends POST /admin/ai {"enabled": false}; "Turn on" sends {"enabled": true}.
*/
// The public backend on Railway (Step 18). For a local run use "http://localhost:8000".
const BACKEND_URL = "https://backend-production-09fa.up.railway.app";

const TOKEN_KEY = "admin_token"; // the sessionStorage key of the token (P136)
const PAGE_SIZE = 30; // questions per page of the recent questions table (the backend allows 1-500)
const EVENT_COLUMNS = 7; // Time, Visitor ID, Chat ID, Question, Result, Tools, Cost
let currentPage = 0; // 0 = the first 30 questions in the chosen order
// The sort of the questions table. Refresh and the page buttons keep it; a page load starts newest first.
const DEFAULT_SORT = { sort: "time", order: "desc" }; // newest first
let currentSort = { ...DEFAULT_SORT };
const REQUEST_TIME_LIMIT_MS = 30000; // the admin addresses only read the file, so 30 s is plenty
// The page's own messages (P138).
const WRONG_TOKEN = "Wrong token";
const NO_SERVER = "Could not reach the server";

// ---------------------------------------------------------------- storage helpers
// sessionStorage can throw (private mode, blocked storage), so each use is wrapped.

/** The saved token, or "" when none (or storage is blocked). */
function loadToken() {
  try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
}

/** Save the token for this tab. */
function saveToken(token) {
  try { sessionStorage.setItem(TOKEN_KEY, token); } catch (e) { /* the page still works for this visit */ }
}

/** Forget the token (wrong token or log out). */
function clearToken() {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* nothing saved, nothing to clear */ }
}

// The token in use right now (kept in memory too, so a blocked storage still works).
let currentToken = "";

// ---------------------------------------------------------------- the request helper

/** A thrown error that says the token was refused (HTTP 401). */
class Unauthorized extends Error {}
/** A thrown error that says the server could not be reached or replied oddly. */
class NoServer extends Error {}

/**
 * Call one admin address with the token and give back its JSON.
 * Example: await api("GET", "/admin/ai") → {enabled: true, updated_at: null, note: null}.
 * 401 → throws Unauthorized; network down, time out, non-JSON or another error status →
 * throws NoServer.
 */
async function api(method, path, body) {
  const controller = new AbortController();
  const timer = setTimeout(function () { controller.abort(); }, REQUEST_TIME_LIMIT_MS);
  let response;
  try {
    const options = { method: method, headers: { Authorization: "Bearer " + currentToken }, signal: controller.signal };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    response = await fetch(BACKEND_URL + path, options);
  } catch (e) {
    throw new NoServer();
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 401) throw new Unauthorized();
  if (!response.ok) throw new NoServer();
  try {
    return await response.json();
  } catch (e) {
    throw new NoServer();
  }
}

// ---------------------------------------------------------------- small page helpers

/** Find an element by its id. */
function byId(id) { return document.getElementById(id); }

/** A new element with plain text inside (never HTML, P137). */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

/** Remove every child of a node. */
function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** Show a message in a message box, or hide the box when text is empty. */
function showMessage(id, text) {
  const box = byId(id);
  box.textContent = text || "";
  box.hidden = !text;
}

// ---------------------------------------------------------------- number formats

/** A whole number with thousands separators, e.g. 410000 → "410,000". */
function whole(n) { return Number(n || 0).toLocaleString("en-US"); }

/** Dollars with 4 decimals, e.g. 0.1524 → "$0.1524". */
function dollars(n) { return "$" + Number(n || 0).toFixed(4); }

/** A share as a percent with 1 decimal, e.g. 0.075 → "7.5%". */
function percent(n) { return (Number(n || 0) * 100).toFixed(1) + "%"; }

/** Milliseconds as seconds with 1 decimal, e.g. 7400 → "7.4 s". */
function seconds(ms) { return (Number(ms || 0) / 1000).toFixed(1) + " s"; }

/** The date part of an ISO time, e.g. "2026-11-02T09:00:00+00:00" → "2026-11-02". */
function dayOf(iso) { return iso ? String(iso).slice(0, 10) : ""; }

/** An ISO time shown short, e.g. "2026-11-02T09:14:03+00:00" → "2026-11-02 09:14". */
function shortTime(iso) { return iso ? String(iso).slice(0, 16).replace("T", " ") : "–"; }

// ---------------------------------------------------------------- the AI switch

/** Draw the switch from {enabled, updated_at, note}. */
function drawSwitch(state) {
  const on = state.enabled !== false;
  byId("switch").classList.toggle("off", !on);
  byId("switch-text").textContent = on ? "AI answering: ON" : "AI answering: OFF";
  const parts = [];
  if (state.updated_at) parts.push("set " + shortTime(state.updated_at) + " UTC");
  if (state.note) parts.push("note: " + state.note);
  byId("switch-note").textContent = parts.join(" · ");
  // ON shows "Turn off"; OFF shows "Turn on". The confirm step is always closed after a redraw.
  byId("switch-off").hidden = !on;
  byId("switch-on").hidden = on;
  byId("switch-confirm").hidden = true;
  byId("switch-cancel").hidden = true;
}

/** Send the wanted state (never a flip, P131) and redraw the switch from the reply. */
async function setSwitch(enabled) {
  const buttons = ["switch-off", "switch-on", "switch-confirm", "switch-cancel"].map(byId);
  buttons.forEach(function (b) { b.disabled = true; });
  try {
    drawSwitch(await api("POST", "/admin/ai", { enabled: enabled }));
    showMessage("dash-message", "");
  } catch (e) {
    handleError(e);
  } finally {
    buttons.forEach(function (b) { b.disabled = false; });
  }
}

// ---------------------------------------------------------------- the cards

/** One number card: a label, a big value and an optional small note. */
function card(label, value, note) {
  const box = el("div", "card");
  box.appendChild(el("div", "card-label", label));
  box.appendChild(el("div", "card-value", value));
  if (note) box.appendChild(el("span", "note", note));
  return box;
}

/** Draw the number cards from GET /admin/metrics. */
function drawCards(m) {
  const cards = byId("cards");
  clear(cards);
  // The log rows start on the day the dashboard was deployed, so three numbers say since when.
  const since = m.events_since ? "since " + dayOf(m.events_since) : "no requests logged yet";
  cards.appendChild(card("Questions", whole(m.questions)));
  cards.appendChild(card("Chats", whole(m.chats)));
  cards.appendChild(card("Visitors", whole(m.visitors), "different browsers · " + since));
  cards.appendChild(card("Refusal rate", percent(m.refusal_rate), since + " · " + whole(m.requests) + " requests"));
  cards.appendChild(card("Cost", dollars(m.cost_usd)));
  cards.appendChild(card("Cost per question", dollars(m.cost_per_question_usd)));
  cards.appendChild(card("Tokens", whole(Number(m.input_tokens || 0) + Number(m.output_tokens || 0)),
    whole(m.input_tokens) + " in · " + whole(m.output_tokens) + " out"));
  cards.appendChild(card("Time p50 / p95", seconds(m.duration_p50_ms) + " / " + seconds(m.duration_p95_ms), since));
}

// ---------------------------------------------------------------- the bars

/**
 * Draw bars into a box: one row per item with its label, a bar and the count.
 * Each bar's width is its count's share of the largest count (P137), e.g. counts 3 and 6 →
 * 50% and 100%. emptyText is shown when there is no item.
 */
function drawBars(boxId, items, emptyText) {
  const box = byId(boxId);
  clear(box);
  if (!items.length) {
    box.appendChild(el("p", "note", emptyText));
    return;
  }
  const largest = Math.max.apply(null, items.map(function (i) { return i.count; }));
  items.forEach(function (item) {
    const row = el("div", "bar-row");
    const label = el("span", "bar-label", item.label);
    label.title = item.label;
    const track = el("span", "bar-track");
    const fill = el("span", "bar-fill");
    fill.style.display = "block";
    fill.style.width = (largest > 0 ? (item.count / largest) * 100 : 0) + "%";
    track.appendChild(fill);
    row.appendChild(label);
    row.appendChild(track);
    row.appendChild(el("span", "bar-count", whole(item.count)));
    box.appendChild(row);
  });
}

/** Draw the three bar groups from GET /admin/metrics. */
function drawAllBars(m) {
  drawBars("days", (m.questions_per_day || []).map(function (d) { return { label: d.day, count: d.count }; }), "No days.");
  byId("refusals-since").textContent = m.events_since ? "(since " + dayOf(m.events_since) + ")" : "";
  drawBars("refusals", (m.refusals_by_cause || []).map(function (r) { return { label: r.cause, count: r.count }; }), "None yet.");
  drawBars("tools", (m.tools || []).map(function (t) { return { label: t.name, count: t.count }; }), "No tools.");
}

// ---------------------------------------------------------------- the recent questions

/** The detail row under a question: the answer and the "How I got this" steps. */
function detailRow(event) {
  const row = el("tr", "detail");
  const cell = el("td");
  cell.colSpan = EVENT_COLUMNS;
  const box = el("div", "detail-box");
  box.appendChild(el("h3", "", event.refusal_cause ? "Refusal message" : "Answer"));
  box.appendChild(el("div", "", event.answer || "–"));
  box.appendChild(el("h3", "", "How I got this"));
  if (event.steps && event.steps.length) {
    const list = el("ul");
    event.steps.forEach(function (s) { list.appendChild(el("li", "", s)); });
    box.appendChild(list);
  } else {
    box.appendChild(el("div", "note", "No tools were used."));
  }
  box.appendChild(el("div", "note", "Chat ID: " + (event.conversation_id || "–")));
  cell.appendChild(box);
  row.appendChild(cell);
  row.hidden = true;
  return row;
}

/**
 * A table cell with the first 8 characters of an ID; the whole ID shows on hover.
 * Example: "3c257eb7-be9e-…" → "3c257eb7". No ID (chats from before visitor IDs) → "–".
 */
function shortIdCell(id) {
  if (!id) return el("td", "id note", "–");
  const cell = el("td", "id", String(id).slice(0, 8));
  cell.title = id;
  return cell;
}

/**
 * Which page numbers to show (0-based), with null for a "…" gap: the first and last page,
 * and two pages on each side of the current one (all pages when there are 7 or fewer). 5 pages → 0 1 2 3 4; 20 pages, current 9 → 0 … 7 8 9 10 11 … 19.
 */
function pageList(current, pages) {
  const list = [];
  for (let p = 0; p < pages; p++) {
    if (pages <= 7 || p === 0 || p === pages - 1 || Math.abs(p - current) <= 2) list.push(p);
    else if (list[list.length - 1] !== null) list.push(null);
  }
  return list;
}

/** The pager under the table: ‹ Previous, one button per page number, Next ›, and "Page 2 of 5 · 136 questions". */
function drawPager(total) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  byId("page-info").textContent = "Page " + (currentPage + 1) + " of " + pages + " · " + whole(total) + " questions";
  byId("prev-page").disabled = currentPage === 0;
  byId("next-page").disabled = currentPage + 1 >= pages;
  const box = byId("page-numbers");
  box.replaceChildren();
  pageList(currentPage, pages).forEach(function (p) {
    if (p === null) {
      box.appendChild(el("span", "gap", "…"));
      return;
    }
    const button = el("button", null, String(p + 1));
    button.type = "button";
    if (p === currentPage) button.setAttribute("aria-current", "page");
    button.addEventListener("click", function () { if (p !== currentPage) loadPage(p); });
    box.appendChild(button);
  });
}

/** The address of one page of recent questions, in the chosen order. */
function eventsPath(page) {
  return "/admin/events?limit=" + PAGE_SIZE + "&offset=" + page * PAGE_SIZE +
    "&sort=" + currentSort.sort + "&order=" + currentSort.order;
}

// ---------------------------------------------------------------- sorting

/** Show ▲ (A→Z, low→high, old→new) or ▼ next to the sorted column's name. */
function drawSortHeaders() {
  document.querySelectorAll("button.sort").forEach(function (button) {
    const column = button.dataset.sort;
    const name = button.dataset.name || button.textContent;
    button.dataset.name = name;
    const active = column === currentSort.sort;
    button.textContent = active ? name + (currentSort.order === "asc" ? " ▲" : " ▼") : name;
    button.parentElement.setAttribute("aria-sort", active ? (currentSort.order === "asc" ? "ascending" : "descending") : "none");
  });
}

/**
 * A click on a column name: the same column flips the order; a new column starts with
 * newest / most expensive first for Time and Cost, and A→Z for the others. Back to page 1.
 */
function chooseSort(column) {
  if (column === currentSort.sort) {
    currentSort = { sort: column, order: currentSort.order === "asc" ? "desc" : "asc" };
  } else {
    currentSort = { sort: column, order: column === "time" || column === "cost" ? "desc" : "asc" };
  }
  drawSortHeaders();
  loadPage(0);
}

/** Load and draw another page of recent questions (the numbers above stay as they are). */
async function loadPage(page) {
  try {
    const reply = await api("GET", eventsPath(page));
    // Questions may have been added since the last load: never go past the last page.
    const lastPage = Math.max(0, Math.ceil((reply.total || 0) / PAGE_SIZE) - 1);
    if (page > lastPage) return loadPage(lastPage);
    currentPage = page;
    drawEvents(reply.events || []);
    drawPager(reply.total || 0);
  } catch (e) {
    handleError(e);
  }
}

/** Draw the recent questions table; a click (or Enter) on a row opens or closes its detail. */
function drawEvents(events) {
  const body = byId("events");
  clear(body);
  if (!events.length) {
    const row = el("tr");
    const cell = el("td", "note", "No questions yet.");
    cell.colSpan = EVENT_COLUMNS;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }
  events.forEach(function (event) {
    const row = el("tr", "row");
    row.tabIndex = 0;
    row.appendChild(el("td", "nw", shortTime(event.time)));
    row.appendChild(shortIdCell(event.visitor_id));
    row.appendChild(shortIdCell(event.conversation_id));
    row.appendChild(el("td", "question", event.question));
    const result = event.refusal_cause ? el("td", "refused", "refused (" + event.refusal_cause + ")") : el("td", "", "answered");
    row.appendChild(result);
    const tools = event.tools || [];
    row.appendChild(el("td", "tools", tools.length ? tools.join(", ") : "none"));
    row.appendChild(el("td", "num", dollars(event.cost_usd)));
    const detail = detailRow(event);
    function toggle() { detail.hidden = !detail.hidden; }
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
    body.appendChild(row);
    body.appendChild(detail);
  });
}

// ---------------------------------------------------------------- login, refresh, errors

/** Show the login box (with a message, or none) and hide the dashboard. */
function showLogin(message) {
  byId("dashboard").hidden = true;
  byId("login").hidden = false;
  showMessage("login-message", message);
  byId("token-input").value = "";
  byId("token-input").focus();
}

/**
 * Handle a failed request (P138): a refused token is forgotten and the login box comes back
 * with "Wrong token"; a failed request keeps the token and says "Could not reach the server".
 */
function handleError(error) {
  if (error instanceof Unauthorized) {
    currentToken = "";
    clearToken();
    showLogin(WRONG_TOKEN);
  } else if (!byId("dashboard").hidden) {
    showMessage("dash-message", NO_SERVER);
  } else {
    showMessage("login-message", NO_SERVER);
  }
}

/** Load the switch, the numbers and the recent questions, then draw everything. */
async function refresh() {
  const button = byId("refresh");
  button.disabled = true;
  try {
    const results = await Promise.all([
      api("GET", "/admin/ai"),
      api("GET", "/admin/metrics"),
      api("GET", eventsPath(currentPage)),
    ]);
    // Every request worked, so the token is right: keep it for this tab and show the dashboard.
    saveToken(currentToken);
    byId("login").hidden = true;
    byId("dashboard").hidden = false;
    showMessage("dash-message", "");
    drawSwitch(results[0]);
    drawCards(results[1]);
    drawAllBars(results[1]);
    drawEvents(results[2].events || []);
    drawPager(results[2].total || 0);
  } catch (e) {
    handleError(e);
  } finally {
    button.disabled = false;
  }
}

/** Wire up the buttons and start: the dashboard with a saved token, else the login box. */
function start() {
  byId("login-form").addEventListener("submit", function (e) {
    e.preventDefault();
    currentToken = byId("token-input").value.trim();
    if (currentToken) refresh();
  });
  byId("refresh").addEventListener("click", refresh);
  byId("prev-page").addEventListener("click", function () { loadPage(currentPage - 1); });
  document.querySelectorAll("button.sort").forEach(function (button) {
    button.addEventListener("click", function () { chooseSort(button.dataset.sort); });
  });
  drawSortHeaders();
  byId("next-page").addEventListener("click", function () { loadPage(currentPage + 1); });
  byId("logout").addEventListener("click", function () {
    currentToken = "";
    currentPage = 0;
    clearToken();
    showLogin("");
  });
  // Turning off takes two presses on the page (P137): "Turn off", then the confirm button.
  byId("switch-off").addEventListener("click", function () {
    byId("switch-off").hidden = true;
    byId("switch-confirm").hidden = false;
    byId("switch-cancel").hidden = false;
  });
  byId("switch-cancel").addEventListener("click", function () {
    byId("switch-off").hidden = false;
    byId("switch-confirm").hidden = true;
    byId("switch-cancel").hidden = true;
  });
  byId("switch-confirm").addEventListener("click", function () { setSwitch(false); });
  byId("switch-on").addEventListener("click", function () { setSwitch(true); });

  currentToken = loadToken();
  if (currentToken) {
    refresh();
  } else {
    showLogin("");
  }
}

start();
