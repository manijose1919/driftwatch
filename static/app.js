/* DriftWatch dashboard — zero-build vanilla JS SPA. */

const $ = (sel) => document.querySelector(sel);
const state = { endpoints: [], events: [], channels: [], stats: null, editingId: null };
const shapeViews = new Map(); // eventId -> {baseline, observed}; presence = expanded

/* ---------- API helper ---------- */

function authHeaders() {
  const token = localStorage.getItem("dw_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(options.headers || {}) },
  });
  if (resp.status === 401) {
    toast("API token required — set it via the ⚙️ button in the header", true);
    throw new Error("unauthorized");
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* not json */ }
    throw new Error(detail);
  }
  return resp.status === 204 ? null : resp.json();
}

/* ---------- rendering ---------- */

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function relTime(iso) {
  if (!iso) return "never";
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function renderStats() {
  const s = state.stats;
  if (!s) return;
  $("#stats").innerHTML = `
    <div class="stat"><b>${s.endpoints}</b><span>endpoints</span></div>
    <div class="stat good"><b>${s.probes_ok}</b><span>healthy</span></div>
    <div class="stat ${s.open_events ? "alarm" : ""}"><b>${s.open_events}</b><span>open drift</span></div>
    <div class="stat ${s.open_breaking ? "alarm" : ""}"><b>${s.open_breaking}</b><span>breaking</span></div>
    <div class="stat ${s.probes_error ? "alarm" : ""}"><b>${s.probes_error}</b><span>erroring</span></div>`;
}

function statusBadge(ep) {
  if (!ep.is_active) return `<span class="badge paused">paused</span>`;
  return `<span class="badge ${esc(ep.last_status)}">${esc(ep.last_status)}</span>`;
}

function renderEndpoints() {
  const box = $("#endpoints-list");
  if (!state.endpoints.length) {
    box.innerHTML = `<div class="empty">No endpoints yet. Add one — or try the built-in demo:
      <code>http://127.0.0.1:8000/demo/products</code></div>`;
    return;
  }
  box.innerHTML = state.endpoints.map((ep) => `
    <div class="card" data-id="${ep.id}">
      <div class="card-top">
        <span class="card-title">${esc(ep.name)}</span>
        ${statusBadge(ep)}
        ${ep.open_events ? `<span class="badge drift">${ep.open_events} open</span>` : ""}
        <span class="spacer"></span>
        <button class="btn small" data-act="probe">Probe now</button>
      </div>
      <div class="card-sub">${esc(ep.method)} ${esc(ep.url)}</div>
      <div class="card-meta">
        <span>every ${ep.interval_seconds}s</span>
        <span>last probe: ${relTime(ep.last_probed_at)}</span>
        ${ep.last_response_ms != null ? `<span>${ep.last_response_ms.toFixed(0)} ms</span>` : ""}
        ${ep.last_error ? `<span style="color:var(--error)">${esc(ep.last_error)}</span>` : ""}
      </div>
      <div class="card-actions">
        <button class="btn small" data-act="edit">Edit</button>
        <button class="btn small" data-act="toggle">${ep.is_active ? "Pause" : "Resume"}</button>
        <button class="btn small danger" data-act="delete">Delete</button>
      </div>
    </div>`).join("");
}

function renderEvents() {
  const box = $("#events-list");
  const showAcked = $("#show-acked").checked;
  const events = state.events.filter((e) => showAcked || !e.acknowledged);
  if (!events.length) {
    box.innerHTML = `<div class="empty">No drift detected. Quiet skies. 🛰️</div>`;
    return;
  }
  box.innerHTML = events.map((ev) => `
    <div class="card" data-id="${ev.id}">
      <div class="card-top">
        <span class="badge ${esc(ev.severity)}">${esc(ev.severity)}</span>
        <span class="card-title">${esc(ev.endpoint_name)}</span>
        <span class="spacer"></span>
        <span class="card-meta">${relTime(ev.created_at)}</span>
      </div>
      <ul class="changes">
        ${ev.changes.map((c) => `
          <li><span class="badge ${esc(c.severity)}">${esc(c.severity)}</span>
              <span class="path">${esc(c.path)}</span>
              <span class="detail">${esc(c.detail)}</span></li>`).join("")}
      </ul>
      ${renderShapeView(ev)}
      <div class="card-actions">
        ${ev.snapshot_id != null
          ? `<button class="btn small" data-act="shapes">${shapeViews.has(ev.id) ? "Hide shapes" : "View shapes"}</button>` : ""}
        ${ev.acknowledged ? "" : `
          ${ev.snapshot_id != null
            ? `<button class="btn small primary" data-act="accept">Accept as new baseline</button>` : ""}
          <button class="btn small" data-act="ack">Acknowledge</button>`}
      </div>
    </div>`).join("");
}

function renderShapeView(ev) {
  const shapes = shapeViews.get(ev.id);
  if (!shapes) return "";
  const fmt = (s) => (s == null ? "(not recorded)" : JSON.stringify(s, null, 2));
  return `
    <div class="shapes-view">
      <div><h4>Baseline shape</h4><pre>${esc(fmt(shapes.baseline))}</pre></div>
      <div><h4>Observed shape</h4><pre>${esc(fmt(shapes.observed))}</pre></div>
    </div>`;
}

function renderChannels() {
  const box = $("#channels-list");
  if (!state.channels.length) {
    box.innerHTML = `<div class="empty">No alert channels. Add a Discord or Slack webhook to get pinged on drift.</div>`;
    return;
  }
  const icons = { discord: "💬", slack: "📣", webhook: "🔗" };
  box.innerHTML = state.channels.map((ch) => `
    <div class="card" data-id="${ch.id}">
      <div class="card-top">
        <span>${icons[ch.kind] || "🔗"}</span>
        <span class="card-title">${esc(ch.name)}</span>
        <span class="badge ${esc(ch.min_severity)}">${esc(ch.min_severity)}+</span>
        <span class="spacer"></span>
        <button class="btn small" data-act="test">Test</button>
        <button class="btn small danger" data-act="delete">Delete</button>
      </div>
      <div class="card-sub">${esc(ch.kind)} · ${esc(ch.webhook_url)}</div>
    </div>`).join("");
}

/* ---------- data loading ---------- */

async function loadAll() {
  try {
    const [stats, endpoints, events, channels] = await Promise.all([
      api("/api/stats"), api("/api/endpoints"), api("/api/events?limit=100"), api("/api/channels"),
    ]);
    Object.assign(state, { stats, endpoints, events, channels });
    renderStats(); renderEndpoints(); renderEvents(); renderChannels();
  } catch (err) {
    if (err.message !== "unauthorized") toast(`Load failed: ${err.message}`, true);
  }
}

/* ---------- toasts & confirm-on-second-click ---------- */

function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = `toast-msg${isError ? " err" : ""}`;
  el.textContent = msg;
  $("#toast").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function armedConfirm(btn) {
  if (btn.dataset.armed) return true;
  btn.dataset.armed = "1";
  const original = btn.textContent;
  btn.textContent = "Sure?";
  setTimeout(() => { delete btn.dataset.armed; btn.textContent = original; }, 2500);
  return false;
}

/* ---------- endpoint actions ---------- */

$("#endpoints-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = Number(btn.closest(".card").dataset.id);
  const ep = state.endpoints.find((x) => x.id === id);
  try {
    if (btn.dataset.act === "probe") {
      btn.disabled = true; btn.textContent = "Probing…";
      await api(`/api/endpoints/${id}/probe`, { method: "POST" });
      toast("Probe complete");
    } else if (btn.dataset.act === "edit") {
      openEndpointDialog(ep);
      return;
    } else if (btn.dataset.act === "toggle") {
      await api(`/api/endpoints/${id}`, {
        method: "PUT", body: JSON.stringify({ is_active: !ep.is_active }),
      });
    } else if (btn.dataset.act === "delete") {
      if (!armedConfirm(btn)) return;
      await api(`/api/endpoints/${id}`, { method: "DELETE" });
      toast(`Deleted "${ep.name}"`);
    }
    await loadAll();
  } catch (err) { toast(err.message, true); await loadAll(); }
});

