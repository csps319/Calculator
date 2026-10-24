"use strict";

/* =========================================================================
   Remediation Console - frontend logic.
   The browser only collects input and displays results. Every calculation
   is done by the Flask API, so the maths and validation live in one place.
   ========================================================================= */

// ---------- Element references ----------
const apiStatus = document.getElementById("api-status");
const apiStatusText = document.getElementById("api-status-text");
const tabs = document.querySelectorAll('[role="tab"]');
const calculatorPanel = document.getElementById("panel-calculator");

const display = document.getElementById("display");
const displayExpression = document.getElementById("display-expression");
const displayValue = document.getElementById("display-value");
const displayError = document.getElementById("display-error");
const keypad = document.getElementById("keypad");
const equalsKey = keypad.querySelector('[data-input="="]');
const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");
const historyClear = document.getElementById("history-clear");

const slaInputs = document.querySelectorAll("[data-sla-severity]");
const dueForm = document.getElementById("due-date-form");
const dueSeverity = document.getElementById("due-severity");
const dueDiscovered = document.getElementById("due-discovered");
const dueSubmit = document.getElementById("due-submit");
const dueResult = document.getElementById("due-result");
const dueResultDate = document.getElementById("due-result-date");
const dueResultMeta = document.getElementById("due-result-meta");
const dueError = document.getElementById("due-error");

const recordsForm = document.getElementById("records-form");
const recordsContainer = document.getElementById("records");
const recordTemplate = document.getElementById("record-template");
const addRecordButton = document.getElementById("add-record");
const recordsSubmit = document.getElementById("records-submit");
const recordsError = document.getElementById("records-error");
const stats = document.getElementById("stats");
const statMttr = document.getElementById("stat-mttr");
const statMttrMeta = document.getElementById("stat-mttr-meta");
const statCompliance = document.getElementById("stat-compliance");
const statComplianceMeta = document.getElementById("stat-compliance-meta");
const ringValue = document.getElementById("ring-value");

/* =========================================================================
   API helpers
   ========================================================================= */
const REQUEST_TIMEOUT_MS = 8000;

function setApiStatus(state) {
  const labels = { checking: "Checking API…", online: "API online", offline: "API offline · retry" };
  apiStatus.dataset.state = state;
  apiStatusText.textContent = labels[state];
}

