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
            P104: tables the AI writes in its answer become real tables (still text nodes);
                 the tool tables sit in one closed "Show the numbers" box under the answer.
            P98: the reply is read on any HTTP status; only a failed request shows
                 "Could not reach the server. Try again.".
*/
const BACKEND_URL = "http://localhost:8000";

const REQUEST_TIME_LIMIT_MS = 75000; // a bit longer than the backend's own 60-second limit
// P106: the page speaks English or Hebrew (right to left). Only the page's own words are
// translated; the AI answers in the language of the question, and the data tables stay English.
const TEXT = {
  en: {
    noServer: "Could not reach the server. Try again.",
    chatId: "Chat ID: ",
    working: "Working…",
    agent: "Agent",
    numbers: function (n) { return "Show the numbers (" + n + (n === 1 ? " table)" : " tables)"); },
    steps: "How I got this",
    about: "About this data",
    period: "Data period:", filters: "Filters:", missing: "Missing:", assumptions: "Assumptions:",
    placeholder: "Ask about any US airport",
    mic: "Mic", stop: "Stop", speak: "Speak your question", question: "Your question",
    otherLang: "עברית", speech: "en-US",
  },
  he: {
    noServer: "אין חיבור לשרת. נסו שוב.",
    chatId: "מזהה שיחה: ",
    working: "עובד על זה…",
    agent: "הסוכן",
    numbers: function (n) { return n === 1 ? "הצגת המספרים (טבלה אחת)" : "הצגת המספרים (" + n + " טבלאות)"; },
    steps: "איך הגעתי לזה",
    about: "על הנתונים",
    period: "תקופת הנתונים:", filters: "סינונים:", missing: "חסר:", assumptions: "הנחות:",
    placeholder: "שאלו על כל שדה תעופה בארה״ב",
    mic: "הקלטה", stop: "עצירה", speak: "הקלטת השאלה", question: "השאלה שלך",
    otherLang: "English", speech: "he-IL",
  },
};
let lang = "en";

// P106: refusal messages in Hebrew, by cause. The backend sends English; on the Hebrew
// page we show these instead. An unknown cause falls back to the backend's text.
const REFUSALS_HE = {
  no_data: "אין לנו נתונים כדי לענות על השאלה הזו. נסו לשאול משהו אחר.",
  airport_not_found: "לא מצאתי את שדה התעופה. בדקו את השם או השתמשו בקוד בן 3 האותיות.",
  chat_not_found: "לא מצאתי את השיחה הזו. התחילו שיחה חדשה.",
  out_of_scope: "אני עונה רק על שאלות על שדות תעופה בארה״ב. שאלו על שדות תעופה בארה״ב.",
  ai_unavailable: "שירות ה־AI לא זמין כרגע. נתוני שדות התעופה תקינים; נסו שוב מאוחר יותר.",
  too_many_steps: "השאלה הזו דרשה יותר מדי שלבים. נסו שאלה ממוקדת יותר.",
  question_too_long: "השאלה ארוכה מדי (יותר מ־1,000 תווים). קצרו אותה.",
  busy: "אני עדיין עונה על השאלה הקודמת. חכו לתשובה הזו קודם.",
  internal_error: "משהו השתבש אצלנו. נסו שוב מאוחר יותר.",
};

// P106: the "How I got this" labels in Hebrew. The backend writes "<label> (<settings>)";
// on the Hebrew page the label is swapped and the settings stay as sent, left to right.
const STEP_LABELS_HE = {
  "Looked up airports": "חיפשתי שדות תעופה",
  "Ranked airports": "דירגתי שדות תעופה",
  "Looked up airport profiles": "שלפתי פרופיל של שדות תעופה",
  "Looked at traffic over time": "בדקתי את התנועה לאורך זמן",
  "Split departures into groups": "חילקתי את ההמראות לקבוצות",
  "Looked at delay causes": "בדקתי את סיבות העיכובים",
  "Estimated unmet demand": "הערכתי את הביקוש הלא מסופק",
  "Checked which data we have": "בדקתי אילו נתונים יש לנו",
  "Checked today's FAA status": "בדקתי את מצב ה־FAA היום",
};

function stepItem(text) {
  const li = el("li");
  if (lang === "he") {
    const label = Object.keys(STEP_LABELS_HE).find(function (k) {
      return text === k || text.startsWith(k + " ");
    });
    if (label) {
      li.appendChild(document.createTextNode(STEP_LABELS_HE[label]));
      const rest = text.slice(label.length).trim();
      if (rest) {
        li.appendChild(document.createTextNode(" "));
        const bdi = document.createElement("bdi");
        bdi.dir = "ltr";
        bdi.textContent = rest;
        li.appendChild(bdi);
      }
      return li;
    }
  }
  li.textContent = text;
  return li;
}

