/*
What:       All the behaviour of the chat page (Step 17).
Why:        Sends the user's question to the backend, shows "Working…" while waiting, then
            shows the answer, the tables and the "How I got this" list. Reloads the same chat
            after a page reload.
Used by:    index.html.
Uses:       The backend's two chat addresses (docs/api.md): POST /chat and GET /chat/{id}.
            The browser's localStorage (keeps only the chat ID) and, when present, the
            browser's speech recognition (voice input, exam bonus). No library.
Main parts: storage helpers, number formats, safe answer text, tables, one turn,
            sending a question, reloading a chat, New chat, voice.
Design:     Implementation plan P92-P98.
            P94: the backend address is the one line right below this comment.
            P95: everything from the server and the user's own text goes in as plain text
                 (textContent / text nodes), never as HTML. The answer keeps a small safe
                 markdown set (**bold**, # headings, - or * bullets, blank line = new
                 paragraph), built from page elements one by one.
            P96: numbers are formatted by their unit. P97: each table scrolls sideways in its
                 own box, then a closed "About this data" box.
            P98: the reply is read on any HTTP status; only a failed request shows
                 "Could not reach the server. Try again.".
*/
const BACKEND_URL = "http://localhost:8000";

const REQUEST_TIME_LIMIT_MS = 75000; // a bit longer than the backend's own 60-second limit
const NO_SERVER_MESSAGE = "Could not reach the server. Try again.";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message");
const sendBtn = document.getElementById("send");
const newChatBtn = document.getElementById("new-chat");
const micBtn = document.getElementById("mic");
const chatIdEl = document.getElementById("chat-id");

let busy = false;

// ---------- Chat ID in localStorage (the page still works if storage is blocked) ----------

function getChatId() {
  try {
    return localStorage.getItem("chatId");
  } catch (e) {
    return null;
  }
}

function setChatId(id) {
  try {
    localStorage.setItem("chatId", id);
  } catch (e) {
    // storage blocked: the chat still works until the page is reloaded
  }
  showChatId();
}

function clearChatId() {
  try {
    localStorage.removeItem("chatId");
  } catch (e) {
    // nothing to clear
  }
  showChatId();
}

function showChatId() {
  const id = getChatId();
  chatIdEl.textContent = id ? "Chat ID: " + id : "Chat ID: new chat";
}

// ---------- Small helpers to build page elements from text ----------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

// ---------- Number formats by unit (P96) ----------