// Sends a request and returns the parsed JSON, or throws an Error whose
// message is friendly enough to show directly to the user.
async function requestJson(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { ...options, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (error) {
    // fetch only rejects when the server can't be reached at all (or we timed out).
    setApiStatus("offline");
    if (error.name === "TimeoutError") {
      throw new Error("The server took too long to respond. Please try again.");
    }
    throw new Error("Can't reach the calculation server. Make sure the backend is running, then try again.");
  }
  setApiStatus("online");

  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error(`The server sent an unexpected response (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    throw new Error((data && data.error) || `Request failed (HTTP ${response.status}).`);
  }
  return data;
}

function postJson(path, body) {
  return requestJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* =========================================================================
   Tabs
   ========================================================================= */
function selectTab(selectedTab) {
  tabs.forEach((tab) => {
    const isSelected = tab === selectedTab;
    tab.setAttribute("aria-selected", String(isSelected));
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !isSelected;
  });
}

tabs.forEach((tab) => tab.addEventListener("click", () => selectTab(tab)));

/* =========================================================================
   Calculator
   tokens always alternate: number, operator, number, operator, ...
     e.g. 12 + -3 × 4  ->  ["12", "+", "-3", "*", "4"]
   So an EVEN length means the next thing typed must be a number.
   A lone "-" in a number position means "a negative number is being typed".
   ========================================================================= */
const OPERATORS = ["+", "-", "*", "/"];
const DISPLAY_SYMBOLS = { "+": "+", "-": "−", "*": "×", "/": "÷" };
const VALID_INPUTS = new Set([..."0123456789", ".", ...OPERATORS, "=", "backspace", "clear"]);
const MAX_DIGITS_PER_NUMBER = 20;
const MAX_HISTORY = 8;

const calc = {
  tokens: [],
  justEvaluated: false, // true right after "=", so the next digit starts a new calculation
  isBusy: false,        // true while waiting for the API
  error: "",
  previous: "",         // the expression shown above the result, e.g. "2 + 3 ="
};

function isExpectingNumber() {
  return calc.tokens.length % 2 === 0;
}

function startFreshIfEvaluated() {
  if (calc.justEvaluated) {
    calc.tokens = [];
    calc.justEvaluated = false;
  }
}

function inputDigit(digit) {
  startFreshIfEvaluated();
  if (isExpectingNumber()) {
    calc.tokens.push(digit);
    return;
  }
  const last = calc.tokens.length - 1;
  const current = calc.tokens[last];
  if (current.replace(/[-.]/g, "").length >= MAX_DIGITS_PER_NUMBER) return;

  if (current === "0") calc.tokens[last] = digit;             // no leading zeros: "07" -> "7"
  else if (current === "-0") calc.tokens[last] = "-" + digit;
  else calc.tokens[last] = current + digit;
}

function inputDecimal() {
  startFreshIfEvaluated();
  if (isExpectingNumber()) {
    calc.tokens.push("0.");
    return;
  }
  const last = calc.tokens.length - 1;
  const current = calc.tokens[last];
  if (current.includes(".")) return;                         // only one decimal point per number
  calc.tokens[last] = current === "-" ? "-0." : current + ".";
}

function inputOperator(operator) {
  calc.justEvaluated = false; // keep the previous result as the first number
  const tokens = calc.tokens;

  if (tokens.length === 0) {
    // Nothing typed yet: "-" starts a negative number, other operators apply to 0.
    if (operator === "-") tokens.push("-");
    else tokens.push("0", operator);
    return;
  }

  if (isExpectingNumber()) {
    // The last token is an operator.
    if (operator === "-") tokens.push("-");          // "5 × −" starts a negative number
    else tokens[tokens.length - 1] = operator;       // repeated operator replaces the last one
    return;
  }

  const last = tokens.length - 1;
  if (tokens[last] === "-") {
    // A lone minus with no digits yet.
    if (operator === "-") return;                    // ignore a second minus sign
    tokens.pop();                                    // drop the minus...
    if (tokens.length > 0) tokens[tokens.length - 1] = operator; // ...and replace the operator before it
    return;
  }

  if (tokens[last].endsWith(".")) tokens[last] = tokens[last].slice(0, -1); // "5." -> "5"
  tokens.push(operator);
}

function backspace() {
  calc.justEvaluated = false;
  const tokens = calc.tokens;
  if (tokens.length === 0) return;
  if (isExpectingNumber()) {
    tokens.pop(); // remove an operator
    return;
  }
  const last = tokens.length - 1;
  const shorter = tokens[last].slice(0, -1);
  if (shorter === "") tokens.pop();
  else tokens[last] = shorter;
}

function clearAll() {
  calc.tokens = [];
  calc.justEvaluated = false;
}

// Turn ["12", "+", "-3"] into "12 + −3" for display.
function formatTokens(tokens) {
  return tokens
    .map((token, index) => (index % 2 === 1 ? DISPLAY_SYMBOLS[token] : token.replace("-", "−")))
    .join(" ");
}

function render() {
  const text = calc.tokens.length > 0 ? formatTokens(calc.tokens) : "0";
  displayValue.textContent = text;
  displayValue.dataset.size = text.length > 22 ? "sm" : text.length > 12 ? "md" : "lg";
  displayExpression.textContent = calc.previous;
  displayError.textContent = calc.error;
  display.classList.toggle("is-busy", calc.isBusy);
  equalsKey.disabled = calc.isBusy;
}

function flashResult() {
  displayValue.classList.remove("flash");
  void displayValue.offsetWidth; // force a reflow so the CSS animation can play again
  displayValue.classList.add("flash");
}

async function evaluate() {
  if (calc.tokens.length === 0 || calc.justEvaluated) return;

  // The backend validates everything (e.g. "5 +"), so we send what we have
  // and show its error message instead of duplicating the rules here.
  const expression = calc.tokens.join(" ");
  const shownExpression = formatTokens(calc.tokens);

  calc.error = "";
  calc.isBusy = true;
  render();
  try {
    const data = await postJson("/api/calculate", { expression });
    calc.tokens = [data.result];
    calc.justEvaluated = true;
    calc.previous = `${shownExpression} =`;
    addHistory(shownExpression, data.result);
    flashResult();
  } catch (error) {
    calc.error = error.message;
  } finally {
    calc.isBusy = false;
    render();
  }
}

// Single entry point for both button clicks and keyboard input.
function handleInput(input) {
  if (calc.isBusy) return; // ignore input while waiting for the API
  if (input === "=") {
    evaluate();
    return;
  }
  calc.error = "";
  calc.previous = "";
  if (/^[0-9]$/.test(input)) inputDigit(input);
  else if (input === ".") inputDecimal();
  else if (OPERATORS.includes(input)) inputOperator(input);
  else if (input === "backspace") backspace();
  else if (input === "clear") clearAll();
  render();
}

// ---------- History ----------
function addHistory(expression, result) {
  const item = document.createElement("li");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "history-item";

  const expressionText = document.createElement("span");
  expressionText.className = "history-expr";
  expressionText.textContent = `${expression} =`;

  const resultText = document.createElement("span");
  resultText.className = "history-result";
  resultText.textContent = result;

  button.append(expressionText, resultText);
  button.addEventListener("click", () => useResult(result));
  item.append(button);
  historyList.prepend(item);

  while (historyList.children.length > MAX_HISTORY) historyList.lastElementChild.remove();
  historyEmpty.hidden = true;
}

function useResult(result) {
  if (calc.isBusy) return;
  // If an operator is waiting for a number, insert the result there; otherwise start from it.
  if (calc.tokens.length > 0 && isExpectingNumber()) calc.tokens.push(result);
  else calc.tokens = [result];
  calc.justEvaluated = false;
  calc.error = "";
  calc.previous = "";
  render();
}

historyClear.addEventListener("click", () => {
  historyList.replaceChildren();
  historyEmpty.hidden = false;
});

// ---------- Mouse / touch ----------
keypad.addEventListener("click", (event) => {
  const key = event.target.closest("[data-input]");
  if (key) handleInput(key.dataset.input);
});

// ---------- Keyboard ----------
const KEY_TO_INPUT = {
  Enter: "=",
  Backspace: "backspace",
  Escape: "clear",
  Delete: "clear",
  x: "*",
  X: "*",
  ",": ".",
};

function pressKeyVisually(input) {
  const key = keypad.querySelector(`[data-input="${input}"]`);
  if (!key) return;
  key.classList.add("pressed");
  setTimeout(() => key.classList.remove("pressed"), 120);
}

document.addEventListener("keydown", (event) => {
  if (calculatorPanel.hidden) return;                          // only on the calculator tab
  if (event.ctrlKey || event.metaKey || event.altKey) return; // leave browser shortcuts alone
  if (event.target.matches("input, select, textarea")) return;

  const input = KEY_TO_INPUT[event.key] ?? event.key;
  if (!VALID_INPUTS.has(input)) return;

  event.preventDefault(); // e.g. stops "/" opening Firefox's quick find
  handleInput(input);
  pressKeyVisually(input);
});

/* =========================================================================
   Security metrics
   ========================================================================= */

// Only send SLA fields the user filled in; the backend applies defaults for the rest.
function readSlaOverrides() {
  const overrides = {};
  slaInputs.forEach((input) => {
    const severity = input.dataset.slaSeverity;
    if (input.validity.badInput) {
      overrides[severity] = null; // text the browser couldn't parse: let the backend report it
    } else if (input.value.trim() !== "") {
      overrides[severity] = Number(input.value);
    }
  });
  return overrides;
}

async function loadSlaDefaults() {
  setApiStatus("checking");
  try {
    const data = await requestJson("/api/sla-defaults");
    slaInputs.forEach((input) => {
      const days = data.sla_days[input.dataset.slaSeverity];
      input.placeholder = String(days);
      if (input.value.trim() === "") input.value = days; // never overwrite the user's edits
    });
  } catch (error) {
    // The status pill already shows "API offline". Blank fields mean "use defaults" later.
  }
}

async function withBusyButton(button, task) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Calculating…";
  try {
    await task();
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

// Today's date as YYYY-MM-DD in the user's LOCAL time zone.
// (new Date().toISOString() uses UTC, which is "yesterday" in Sydney until 11am.)
function todayIso() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

// "2026-11-08" -> "Sun, 8 Nov 2026". We build the Date from its parts because
// new Date("2026-11-08") is parsed as UTC midnight and can show the wrong day.
function formatLongDate(isoDate) {
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
  });
}

// ---------- SLA due date ----------
dueForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  dueError.textContent = "";

  await withBusyButton(dueSubmit, async () => {
    try {
      const data = await postJson("/api/sla/due-date", {
        severity: dueSeverity.value,
        discovered: dueDiscovered.value,
        sla_days: readSlaOverrides(),
      });
      dueResultDate.textContent = formatLongDate(data.due_date);
      dueResultMeta.textContent =
        `${data.due_date} · ${data.severity} · ${data.sla_days}-day SLA from ${formatLongDate(data.discovered)}`;
      dueResult.hidden = false;
    } catch (error) {
      dueResult.hidden = true;
      dueError.textContent = error.message;
    }
  });
});

// ---------- Remediation records ----------
const SAMPLE_RECORDS = [
  { severity: "Critical", discovered: "2026-09-01", fixed: "2026-09-10" },
  { severity: "High", discovered: "2026-08-03", fixed: "2026-09-14" },
  { severity: "Medium", discovered: "2026-06-15", fixed: "2026-08-20" },
];

function updateRemoveButtons() {
  const rows = recordsContainer.querySelectorAll(".record-row");
  rows.forEach((row) => {
    row.querySelector(".record-remove").disabled = rows.length === 1; // always keep one row
  });
}

function clearRecordResults() {
  recordsContainer.querySelectorAll(".record-row").forEach((row) => {
    row.classList.remove("has-error");
    const cell = row.querySelector(".record-result");
    cell.textContent = "—";
    delete cell.dataset.status;
    cell.removeAttribute("title");
  });
}

function addRecordRow(record = { severity: "High", discovered: "", fixed: "" }) {
  const row = recordTemplate.content.firstElementChild.cloneNode(true);
  row.querySelector(".record-severity").value = record.severity;
  row.querySelector(".record-discovered").value = record.discovered;
  row.querySelector(".record-fixed").value = record.fixed;
  row.querySelector(".record-remove").addEventListener("click", () => {
    row.remove();
    updateRemoveButtons();
    clearRecordResults();
  });
  recordsContainer.append(row);
  updateRemoveButtons();
  return row;
}

function showRecordResults(rows, results) {
  rows.forEach((row, index) => {
    const result = results[index];
    const cell = row.querySelector(".record-result");
    cell.textContent = `${result.days_to_remediate}d · ${result.within_sla ? "Within SLA" : "Breached"}`;
    cell.dataset.status = result.within_sla ? "ok" : "breach";
    cell.title = `Due ${result.due_date}`;
  });
}

function showStats(data) {
  const plural = data.total_count === 1 ? "" : "s";
  statMttr.textContent = String(data.mttr_days);
  statMttrMeta.textContent = `Average across ${data.total_count} record${plural}`;
  statCompliance.textContent = String(data.sla_compliance_percent);
  statComplianceMeta.textContent = `${data.within_sla_count} of ${data.total_count} fixed within SLA`;
  stats.hidden = false;

  const percent = data.sla_compliance_percent;
  const color = percent >= 90 ? "var(--ok)" : percent >= 70 ? "var(--medium)" : "var(--critical)";
  ringValue.style.setProperty("--ring-color", color);

  // Reset the ring to empty, force a reflow, then set the value so the fill animates every time.
  ringValue.style.strokeDashoffset = "100";
  void ringValue.getBoundingClientRect();
  ringValue.style.strokeDashoffset = String(100 - percent);
}

// Backend errors look like "Record 2: Fixed date is required" - highlight that row.
function highlightRecordFromError(rows, message) {
  const match = /^Record (\d+)/.exec(message);
  if (match) rows[Number(match[1]) - 1]?.classList.add("has-error");
}

addRecordButton.addEventListener("click", () => {
  const row = addRecordRow();
  clearRecordResults();
  row.querySelector(".record-severity").focus();
});

recordsContainer.addEventListener("input", clearRecordResults); // results go stale when inputs change

recordsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearRecordResults();
  recordsError.textContent = "";

  const rows = [...recordsContainer.querySelectorAll(".record-row")];
  const records = rows.map((row) => ({
    severity: row.querySelector(".record-severity").value,
    discovered: row.querySelector(".record-discovered").value,
    fixed: row.querySelector(".record-fixed").value,
  }));

  await withBusyButton(recordsSubmit, async () => {
    try {
      const data = await postJson("/api/sla/remediation-metrics", {
        records,
        sla_days: readSlaOverrides(),
      });
      showRecordResults(rows, data.records);
      showStats(data);
    } catch (error) {
      recordsError.textContent = error.message;
      highlightRecordFromError(rows, error.message);
    }
  });
});

/* =========================================================================
   Start-up
   ========================================================================= */
apiStatus.addEventListener("click", loadSlaDefaults); // click the pill to retry
SAMPLE_RECORDS.forEach((record) => addRecordRow(record));
dueDiscovered.value = todayIso();
render();
loadSlaDefaults();