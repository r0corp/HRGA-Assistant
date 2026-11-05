// Halaman HRGA Report untuk HP. Semua teks dari server dipasang lewat textContent (tanpa innerHTML).
"use strict";

const $ = (id) => document.getElementById(id);
let me = null;
let saveTimer = null;

function today() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

async function api(method, path, data) {
  const opt = { method, headers: { "X-HRGA": "1" }, credentials: "same-origin" };
  if (data !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(data);
  }
  const r = await fetch(path, opt);
  let body = {};
  try { body = await r.json(); } catch (e) { /* respons kosong */ }
  if (r.status === 401 && path !== "/api/login") {
    showLogin();
  }
  if (!r.ok) throw new Error(body.error || ("Server menjawab " + r.status));
  return body;
}

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.add("hidden"), 3200);
}

async function busy(text, work) {
  $("busy-text").textContent = text;
  $("busy").classList.remove("hidden");
  try { return await work(); }
  catch (e) { toast(e.message); }
  finally { $("busy").classList.add("hidden"); }
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("id-ID", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// ---------- tampilan ----------

function show(view) {
  for (const v of ["login", "today", "history", "team"]) $("view-" + v).classList.toggle("hidden", v !== view);
  for (const b of document.querySelectorAll(".tabs button")) b.classList.toggle("active", b.dataset.tab === view);
  window.scrollTo(0, 0);
}

function showLogin() {
  me = null;
  $("who").classList.add("hidden");
  $("tabs").classList.add("hidden");
  show("login");
}

function showApp() {
  $("who-name").textContent = me.name;
  $("who").classList.remove("hidden");
  $("tabs").classList.remove("hidden");
  for (const el of document.querySelectorAll(".admin-only")) el.classList.toggle("hidden", !["admin", "supervisor"].includes(me.role));
  $("day").max = today();
  $("day").value = today();
  $("team-day").value = today();
  show("today");
  loadReport();
}

function setSent(sentAt) {
  const p = $("sent-pill");
  p.textContent = sentAt ? "Terkirim " + fmtTime(sentAt) : "Belum dikirim";
  p.classList.toggle("ok", !!sentAt);
  $("send-btn").textContent = sentAt ? "Kirim ulang ke Fena" : "Kirim ke Fena";
}

// ---------- report ----------

async function loadReport() {
  try {
    const r = await api("GET", "/api/report?date=" + $("day").value);
    $("story").value = r.story || "";
    $("report").value = r.text || "";
    $("saved").textContent = "";
    $("revise-reply").textContent = "";
    setSent(r.sent_at);
  } catch (e) { toast(e.message); }
}

function scheduleSave() {
  $("saved").textContent = "...";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      await api("PUT", "/api/report", { date: $("day").value, text: $("report").value, story: $("story").value });
      $("saved").textContent = "Tersimpan";
    } catch (e) { $("saved").textContent = ""; toast(e.message); }
  }, 900);
}

async function tidy() {
  const story = $("story").value.trim();
  if (!story) { toast("Ceritakan dulu pekerjaan hari ini"); return; }
  await busy("Claude sedang merapikan report... (20-60 detik)", async () => {
    const r = await api("POST", "/api/tidy", { date: $("day").value, story });
    $("report").value = r.text;
    $("saved").textContent = "Tersimpan";
    toast("Draf siap. Cek dulu, lalu Kirim ke Fena.");
  });
}

async function revise() {
  const instruction = $("revise").value.trim();
  if (!instruction) return;
  await busy("Claude sedang mengubah report...", async () => {
    const r = await api("POST", "/api/revise", {
      date: $("day").value, text: $("report").value, story: $("story").value, instruction,
    });
    $("report").value = r.text;
    $("revise-reply").textContent = r.reply || "";
    if (r.changed) { $("revise").value = ""; toast("Draf sudah diubah"); }
  });
}

async function send() {
  const text = $("report").value.trim();
  if (!text) { toast("Report masih kosong"); return; }
  if (!confirm("Kirim report tanggal " + $("day").value + " ke Fena?")) return;
  await busy("Mengirim...", async () => {
    const r = await api("POST", "/api/report/submit", { date: $("day").value, text, story: $("story").value });
    setSent(r.sent_at);
    toast("Report terkirim ke Fena ✓");
  });
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Disalin"); }
  catch (e) { toast("Tidak bisa menyalin di browser ini"); }
}

