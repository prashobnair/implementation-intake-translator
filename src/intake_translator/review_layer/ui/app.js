"use strict";
const root = document.getElementById("main");
const live = document.getElementById("live");
let csrf = sessionStorage.getItem("csrf") || "";
let me = null;
const SLA_WARN_H = 4, SLA_BREACH_H = 24;

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "text") node.textContent = v; else node.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids) node.append(kid);
  return node;
}
function announce(msg) { live.textContent = msg; }
async function api(method, url, body) {
  const headers = { "Content-Type": "application/json" };
  if (method !== "GET") headers["X-CSRF-Token"] = csrf;
  const res = await fetch(url, { method, headers, credentials: "same-origin", body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}
function fmtAge(hours) { return hours === null ? "unknown" : hours < 1 ? "<1h" : hours < 48 ? Math.floor(hours) + "h" : Math.floor(hours / 24) + "d"; }
function slaBadge(hours, status) {
  if (status === "approved") return el("span", { class: "badge ok", text: "SLA: done" });
  if (hours === null) return el("span", { class: "badge warn", text: "SLA: unknown" });
  if (hours >= SLA_BREACH_H) return el("span", { class: "badge bad", text: "SLA: breached" });
  if (hours >= SLA_WARN_H) return el("span", { class: "badge warn", text: "SLA: at risk" });
  return el("span", { class: "badge ok", text: "SLA: on time" });
}
function ageHours(received, now) { return received ? (new Date(now) - new Date(received)) / 3600000 : null; }

function showLogin(message) {
  root.replaceChildren();
  const form = el("form", { id: "login", "aria-labelledby": "lh" },
    el("h2", { id: "lh", text: "Sign in" }),
    el("p", { class: "error", role: "alert", text: message || "" }),
    el("p", {}, el("label", { for: "u", text: "Username" }), el("br"), el("input", { id: "u", name: "username", autocomplete: "username", required: true })),
    el("p", {}, el("label", { for: "p", text: "Password" }), el("br"), el("input", { id: "p", name: "password", type: "password", autocomplete: "current-password", required: true })),
    el("button", { type: "submit", text: "Sign in" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const r = await api("POST", "/login", { username: form.username.value, password: form.password.value });
    if (r.status !== 200) return showLogin("Sign-in failed. Check the username and password.");
    csrf = r.data.csrf_token; sessionStorage.setItem("csrf", csrf);
    await boot();
  });
  root.append(form);
  document.getElementById("u").focus();
}

async function boot() {
  const r = await api("GET", "/me");
  if (r.status !== 200) { document.getElementById("who").textContent = ""; document.getElementById("logout").hidden = true; return showLogin(); }
  me = r.data;
  document.getElementById("who").textContent = me.username;
  document.getElementById("logout").hidden = false;
  route();
}
document.getElementById("logout").addEventListener("click", async () => {
  await api("POST", "/logout"); sessionStorage.removeItem("csrf"); csrf = ""; me = null; await boot();
});
window.addEventListener("hashchange", () => me && route());

function route() {
  const m = location.hash.match(/^#\/t\/([^/]+)\/c\/(.+)$/);
  if (m) return showCase(decodeURIComponent(m[1]), decodeURIComponent(m[2]));
  showQueue();
}

async function showQueue() {
  const tenants = Object.keys(me.memberships).sort();
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const state = { tenant: params.get("tenant") || tenants[0], status: "", age: "", ai: "", override: "", q: "" };
  root.replaceChildren(el("h2", { text: "Review queue", tabindex: "-1", id: "qh" }));
  const sel = (id, label, opts) => el("label", { for: id, text: label },
    (() => { const s = el("select", { id }); for (const [v, t] of opts) s.append(el("option", { value: v, text: t })); return s; })());
  const filters = el("div", { class: "filters", role: "search", "aria-label": "Queue filters" },
    sel("f-tenant", "Tenant", tenants.map((t) => [t, t])),
    sel("f-status", "Status", [["", "Any"], ["needs_review", "Needs review"], ["needs_re_review", "Needs re-review"], ["deferred", "Deferred"], ["approved", "Approved"]]),
    sel("f-age", "Age", [["", "Any"], ["lt4", "Under 4 hours"], ["4to24", "4 to 24 hours"], ["gt24", "Over 24 hours"]]),
    sel("f-ai", "AI source", [["", "Any"], ["yes", "Has AI source"], ["no", "No AI source"]]),
    sel("f-override", "Override", [["", "Any"], ["yes", "Has override"], ["no", "No override"]]),
    el("label", { for: "f-q", text: "Customer search" }, el("input", { id: "f-q", type: "search" })));
  const tbody = el("tbody");
  const table = el("table", { "aria-label": "Cases" },
    el("thead", {}, el("tr", {}, ...["Case", "Customer", "Status", "Age", "SLA", "AI", "Override"].map((h) => el("th", { scope: "col", text: h })))), tbody);
  const count = el("p", { id: "count" });
  root.append(filters, count, table);
  document.getElementById("f-tenant").value = state.tenant;
  let data = { cases: [], now: new Date().toISOString() };
  async function load() {
    const r = await api("GET", `/tenants/${encodeURIComponent(state.tenant)}/cases`);
    data = r.status === 200 ? r.data : { cases: [], now: new Date().toISOString() };
    draw();
  }
  function draw() {
    const rows = data.cases.filter((c) => {
      const h = ageHours(c.received_at, data.now);
      if (state.status && c.status !== state.status) return false;
      if (state.age === "lt4" && !(h !== null && h < 4)) return false;
      if (state.age === "4to24" && !(h !== null && h >= 4 && h < 24)) return false;
      if (state.age === "gt24" && !(h !== null && h >= 24)) return false;
      if (state.ai && c.has_ai !== (state.ai === "yes")) return false;
      if (state.override && c.has_override !== (state.override === "yes")) return false;
      if (state.q && !String(c.customer).toLowerCase().includes(state.q.toLowerCase())) return false;
      return true;
    });
    tbody.replaceChildren(...rows.map((c) => {
      const h = ageHours(c.received_at, data.now);
      const link = el("a", { href: `#/t/${encodeURIComponent(state.tenant)}/c/${encodeURIComponent(c.event_id)}`, text: c.event_id });
      return el("tr", { "data-case": c.event_id }, el("td", {}, link), el("td", { text: c.customer }),
        el("td", { text: c.status }), el("td", { text: fmtAge(h) }), el("td", {}, slaBadge(h, c.status)),
        el("td", { text: c.has_ai ? "yes" : "no" }), el("td", { text: c.has_override ? "yes" : "no" }));
    }));
    count.textContent = `${rows.length} of ${data.cases.length} cases`;
    announce(count.textContent);
  }
  filters.addEventListener("change", (ev) => {
    const map = { "f-tenant": "tenant", "f-status": "status", "f-age": "age", "f-ai": "ai", "f-override": "override" };
    const key = map[ev.target.id];
    if (!key) return;
    state[key] = ev.target.value;
    if (key === "tenant") load(); else draw();
  });
  document.getElementById("f-q").addEventListener("input", (ev) => { state.q = ev.target.value; draw(); });
  await load();
}

function candidateCell(c, trust, fetched, td) {
  td.append(el("div", {}, el("strong", { text: String(c.value) })));
  td.append(el("div", { class: "src", text: `${c.source} (${trust})` }));
  td.append(el("div", { class: "src", text: "fetched " + (fetched || "unknown") }));
  const id = "ev-" + Math.random().toString(36).slice(2, 8);
  const panel = el("div", { class: "evidence", id, hidden: true });
  panel.append(el("div", { text: `Source: ${c.source}` }), el("div", { text: `Trust: ${trust}` }));
  if (typeof c.quote === "string") {
    const q = el("blockquote", {});
    const at = c.quote.indexOf(String(c.value));
    if (at >= 0) { q.append(c.quote.slice(0, at), el("mark", { text: String(c.value) }), c.quote.slice(at + String(c.value).length)); } else { q.append(c.quote); }
    panel.append(q);
  } else {
    panel.append(el("div", { text: "No quoted evidence for this source." }));
  }
  const btn = el("button", { type: "button", class: "secondary", "aria-expanded": "false", "aria-controls": id, text: "Evidence" });
  btn.addEventListener("click", () => { const open = panel.hidden; panel.hidden = !open; btn.setAttribute("aria-expanded", String(open)); });
  td.append(btn, panel);
}

async function showCase(tenant, eventId) {
  const r = await api("GET", `/tenants/${encodeURIComponent(tenant)}/cases/${encodeURIComponent(eventId)}`);
  root.replaceChildren();
  if (r.status !== 200) { root.append(el("p", { class: "error", role: "alert", text: "Case not available." })); return; }
  const v = r.data, p = v.packet;
  const sources = Object.keys(v.sources).sort((a, b) => a.localeCompare(b));
  const h = el("h2", { id: "ch", tabindex: "-1", text: `Case ${v.event_id}` });
  root.append(el("p", {}, el("a", { href: "#/", text: "Back to queue" })), h,
    el("p", {}, "Status: ", el("span", { class: "badge " + (v.status === "approved" ? "ok" : "warn"), id: "case-status", text: v.status }), ` · version ${v.version}`));
  const names = v.fields.map((f) => f.name);
  const tbody = el("tbody");
  const targets = [];
  for (const f of v.fields) {
    const cands = p.candidates[f.name] || [];
    const conflict = Object.prototype.hasOwnProperty.call(p.conflicts, f.name);
    const missing = f.required && !(f.name in p.resolved) && !conflict;
    if (conflict || missing) targets.push(f.name);
    const tag = conflict ? "Conflict" : missing ? "Required, missing" : (f.name in p.resolved ? "Agreed" : "Optional, empty");
    const head = el("th", { scope: "row" }, f.name + (f.required ? " (required)" : ""), el("div", { class: "tag", text: tag }));
    const row = el("tr", { "data-field": f.name }, head);
    for (const s of sources) {
      const td = el("td", { class: conflict ? "conflict" : missing ? "missing" : "" });
      const c = cands.find((x) => x.source === s);
      if (c) candidateCell(c, v.sources[s], v.received_at, td); else td.append("none");
      row.append(td);
    }
    tbody.append(row);
  }
  root.append(el("table", { "aria-label": "Field by source matrix" },
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Field" }), ...sources.map((s) => el("th", { scope: "col", text: s })))), tbody));
  if (v.amendment) {
    const box = el("section", { class: "diff", "aria-labelledby": "dh" }, el("h3", { id: "dh", text: "Amendment diff" }));
    for (const d of v.amendment.diff) {
      box.append(el("p", { "data-diff": d.field }, `${d.field}: approved ${d.old_approved_value} → candidates ` + d.new_candidates.map((c) => `${c.source}=${c.value}`).join(", ")));
    }
    root.append(box);
  }
  if (v.status === "approved") return;
  const canDecide = ["reviewer", "approver", "admin"].includes(v.role);
  if (!canDecide) { root.append(el("p", { text: "Your role can view this case but not decide." })); return; }
  const form = el("form", { id: "decide", "aria-labelledby": "dech" }, el("h3", { id: "dech", text: "Decisions" }));
  for (const name of targets) {
    const options = (p.conflicts[name] || p.candidates[name] || []);
    const set = el("fieldset", { "data-decision": name }, el("legend", { text: name }));
    const radio = (val, label, extra) => {
      const id = `d-${name}-${val}`;
      return el("div", {}, el("input", { type: "radio", name: "k-" + name, id, value: val, ...extra }), " ", el("label", { for: id, text: label }));
    };
    for (const o of options) set.append(radio("src:" + o.source, `Choose ${o.source}: ${o.value}`));
    set.append(radio("override", "Override with a written value"), radio("defer", "Defer with a customer question"));
    set.append(el("p", {}, el("label", { for: `v-${name}`, text: "Override value" }), " ", el("input", { id: `v-${name}` })),
      el("p", {}, el("label", { for: `r-${name}`, text: "Override rationale (20+ characters)" }), " ", el("input", { id: `r-${name}`, size: "50" })),
      el("p", {}, el("label", { for: `q-${name}`, text: "Customer question" }), " ", el("input", { id: `q-${name}`, size: "50" })));
    form.append(set);
  }
  const msg = el("p", { class: "error", id: "msg", role: "alert" });
  form.append(msg, el("button", { type: "submit", text: "Submit decisions" }));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const decisions = {};
    for (const name of targets) {
      const picked = form.querySelector(`input[name="k-${name}"]:checked`);
      if (!picked) { msg.textContent = `Choose an option for ${name}.`; return; }
      if (picked.value.startsWith("src:")) decisions[name] = { type: "choose_source", source: picked.value.slice(4) };
      else if (picked.value === "override") decisions[name] = { type: "override", value: document.getElementById(`v-${name}`).value, rationale: document.getElementById(`r-${name}`).value };
      else decisions[name] = { type: "defer", question: document.getElementById(`q-${name}`).value };
    }
    const res = await api("POST", `/tenants/${encodeURIComponent(tenant)}/cases/${encodeURIComponent(eventId)}/decisions`, { decisions, expected_version: v.version });
    if (res.status === 201) { announce("Decisions saved"); return showCase(tenant, eventId); }
    msg.textContent = res.status === 409 ? "Someone else changed this case. Reload to see the latest version." : `Could not save (${res.data.detail || res.status}).`;
  });
  root.append(form);
}
boot();
