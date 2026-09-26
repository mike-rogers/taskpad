/* TaskPad card: list, create, and edit periodic chores.
 * Served by the taskpad integration; no build step, no dependencies.
 * Usage in a dashboard:  type: custom:taskpad-card
 */

console.info("[taskpad-card] evaluating (v0.6.0)");

const UNITS = ["days", "weeks", "months"];
const UNIT_DAYS = { days: 1, weeks: 7, months: 30 };

function fmtDate(iso) {
  if (!iso) return "no date";
  const [y, m, d] = iso.split("-").map(Number);
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[m - 1]} ${d}`;
}

function daysLeft(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const due = new Date(y, m - 1, d, 12);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
  return Math.round((due - today) / 86400000);
}

function daysText(n) {
  if (n === null) return "";
  if (n < 0) return `${-n}d late`;
  if (n === 0) return "today";
  if (n === 1) return "1 day";
  return `${n} days`;
}

function urgencyColor(n, blocked) {
  if (blocked) return "var(--secondary-text-color)";
  if (n === null) return "var(--secondary-text-color)";
  if (n < 0) return "#e53935";
  if (n <= 2) return "#fb8c00";
  if (n <= 7) return "#fdd835";
  return "#43a047";
}

function todayPlus(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

class TaskpadCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._editing = null; // null | {} (new) | task object (edit)
    this._dueTouched = false;
  }

  setConfig(config) {
    this._config = { entity: "todo.taskpad", title: "TaskPad", ...(config || {}) };
    // If hass arrived first (rebuild flows), render now that config exists.
    if (this._hass) this.hass = this._hass;
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    // hass can arrive before setConfig in rebuild flows; render waits.
    if (!this._config) return;
    const state = hass.states[this._config.entity];
    const tasks = state ? state.attributes.tasks || [] : null;
    const snapshot = JSON.stringify(tasks);
    // Don't clobber the form while the user is typing in it.
    if (this._editing !== null && snapshot === this._snapshot) return;
    this._snapshot = snapshot;
    this._tasks = tasks;
    this._render();
  }

  _call(service, data) {
    this._hass.callService("taskpad", service, data);
  }

  // ---- form -------------------------------------------------------------

  _openForm(task) {
    this._editing = task || {};
    this._dueTouched = !!task;
    this._render();
  }

  _closeForm() {
    this._editing = null;
    this._render();
  }

  _save() {
    const q = (sel) => this.shadowRoot.querySelector(sel);
    const name = q("#f-name").value.trim();
    const due = q("#f-due").value;
    const value = parseInt(q("#f-value").value, 10);
    const unit = q("#f-unit").value;
    const prep = q("#f-prep").value.trim();
    if (!name || !due || !(value > 0)) {
      q("#f-error").textContent = "Name, due date, and a positive period are required.";
      return;
    }
    const data = {
      name,
      due,
      interval_value: value,
      interval_unit: unit,
      prep_text: prep,
    };
    if (this._editing.uid) {
      this._call("update_task", { uid: this._editing.uid, ...data });
    } else {
      this._call("add_task", data);
    }
    this._closeForm();
  }

  _syncDueDefault() {
    // For new tasks, keep due = today + period until the user edits it.
    if (this._editing.uid || this._dueTouched) return;
    const q = (sel) => this.shadowRoot.querySelector(sel);
    const value = parseInt(q("#f-value").value, 10);
    const unit = q("#f-unit").value;
    if (value > 0) q("#f-due").value = todayPlus(value * UNIT_DAYS[unit]);
  }

  _formHtml() {
    const t = this._editing;
    const isEdit = !!t.uid;
    const value = t.interval_value ?? 30;
    const unit = UNITS.includes(t.interval_unit) ? t.interval_unit : "days";
    const due = t.due ?? todayPlus(value * UNIT_DAYS[unit]);
    const options = UNITS.map(
      (u) => `<option value="${u}" ${u === unit ? "selected" : ""}>${u}</option>`
    ).join("");
    return `
      <div class="form">
        <div class="form-title">${isEdit ? "Edit task" : "New task"}</div>
        <label>Name
          <input id="f-name" type="text" value="${t.name ? escapeHtml(t.name) : ""}"
                 placeholder="Change furnace air filter">
        </label>
        <label>Due
          <input id="f-due" type="date" value="${due}">
        </label>
        <div class="row2">
          <label>Every
            <input id="f-value" type="number" min="1" value="${value}">
          </label>
          <label>Unit
            <select id="f-unit">${options}</select>
          </label>
        </div>
        <label>Dependency task (spawned on long-press)
          <input id="f-prep" type="text"
                 value="${t.prep_text ? escapeHtml(t.prep_text) : ""}"
                 placeholder="Call vet and pick up flea meds">
        </label>
        <div id="f-error" class="error"></div>
        <div class="buttons">
          <button class="primary" id="f-save">Save</button>
          <button id="f-cancel">Cancel</button>
        </div>
      </div>`;
  }

  // ---- rendering --------------------------------------------------------

  _rowHtml(t) {
    const n = daysLeft(t.due);
    const color = urgencyColor(n, t.blocked);
    const meta = t.prep
      ? `due ${fmtDate(t.due)} · prerequisite`
      : `due ${fmtDate(t.due)} · every ${t.interval_value} ${t.interval_unit}` +
        (t.blocked ? " · waiting on prep" : "");
    const days = t.blocked ? `(${daysText(n)})` : daysText(n);
    const cls = ["task", t.prep ? "prep" : "", t.blocked ? "blocked" : ""].join(" ");
    const buttons = t.prep
      ? `<button data-act="complete" data-uid="${t.uid}" title="Done">&#10003;</button>`
      : `<button data-act="complete" data-uid="${t.uid}" title="Done">&#10003;</button>
         <button data-act="block" data-uid="${t.uid}" title="Needs prep first"
                 ${t.blocked ? "disabled" : ""}>&#8869;</button>
         <button data-act="edit" data-uid="${t.uid}" title="Edit">&#9998;</button>`;
    return `
      <div class="${cls}" style="--stripe:${color}">
        <div class="text">
          <div class="name">${escapeHtml(t.name)}</div>
          <div class="meta">${meta}</div>
        </div>
        <div class="days" style="color:${color}">${days}</div>
        <div class="actions">${buttons}</div>
      </div>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    let body;
    if (this._tasks === null || this._tasks === undefined) {
      body = `<div class="empty">Entity ${this._config.entity} not found.</div>`;
    } else if (this._editing !== null) {
      body = this._formHtml();
    } else {
      // Preps render directly beneath their parent task.
      const roots = this._tasks.filter((t) => !t.prep);
      const preps = this._tasks.filter((t) => t.prep);
      const ordered = [];
      for (const t of roots) {
        ordered.push(t);
        for (const p of preps) if (p.parent_uid === t.uid) ordered.push(p);
      }
      for (const p of preps) {
        if (!roots.some((t) => t.uid === p.parent_uid)) ordered.push(p);
      }
      body = ordered.length
        ? ordered.map((t) => this._rowHtml(t)).join("")
        : `<div class="empty">All caught up!</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 16px 16px; }
        .header { display: flex; align-items: center; justify-content: space-between;
                  margin-bottom: 8px; }
        .title { font-size: 1.2em; font-weight: 500; }
        .header button, .actions button, .buttons button {
          background: none; border: 1px solid var(--divider-color);
          color: var(--primary-text-color); border-radius: 6px;
          padding: 4px 10px; cursor: pointer; font-size: 1em; }
        .buttons .primary { background: var(--primary-color);
          border-color: var(--primary-color);
          color: var(--text-primary-color, #fff); }
        .task { display: flex; align-items: center; gap: 10px;
                border-left: 4px solid var(--stripe);
                background: var(--secondary-background-color);
                border-radius: 8px; padding: 8px 10px; margin: 6px 0; }
        .task.prep { margin-left: 24px; }
        .task.blocked .name { color: var(--secondary-text-color); }
        .text { flex: 1; min-width: 0; }
        .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis;
                white-space: nowrap; }
        .meta { font-size: 0.85em; color: var(--secondary-text-color); }
        .days { font-weight: 600; white-space: nowrap; }
        .actions { display: flex; gap: 4px; }
        .actions button[disabled] { opacity: 0.4; cursor: default; }
        .empty { color: var(--secondary-text-color); padding: 12px 0; }
        .form label { display: block; margin: 8px 0; font-size: 0.9em;
                      color: var(--secondary-text-color); }
        .form input, .form select { display: block; width: 100%;
          box-sizing: border-box; margin-top: 2px; padding: 6px 8px;
          font-size: 1em; color: var(--primary-text-color);
          background: var(--secondary-background-color);
          border: 1px solid var(--divider-color); border-radius: 6px; }
        .form .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .form-title { font-weight: 500; margin-bottom: 4px; }
        .error { color: #e53935; font-size: 0.85em; min-height: 1.2em; }
        .buttons { display: flex; gap: 8px; justify-content: flex-end; }
      </style>
      <ha-card>
        <div class="header">
          <div class="title">${escapeHtml(this._config.title)}</div>
          ${this._editing === null ? '<button id="add">+ Add</button>' : ""}
        </div>
        ${body}
      </ha-card>`;

    const q = (sel) => this.shadowRoot.querySelector(sel);
    if (this._editing !== null) {
      q("#f-save").addEventListener("click", () => this._save());
      q("#f-cancel").addEventListener("click", () => this._closeForm());
      q("#f-due").addEventListener("input", () => (this._dueTouched = true));
      q("#f-value").addEventListener("input", () => this._syncDueDefault());
      q("#f-unit").addEventListener("change", () => this._syncDueDefault());
    } else {
      const add = q("#add");
      if (add) add.addEventListener("click", () => this._openForm(null));
      this.shadowRoot.querySelectorAll(".actions button").forEach((btn) => {
        btn.addEventListener("click", () => {
          const uid = btn.dataset.uid;
          const act = btn.dataset.act;
          if (act === "complete") this._call("complete", { task: uid });
          else if (act === "block") this._call("block", { task: uid });
          else if (act === "edit") {
            const task = this._tasks.find((t) => t.uid === uid);
            if (task) this._openForm(task);
          }
        });
      });
    }
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML.replace(/"/g, "&quot;");
}

try {
  customElements.define("taskpad-card", TaskpadCard);
} catch (err) {
  console.error("[taskpad-card] define failed:", err);
}
console.info(
  "[taskpad-card] registered:",
  !!customElements.get("taskpad-card")
);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "taskpad-card",
  name: "TaskPad Card",
  description: "List, create, and edit TaskPad periodic chores.",
});