// ---------- riwayat & rekap ----------

function itemRow(ok, name, sub, body, onClick) {
  const item = document.createElement("div");
  item.className = "item";
  const head = document.createElement("div");
  head.className = "item-head";
  const dot = document.createElement("span");
  dot.className = "dot " + (ok ? "ok" : "no");
  dot.textContent = ok ? "✓" : "✕";
  const info = document.createElement("div");
  const n = document.createElement("div");
  n.className = "item-name";
  n.textContent = name;
  const s = document.createElement("div");
  s.className = "item-sub";
  s.textContent = sub;
  info.append(n, s);
  head.append(dot, info);
  item.append(head);
  if (body) {
    const b = document.createElement("div");
    b.className = "item-body hidden";
    b.textContent = body;
    item.append(b);
    head.addEventListener("click", () => b.classList.toggle("hidden"));
  }
  if (onClick) head.addEventListener("click", onClick);
  return item;
}

async function loadHistory() {
  const list = $("history-list");
  list.replaceChildren();
  try {
    const r = await api("GET", "/api/history");
    for (const it of r.items) {
      const d = new Date(it.date + "T00:00:00");
      const label = d.toLocaleDateString("id-ID", { weekday: "long", day: "2-digit", month: "long" });
      list.append(itemRow(!!it.sent_at, label, it.sent_at ? "Terkirim " + fmtTime(it.sent_at) : "Belum dikirim",
        null, () => { $("day").value = it.date; show("today"); loadReport(); }));
    }
  } catch (e) { toast(e.message); }
}

let teamText = "";
async function loadTeam() {
  const list = $("team-list");
  list.replaceChildren();
  try {
    const r = await api("GET", "/api/team?date=" + $("team-day").value);
    teamText = r.text;
    const done = r.rows.filter((x) => x.sent_at).length;
    $("team-count").textContent = done + "/" + r.rows.length + " sudah report";
    $("team-count").classList.toggle("ok", done === r.rows.length);
    for (const x of r.rows) {
      const sub = x.title + " · " + (x.sent_at ? "Terkirim " + fmtTime(x.sent_at) : "Belum report");
      list.append(itemRow(!!x.sent_at, x.name, sub, x.sent_at ? x.text : null));
    }
  } catch (e) { toast(e.message); }
}

// ---------- mulai ----------

document.addEventListener("DOMContentLoaded", async () => {
  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    $("login-error").textContent = "";
    $("login-btn").disabled = true;
    try {
      const r = await api("POST", "/api/login", { name: $("login-name").value, pin: $("login-pin").value });
      me = r.user;
      $("login-pin").value = "";
      showApp();
    } catch (e) { $("login-error").textContent = e.message; }
    finally { $("login-btn").disabled = false; }
  });
  $("logout").addEventListener("click", async () => {
    try { await api("POST", "/api/logout", {}); } catch (e) { /* tetap keluar */ }
    showLogin();
  });
  for (const b of document.querySelectorAll(".tabs button")) {
    b.addEventListener("click", () => {
      show(b.dataset.tab);
      if (b.dataset.tab === "history") loadHistory();
      if (b.dataset.tab === "team") loadTeam();
      if (b.dataset.tab === "today") loadReport();
    });
  }
  $("day").addEventListener("change", loadReport);
  $("team-day").addEventListener("change", loadTeam);
  $("report").addEventListener("input", scheduleSave);
  $("story").addEventListener("input", scheduleSave);
  $("tidy-btn").addEventListener("click", tidy);
  $("revise-btn").addEventListener("click", revise);
  $("revise").addEventListener("keydown", (e) => { if (e.key === "Enter") revise(); });
  $("send-btn").addEventListener("click", send);
  $("copy-btn").addEventListener("click", () => copy($("report").value));
  $("team-copy").addEventListener("click", () => copy(teamText));

  try {
    me = (await api("GET", "/api/me")).user;
    showApp();
  } catch (e) { showLogin(); }
});