function fixed1(v) {
  return v.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function formatValue(value, unit) {
  if (value === null || value === undefined) return "–";
  if (typeof value !== "number") return String(value);
  switch (unit) {
    case "share":
      return fixed1(value * 100) + "%";
    case "passengers":
    case "departures":
    case "seats":
    case "departures per runway":
      return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
    case "grade":
    case "points":
    case "minutes":
    case "miles":
      return fixed1(value);
    case "month":
      return Number.isInteger(value) && value >= 1 && value <= 12 ? MONTHS[value - 1] : String(value);
    default: // rank, year, text and any unknown unit: as it is
      return String(value);
  }
}

function isNumberCell(value, unit) {
  return typeof value === "number" && unit !== "text" && unit !== "month";
}

// ---------- The answer: plain text with a small safe markdown set (P95) ----------

// Adds text to `parent`, turning **bold** into <strong>. Unpaired ** stay as written.
function addInline(parent, text) {
  const parts = text.split("**");
  if (parts.length % 2 === 0) {
    // odd number of "**": the last one has no partner, keep it as written
    const last = parts.pop();
    parts[parts.length - 1] += "**" + last;
  }
  parts.forEach(function (part, i) {
    if (!part) return;
    if (i % 2 === 1) parent.appendChild(el("strong", null, part));
    else parent.appendChild(document.createTextNode(part));
  });
}

function renderAnswer(text) {
  const box = document.createDocumentFragment();
  let para = null;
  let list = null;
  text.split(/\r?\n/).forEach(function (line) {
    const heading = line.match(/^\s*(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (!line.trim()) {
      para = null;
      list = null;
    } else if (heading) {
      para = null;
      list = null;
      const h = el(heading[1].length === 1 ? "h3" : "h4");
      addInline(h, heading[2]);
      box.appendChild(h);
    } else if (bullet) {
      para = null;
      if (!list) {
        list = el("ul");
        box.appendChild(list);
      }
      const li = el("li");
      addInline(li, bullet[1]);
      list.appendChild(li);
    } else {
      list = null;
      if (para) {
        para.appendChild(el("br"));
      } else {
        para = el("p");
        box.appendChild(para);
      }
      addInline(para, line);
    }
  });
  return box;
}

// ---------- Tables (P89, P90, P96, P97) ----------

function renderAbout(about) {
  const details = el("details"); // closed at first
  details.appendChild(el("summary", null, "About this data"));
  if (!about || typeof about !== "object") return details;
  if (about.data_period) {
    details.appendChild(el("p", null, "Data period: " + about.data_period));
  }
  [["filters", "Filters:"], ["missing", "Missing:"], ["assumptions", "Assumptions:"]].forEach(function (pair) {
    let items = about[pair[0]];
    if (!items || (Array.isArray(items) && items.length === 0)) return;
    if (!Array.isArray(items)) items = [items];
    details.appendChild(el("p", null, pair[1]));
    const ul = el("ul");
    items.forEach(function (item) {
      ul.appendChild(el("li", null, item));
    });
    details.appendChild(ul);
  });
  return details;
}

function renderTable(t) {
  const block = el("div", "table-block");
  block.appendChild(el("div", "table-title", t.title));
  const columns = t.columns || [];
  const units = t.units || [];
  const unitCol = columns.indexOf("Unit"); // for unit "row" (P89)

  const table = el("table");
  const headRow = el("tr");
  columns.forEach(function (c) {
    headRow.appendChild(el("th", null, c));
  });
  table.appendChild(el("thead")).appendChild(headRow);

  const body = el("tbody");
  (t.rows || []).forEach(function (row) {
    const tr = el("tr");
    row.forEach(function (value, i) {
      let unit = units[i];
      if (unit === "row") unit = unitCol >= 0 ? row[unitCol] : null;
      tr.appendChild(el("td", isNumberCell(value, unit) ? "num" : null, formatValue(value, unit)));
    });
    body.appendChild(tr);
  });
  table.appendChild(body);

  const scroll = el("div", "table-scroll");
  scroll.appendChild(table);
  block.appendChild(scroll);
  block.appendChild(renderAbout(t.about));
  return block;
}

// ---------- One turn: question, then answer or refusal, tables, steps ----------

function addQuestion(text) {
  const turn = el("div", "turn");
  turn.appendChild(el("div", "msg user", text));
  messagesEl.appendChild(turn);
  return turn;
}

function addReply(turn, reply) {
  const bot = el("div", "msg bot");
  if (reply.refusal && reply.refusal.message) {
    bot.classList.add("refusal");
    bot.appendChild(el("p", null, reply.refusal.message));
  } else if (reply.answer) {
    bot.appendChild(renderAnswer(String(reply.answer)));
  }
  (reply.tables || []).forEach(function (t) {
    bot.appendChild(renderTable(t));
  });
  const steps = reply.steps || [];
  if (steps.length) {
    const box = el("div", "steps");
    box.appendChild(el("h4", null, "How I got this"));
    const ul = el("ul");
    steps.forEach(function (s) {
      ul.appendChild(el("li", null, s));
    });
    box.appendChild(ul);
    bot.appendChild(box);
  }
  turn.appendChild(bot);
}

function addNoServer(turn) {
  addReply(turn, { refusal: { message: NO_SERVER_MESSAGE } });
}

// ---------- Talking to the backend ----------

// Returns the parsed JSON reply on any HTTP status, or null when the request failed
// (network down, too slow, or a reply that is not JSON).
async function callBackend(path, options) {
  const controller = new AbortController();
  const timer = setTimeout(function () {
    controller.abort();
  }, REQUEST_TIME_LIMIT_MS);
  try {
    const res = await fetch(BACKEND_URL + path, Object.assign({ signal: controller.signal }, options));
    const data = await res.json();
    return data && typeof data === "object" ? data : null;
  } catch (e) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function setBusy(on) {
  busy = on;
  sendBtn.disabled = on;
  newChatBtn.disabled = on;
}

async function send() {
  if (busy) return;
  const text = inputEl.value;
  if (!text.trim()) return;
  setBusy(true);
  inputEl.value = "";
  const turn = addQuestion(text);
  const working = el("div", "msg working", "Working…");
  turn.appendChild(working);
  turn.scrollIntoView({ block: "start" });

  const body = { message: text };
  const id = getChatId();
  if (id) body.conversation_id = id;
  const reply = await callBackend("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  working.remove();
  if (!reply) {
    addNoServer(turn);
  } else {
    if (reply.refusal && reply.refusal.cause === "chat_not_found") clearChatId();
    else if (typeof reply.conversation_id === "string" && reply.conversation_id) setChatId(reply.conversation_id);
    addReply(turn, reply);
  }
  setBusy(false);
  inputEl.focus();
}

async function reloadChat() {
  const id = getChatId();
  showChatId();
  if (!id) return;
  setBusy(true);
  const reply = await callBackend("/chat/" + encodeURIComponent(id), { method: "GET" });
  if (!reply) {
    // server down: keep the chat ID so a later reload can show the chat again
    messagesEl.appendChild(el("div", "msg refusal", NO_SERVER_MESSAGE));
  } else if (reply.refusal && reply.refusal.cause === "chat_not_found") {
    clearChatId();
  } else {
    (reply.turns || []).forEach(function (t) {
      addReply(addQuestion(t.question), t);
    });
  }
  setBusy(false);
}

// ---------- Buttons and keys ----------

sendBtn.addEventListener("click", send);

inputEl.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault(); // Enter never adds a new line; it sends only when not waiting
    if (!busy) send();
  }
});

newChatBtn.addEventListener("click", function () {
  if (busy) return;
  clearChatId();
  messagesEl.replaceChildren();
  inputEl.focus();
});

// ---------- Voice input (bonus): fills the message box, never sends by itself ----------

const SpeechRecognitionImpl = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognitionImpl) {
  let recognition = null;
  micBtn.hidden = false;
  micBtn.addEventListener("click", function () {
    if (recognition) {
      recognition.stop();
      return;
    }
    recognition = new SpeechRecognitionImpl();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = function (event) {
      const spoken = event.results[0][0].transcript;
      inputEl.value = inputEl.value.trim() ? inputEl.value.trim() + " " + spoken : spoken;
    };
    recognition.onend = function () {
      recognition = null;
      micBtn.textContent = "Mic";
    };
    try {
      recognition.start();
      micBtn.textContent = "Stop";
    } catch (e) {
      recognition = null;
    }
  });
}

reloadChat();