$("#events-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = Number(btn.closest(".card").dataset.id);
  try {
    if (btn.dataset.act === "accept") {
      await api(`/api/events/${id}/accept`, { method: "POST" });
      toast("New baseline accepted");
    } else if (btn.dataset.act === "ack") {
      await api(`/api/events/${id}/ack`, { method: "POST" });
    } else if (btn.dataset.act === "shapes") {
      if (shapeViews.has(id)) {
        shapeViews.delete(id);
      } else {
        shapeViews.set(id, await api(`/api/events/${id}/shapes`));
      }
      renderEvents();
      return;
    }
    await loadAll();
  } catch (err) { toast(err.message, true); }
});

$("#channels-list").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = Number(btn.closest(".card").dataset.id);
  try {
    if (btn.dataset.act === "test") {
      btn.disabled = true;
      const res = await api(`/api/channels/${id}/test`, { method: "POST" });
      toast(res.ok ? "Test message delivered ✅" : "Webhook rejected the test message", !res.ok);
      btn.disabled = false;
    } else if (btn.dataset.act === "delete") {
      if (!armedConfirm(btn)) return;
      await api(`/api/channels/${id}`, { method: "DELETE" });
      await loadAll();
    }
  } catch (err) { toast(err.message, true); btn.disabled = false; }
});

