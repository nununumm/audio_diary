"use strict";

// --------------------------------------------------------------------------- //
// Small helpers
// --------------------------------------------------------------------------- //
const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(path, { credentials: "same-origin", ...options });
  if (res.status === 401) {
    showLogin();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let detail = "エラーが発生しました";
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 2200);
}

function todayISO() {
  const d = new Date();
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d - tz).toISOString().slice(0, 10);
}

// --------------------------------------------------------------------------- //
// View switching
// --------------------------------------------------------------------------- //
function showLogin() {
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}
function showApp() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  loadEntries();
}

// --------------------------------------------------------------------------- //
// Auth
// --------------------------------------------------------------------------- //
async function checkAuth() {
  try {
    await api("/api/me");
    showApp();
  } catch (_) {
    showLogin();
  }
}

$("#login-btn").addEventListener("click", doLogin);
$("#login-password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doLogin();
});

async function doLogin() {
  const password = $("#login-password").value;
  const errEl = $("#login-error");
  errEl.classList.add("hidden");
  try {
    await api("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    $("#login-password").value = "";
    showApp();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  }
}

$("#logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  showLogin();
});

// --------------------------------------------------------------------------- //
// Entry list
// --------------------------------------------------------------------------- //
let searchTimer = null;
$("#search-input").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadEntries, 250);
});

async function loadEntries() {
  const q = $("#search-input").value.trim();
  const url = q ? `/api/entries?q=${encodeURIComponent(q)}` : "/api/entries";
  try {
    const { entries } = await api(url);
    renderEntries(entries);
  } catch (e) {
    if (e.message !== "unauthorized") toast(e.message);
  }
}

function renderEntries(entries) {
  const list = $("#entry-list");
  list.innerHTML = "";
  if (!entries.length) {
    list.innerHTML = `<p class="empty">まだ日記がありません。<br>下のボタンで録音してみましょう。</p>`;
    return;
  }
  for (const e of entries) {
    const card = document.createElement("article");
    card.className = "entry-card";
    const body = e.clean_text || e.raw_text || "(本文なし)";
    const thumbs = e.photos
      .map((p) => `<img src="${p.thumb_url}" alt="" loading="lazy">`)
      .join("");
    card.innerHTML = `
      <div class="date">${e.entry_date}</div>
      <p class="preview">${escapeHtml(body)}</p>
      ${thumbs ? `<div class="thumbs">${thumbs}</div>` : ""}`;
    card.addEventListener("click", () => openDetail(e.id));
    list.appendChild(card);
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// --------------------------------------------------------------------------- //
// Recording
// --------------------------------------------------------------------------- //
let mediaRecorder = null;
let chunks = [];

function pickMime() {
  const prefs = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"];
  for (const m of prefs) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

$("#record-btn").addEventListener("click", toggleRecording);

async function toggleRecording() {
  const btn = $("#record-btn");
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = pickMime();
    mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunks = [];
    mediaRecorder.ondataavailable = (ev) => ev.data.size && chunks.push(ev.data);
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      btn.classList.remove("recording");
      const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
      await uploadRecording(blob);
    };
    mediaRecorder.start();
    btn.classList.add("recording");
    $("#record-status").textContent = "録音中… タップで停止";
  } catch (e) {
    toast("マイクを使用できません: " + e.message);
  }
}

async function uploadRecording(blob) {
  $("#record-status").textContent = "文字起こし中…";
  const fd = new FormData();
  const ext = (blob.type.split("/")[1] || "webm").split(";")[0];
  fd.append("audio", blob, `recording.${ext}`);
  fd.append("entry_date", todayISO());
  try {
    const entry = await api("/api/entries/transcribe", { method: "POST", body: fd });
    $("#record-status").textContent = "";
    await loadEntries();
    openDetail(entry.id);
  } catch (e) {
    $("#record-status").textContent = "";
    toast(e.message);
  }
}

// --------------------------------------------------------------------------- //
// Detail modal
// --------------------------------------------------------------------------- //
let currentEntry = null;

async function openDetail(id) {
  try {
    currentEntry = await api(`/api/entries/${id}`);
  } catch (e) {
    return toast(e.message);
  }
  $("#detail-date").value = currentEntry.entry_date;
  $("#detail-clean").value = currentEntry.clean_text;
  $("#detail-raw").value = currentEntry.raw_text;
  renderDetailPhotos();
  $("#detail-modal").classList.remove("hidden");
}

function renderDetailPhotos() {
  const grid = $("#detail-photos");
  grid.innerHTML = "";
  for (const p of currentEntry.photos) {
    const cell = document.createElement("div");
    cell.className = "cell";
    cell.innerHTML = `<img src="${p.thumb_url}" alt="">
      <button class="del" title="削除">✕</button>`;
    cell.querySelector(".del").addEventListener("click", () => deletePhoto(p.id));
    grid.appendChild(cell);
  }
}

$("#detail-close").addEventListener("click", () => {
  $("#detail-modal").classList.add("hidden");
  currentEntry = null;
});

$("#detail-save").addEventListener("click", async () => {
  if (!currentEntry) return;
  try {
    await api(`/api/entries/${currentEntry.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entry_date: $("#detail-date").value,
        clean_text: $("#detail-clean").value,
        raw_text: $("#detail-raw").value,
      }),
    });
    toast("保存しました");
    $("#detail-modal").classList.add("hidden");
    loadEntries();
  } catch (e) {
    toast(e.message);
  }
});

$("#detail-delete").addEventListener("click", async () => {
  if (!currentEntry || !confirm("この日記を削除しますか？")) return;
  try {
    await api(`/api/entries/${currentEntry.id}`, { method: "DELETE" });
    $("#detail-modal").classList.add("hidden");
    loadEntries();
  } catch (e) {
    toast(e.message);
  }
});

$("#photo-input").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  ev.target.value = "";
  if (!file || !currentEntry) return;
  const fd = new FormData();
  fd.append("photo", file);
  try {
    const photo = await api(`/api/entries/${currentEntry.id}/photos`, {
      method: "POST",
      body: fd,
    });
    currentEntry.photos.push(photo);
    renderDetailPhotos();
    loadEntries();
  } catch (e) {
    toast(e.message);
  }
});

async function deletePhoto(photoId) {
  try {
    await api(`/api/photos/${photoId}`, { method: "DELETE" });
    currentEntry.photos = currentEntry.photos.filter((p) => p.id !== photoId);
    renderDetailPhotos();
    loadEntries();
  } catch (e) {
    toast(e.message);
  }
}

// --------------------------------------------------------------------------- //
// Boot
// --------------------------------------------------------------------------- //
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
checkAuth();