function refusalText(refusal) {
  if (lang === "he" && Object.prototype.hasOwnProperty.call(REFUSALS_HE, refusal.cause)) return REFUSALS_HE[refusal.cause];
  return refusal.message;
}
function T(key) {
  return TEXT[lang][key];
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message");
const sendBtn = document.getElementById("send");
const newChatBtn = document.getElementById("new-chat");
const micBtn = document.getElementById("mic");
const chatIdEl = document.getElementById("chat-id");
const welcomeEl = document.getElementById("welcome");
const methodEl = document.getElementById("method");

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
  chatIdEl.textContent = id ? T("chatId") + id : ""; // nothing to show before the first answer
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
// Backticks around a word (`code`) are dropped: the reader needs the word, not the marks.
function addInline(parent, text) {
  const parts = text.replace(/`([^`]*)`/g, "$1").split("**");
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

// A markdown table the AI wrote anyway (P104): "| a | b |" lines become a real table,
// built from text nodes like everything else. The "|---|" line is skipped.
function isTableLine(line) {
  return /^\s*\|.*\|\s*$/.test(line);
}

function isDividerLine(line) {
  return /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*(:?-{2,}:?\s*)?$/.test(line);
}

function tableCells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(function (c) {
    return c.trim();
  });
}

function renderAnswerTable(lines) {
  const rows = lines.filter(function (l) {
    return !isDividerLine(l);
  }).map(tableCells);
  const table = el("table");
  if (rows.length) {
    const headRow = el("tr");
    rows[0].forEach(function (c) {
      const th = el("th");
      addInline(th, c);
      headRow.appendChild(th);
    });
    table.appendChild(el("thead")).appendChild(headRow);
  }
  const body = el("tbody");
  rows.slice(1).forEach(function (r) {
    const tr = el("tr");
    r.forEach(function (c) {
      const td = el("td", /^[-+$]?[\d.,]+%?$/.test(c) ? "num" : null);
      addInline(td, c);
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
  table.appendChild(body);
  const scroll = el("div", "table-scroll");
  scroll.appendChild(table);
  return scroll;
}

function renderAnswer(text) {
  const box = el("div", "answer");
  box.dir = "auto";
  const lines = text.split(/\r?\n/);
  let para = null;
  let list = null;
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n];
    const heading = line.match(/^\s*(#{1,6})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*\u2022]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (!line.trim() || /^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      para = null; // a blank line or a "---" rule ends the paragraph or list
      list = null;
    } else if (isTableLine(line)) {
      para = null;
      list = null;
      const block = [];
      while (n < lines.length && isTableLine(lines[n])) block.push(lines[n++]);
      n--;
      box.appendChild(renderAnswerTable(block));
    } else if (heading) {
      para = null;
      list = null;
      const h = el(heading[1].length <= 2 ? "h3" : "h4");
      addInline(h, heading[2].replace(/\s*#+\s*$/, ""));
      box.appendChild(h);
    } else if (bullet || numbered) {
      para = null;
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = el(tag);
        box.appendChild(list);
      }
      const li = el("li");
      addInline(li, (bullet || numbered)[1]);
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
  }
  return box;
}

// ---------- Tables (P89, P90, P96, P97) ----------

function renderAbout(about) {
  const details = el("details"); // closed at first
  details.appendChild(el("summary", null, T("about")));
  if (!about || typeof about !== "object") return details;
  if (about.data_period) {
    details.appendChild(el("p", null, T("period") + " " + about.data_period));
  }
  [["filters", T("filters")], ["missing", T("missing")], ["assumptions", T("assumptions")]].forEach(function (pair) {
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

// P105: the welcome screen shows only while the chat is empty.
function updateWelcome() {
  const empty = messagesEl.children.length === 0;
  welcomeEl.hidden = !empty;
  // P107: an empty chat centres the headline, the message box and the suggestions
  document.body.classList.toggle("empty", empty);
}

function addQuestion(text) {
  const turn = el("div", "turn");
  // the bubble follows the page side; the text inside follows its own language
  const q = el("div", "msg user");
  const words = el("span", null, text);
  words.dir = "auto";
  q.appendChild(words);
  turn.appendChild(q);
  messagesEl.appendChild(turn);
  updateWelcome();
  return turn;
}

function addReply(turn, reply) {
  const bot = el("div", "msg bot");
  bot.appendChild(el("div", "bot-label", T("agent")));
  if (reply.refusal && reply.refusal.message) {
    bot.classList.add("refusal");
    bot.appendChild(el("p", null, refusalText(reply.refusal)));
  } else if (reply.answer) {
    bot.appendChild(renderAnswer(String(reply.answer)));
  }
  const tables = reply.tables || [];
  if (tables.length) {
    // P104: the numbers sit under the answer in one closed box, so the answer is read first
    const numbers = el("details", "numbers");
    numbers.appendChild(
      el("summary", null, T("numbers")(tables.length))
    );
    tables.forEach(function (t) {
      numbers.appendChild(renderTable(t));
    });
    bot.appendChild(numbers);
  }
  const steps = reply.steps || [];
  if (steps.length) {
    const box = el("div", "steps");
    box.appendChild(el("h4", null, T("steps")));
    const ul = el("ul");
    steps.forEach(function (s) {
      ul.appendChild(stepItem(String(s)));
    });
    box.appendChild(ul);
    bot.appendChild(box);
  }
  turn.appendChild(bot);
}

function addNoServer(turn) {
  addReply(turn, { refusal: { message: T("noServer") } });
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
  fitInput();
  const turn = addQuestion(text);
  const working = el("div", "msg working", T("working"));
  turn.appendChild(working);
  turn.scrollIntoView({ block: "start" });

  // P106: the page language; "he" makes the backend ask the AI for a Hebrew answer.
  const body = { message: text, language: lang };
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
    messagesEl.appendChild(el("div", "msg refusal", T("noServer")));
    updateWelcome();
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

// P107: the message box grows with its text, up to the CSS max-height.
function fitInput() {
  inputEl.style.height = "auto";
  inputEl.style.height = inputEl.scrollHeight + "px";
}
inputEl.addEventListener("input", fitInput);

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
  updateWelcome();
  window.scrollTo(0, 0);
  inputEl.focus();
});

// ---------- Example questions and the "How the score works" panel (P105) ----------

document.querySelectorAll("button[data-q]").forEach(function (b) {
  b.addEventListener("click", function () {
    if (busy) return;
    inputEl.value = b.getAttribute("data-q");
    send();
  });
});

function openMethod() {
  if (typeof methodEl.showModal === "function") methodEl.showModal();
  else methodEl.setAttribute("open", "");
}
document.querySelectorAll(".open-method").forEach(function (b) {
  b.addEventListener("click", openMethod);
});

methodEl.querySelectorAll("[data-close]").forEach(function (b) {
  b.addEventListener("click", function () {
    if (typeof methodEl.close === "function") methodEl.close();
    else methodEl.removeAttribute("open");
  });
});

methodEl.addEventListener("click", function (e) {
  if (e.target === methodEl) methodEl.close(); // a click on the dark backdrop closes it
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
    recognition.lang = T("speech");
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = function (event) {
      const spoken = event.results[0][0].transcript;
      inputEl.value = inputEl.value.trim() ? inputEl.value.trim() + " " + spoken : spoken;
    };
    recognition.onend = function () {
      recognition = null;
      micBtn.textContent = T("mic");
    };
    try {
      recognition.start();
      micBtn.textContent = T("stop");
    } catch (e) {
      recognition = null;
    }
  });
}

// ---------- Language: English or Hebrew, right to left (P106) ----------

const langBtn = document.getElementById("lang-toggle");

function applyLang(next) {
  lang = next === "he" ? "he" : "en";
  try {
    localStorage.setItem("lang", lang);
  } catch (e) {
    // storage blocked: the choice lasts until the page is reloaded
  }
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
  document.title = lang === "he" ? "סוכן השקעות בשדות תעופה בארה״ב" : "US Airport Investment Agent";
  langBtn.setAttribute("aria-label", T("otherLang")); // the flag and the name are in index.html
  inputEl.placeholder = T("placeholder");
  inputEl.setAttribute("aria-label", T("question"));
  micBtn.title = T("speak");
  micBtn.setAttribute("aria-label", T("speak"));
  if (micBtn.textContent !== TEXT.en.stop && micBtn.textContent !== TEXT.he.stop) micBtn.textContent = T("mic");
  showChatId();
}

langBtn.addEventListener("click", function () {
  if (busy) return;
  applyLang(lang === "he" ? "en" : "he");
  // draw the chat again so its labels ("How I got this", ...) switch language too
  messagesEl.replaceChildren();
  updateWelcome();
  reloadChat();
});

let savedLang = null;
try {
  savedLang = localStorage.getItem("lang");
} catch (e) {
  savedLang = null;
}
applyLang(savedLang === "he" ? "he" : "en");
reloadChat();