$("#show-acked").addEventListener("change", renderEvents);

/* ---------- endpoint dialog ---------- */

function openEndpointDialog(ep = null) {
  state.editingId = ep ? ep.id : null;
  const form = $("#form-endpoint");
  form.reset();
  $("#endpoint-error").textContent = "";
  $("#dlg-endpoint-title").textContent = ep ? `Edit "${ep.name}"` : "Add endpoint";
  if (ep) {
    form.name.value = ep.name;
    form.url.value = ep.url;
    form.method.value = ep.method;
    form.interval_seconds.value = ep.interval_seconds;
    form.headers.value = Object.keys(ep.headers || {}).length ? JSON.stringify(ep.headers, null, 0) : "";
    form.body.value = ep.body || "";
    form.is_active.checked = ep.is_active;
  }
  $("#dlg-endpoint").showModal();
}

$("#btn-add-endpoint").addEventListener("click", () => openEndpointDialog());

$("#form-endpoint").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  let headers = {};
  if (form.headers.value.trim()) {
    try {
      headers = JSON.parse(form.headers.value);
      if (typeof headers !== "object" || Array.isArray(headers) || headers === null) throw new Error();
    } catch {
      $("#endpoint-error").textContent = "Headers must be a JSON object";
      return;
    }
  }
  const payload = {
    name: form.name.value.trim(),
    url: form.url.value.trim(),
    method: form.method.value,
    interval_seconds: Number(form.interval_seconds.value) || 300,
    headers,
    body: form.body.value.trim() || null,
    is_active: form.is_active.checked,
  };
  try {
    if (state.editingId != null) {
      await api(`/api/endpoints/${state.editingId}`, { method: "PUT", body: JSON.stringify(payload) });
      toast("Endpoint updated");
    } else {
      await api("/api/endpoints", { method: "POST", body: JSON.stringify(payload) });
      toast("Endpoint added — first probe captures the baseline in a few seconds");
    }
    $("#dlg-endpoint").close();
    await loadAll();
  } catch (err) {
    $("#endpoint-error").textContent = err.message;
  }
});

/* ---------- channel dialog ---------- */

$("#btn-add-channel").addEventListener("click", () => {
  $("#form-channel").reset();
  $("#channel-error").textContent = "";
  $("#dlg-channel").showModal();
});

$("#form-channel").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    await api("/api/channels", {
      method: "POST",
      body: JSON.stringify({
        name: form.name.value.trim(),
        kind: form.kind.value,
        min_severity: form.min_severity.value,
        webhook_url: form.webhook_url.value.trim(),
      }),
    });
    $("#dlg-channel").close();
    toast("Channel added — hit Test to verify the webhook");
    await loadAll();
  } catch (err) {
    $("#channel-error").textContent = err.message;
  }
});

/* ---------- channel kind -> target field label ---------- */

$("#channel-kind").addEventListener("change", (e) => {
  const input = $("#form-channel").webhook_url;
  const label = $("#channel-target-label");
  if (e.target.value === "email") {
    label.firstChild.textContent = "Recipient email ";
    input.placeholder = "you@example.com";
  } else {
    label.firstChild.textContent = "Webhook URL ";
    input.placeholder = "https://discord.com/api/webhooks/…";
  }
});

/* ---------- API token dialog ---------- */

$("#btn-settings").addEventListener("click", () => {
  $("#form-token").token.value = localStorage.getItem("dw_token") || "";
  $("#dlg-token").showModal();
});

$("#form-token").addEventListener("submit", (e) => {
  e.preventDefault();
  const token = e.target.token.value.trim();
  if (token) {
    localStorage.setItem("dw_token", token);
    toast("Token saved");
  } else {
    localStorage.removeItem("dw_token");
    toast("Token cleared");
  }
  $("#dlg-token").close();
  loadAll();
});

document.querySelectorAll("dialog [data-close]").forEach((btn) =>
  btn.addEventListener("click", () => btn.closest("dialog").close()));

/* ---------- boot ---------- */

loadAll();
setInterval(() => {
  // Skip refresh while a modal is open so form input never gets clobbered.
  if (document.querySelector("dialog[open]")) return;
  loadAll();
}, 5000);
