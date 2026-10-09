"use strict";
/* AgriLens front-end. No build step. Sections: helpers · images · streaming · results · voice · tabs · boot */

const $ = id => document.getElementById(id);
const S = { lang: localStorage.lang || "ne", tab: +(localStorage.tab || 0), chatId: "", chatRef: "", plantRec: "", docId: "", health: {}, busy: false, stopAll: false };
const t = k => T[S.lang][k] ?? T.ne[k] ?? k;
const fl = k => T[S.lang].f[k] || k.replace(/_/g, " ");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const md = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/^\s*[-*•]\s+/gm, "• ").replace(/\n/g, "<br>");
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const form = o => { const fd = new FormData(); for (const [k, v] of Object.entries(o)) if (v != null) fd.append(k, v); return fd; };
const getJSON = async u => (await fetch(u)).json();
const when = ts => new Date(ts * 1000).toLocaleDateString(S.lang === "ne" ? "ne-NP" : undefined, { month: "short", day: "numeric" });
function toast(msg) { const x = $("toast"); x.textContent = msg; x.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => x.hidden = true, 5000); }

/* ---------- images: shrink on the phone BEFORE upload (4-8 MB photo -> ~300 KB) ---------- */
async function shrink(file, max = 1600, q = 0.85) {
  if (!file.type.startsWith("image/")) return file;
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const s = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas"); c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise(r => c.toBlob(r, "image/jpeg", q));
    return blob && blob.size < file.size ? new File([blob], "photo.jpg", { type: "image/jpeg" }) : file;
  } catch { return file; }
}
const PICK = {};   // slot -> Promise<File>, compressed in the background as soon as the photo is chosen
// function mountPickers() {
//   document.querySelectorAll("[data-pick]").forEach(box => {
//     const id = box.dataset.pick;
//     box.innerHTML = `<div class="two"><label class="big"><input type="file" accept="image/*" capture="environment" hidden>📷 <span data-t="camera"></span></label>` +
//       `<label class="big alt"><input type="file" accept="image/*" hidden>🖼️ <span data-t="gallery"></span></label></div><img class="prev" alt="">`;
//     box.querySelectorAll("input").forEach(inp => inp.onchange = () => {
//       const f = inp.files[0]; if (!f) return;
//       const p = box.querySelector(".prev"); p.src = URL.createObjectURL(f); p.style.display = "block";
//       PICK[id] = shrink(f, id === "plant" ? 1280 : 1600); inp.value = "";
//     });
//   });
// }
function mountPickers() {
  document.querySelectorAll("[data-pick]").forEach(box => {
    const id = box.dataset.pick;
    box.innerHTML = `<label class="big"><input type="file" accept="image/*" hidden>📷 <span data-t="pick"></span></label><img class="prev" alt="">`;
    box.querySelector("input").onchange = e => {
      const inp = e.target, f = inp.files[0]; if (!f) return;
      const p = box.querySelector(".prev"); p.src = URL.createObjectURL(f); p.style.display = "block";
      PICK[id] = shrink(f, id === "plant" ? 1280 : 1600); inp.value = "";
    };
  });
}

/* ---------- streaming (NDJSON) ---------- */
async function streamPost(url, fd, signal, onEvent) {
  const r = await fetch(url, { method: "POST", body: fd, signal });
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
  const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
  for (;;) {
    const { done, value } = await rd.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i; while ((i = buf.indexOf("\n")) >= 0) { const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1); if (line) onEvent(JSON.parse(line)); }
  }
}
/* run(): shows "⏳ 12 सेकेन्ड + Stop", streams text, hands the final result to the caller */
async function run(url, fd, out, h = {}) {
  fd.append("lang", S.lang);
  const ac = new AbortController(); let base = t("wait"), text = "", t0 = Date.now();
  out.innerHTML = `<div class="status"><span class="spin"></span><span class="st"></span><button class="stop">${esc(t("stop"))}</button></div><div class="res"></div>`;
  const st = out.querySelector(".st"), res = out.querySelector(".res"), bar = out.querySelector(".status");
  out.querySelector(".stop").onclick = () => ac.abort();
  const tick = () => st.textContent = `${base} ${Math.round((Date.now() - t0) / 1000)} ${t("sec")}`; tick();
  const iv = setInterval(tick, 500);
  try {
    await streamPost(url, fd, ac.signal, ev => {
      if (ev.t === "queued") base = t("queued");
      else if (ev.t === "progress") base = ev.msg || t("wait");
      else if (ev.t === "delta") { base = t("writing"); text += ev.v; res.innerHTML = md(text); h.onDelta?.(text); }
      else if (ev.t === "warn") { res.innerHTML = `<div class="warn">📸 ${renderData({ reasons: ev.reasons, suggestions: ev.suggestions })}</div>`; h.onWarn?.(ev, res); }
      else if (ev.t === "error") res.innerHTML = `<div class="err">${esc(ev.m)}</div>`;
      else if (ev.t === "result") h.onResult?.(ev, res);
      else h.onEvent?.(ev, res);
    });
  } catch (e) { if (e.name !== "AbortError") res.innerHTML = `<div class="err">${esc(e.message || e)}</div>`; }
  finally { clearInterval(iv); bar.remove(); }
  return { text, res };
}

/* ---------- rendering structured results ---------- */
const NR = [/पढ्न सकिएन/, /Not readable/i, /not provided in the available/i];
const isNR = v => typeof v === "string" && (v.trim() === "" || NR.some(r => r.test(v)));
const KEY = new Set(["dosage", "mixing_ratio", "pre_harvest_interval", "ppe", "warnings", "expiry_date"]);
const HZ = { red: "#d32f2f", yellow: "#f9a825", blue: "#1976d2", green: "#2e7d32" };
function val(k, v) {
  if (v == null || isNR(v)) return `<span class="nr">⚠ ${esc(t("nr"))}</span>`;
  if (typeof v !== "string") return esc(v);
  const m = T[S.lang].v[v];
  const dot = k === "hazard_color" && HZ[v] ? `<i class="hz" style="background:${HZ[v]}"></i>` : "";
  return dot + esc(m || v);
}
function renderData(v, ev = {}, k = null) {
  if (v == null || typeof v !== "object") return val(k, v);
  if (Array.isArray(v)) return v.length ? "<ul>" + v.map(x => `<li>${renderData(x, {}, k)}</li>`).join("") + "</ul>" : `<span class="nr">—</span>`;
  if (v.raw) return `<div class="row">${md(v.raw)}</div>`;
  const keys = Object.keys(v).filter(x => !["evidence", "unreadable_fields", "category"].includes(x) || (x === "category" && typeof v[x] === "string" && !v.summary));
  keys.sort((a, b) => ["farmer_summary"].includes(b) - ["farmer_summary"].includes(a));
  let html = keys.map(x => {
    const b = ev[x] ? `<span class="badge ${esc(ev[x])}">${esc(T[S.lang].ev[ev[x]] || ev[x])}</span>` : "";
    return `<div class="row${KEY.has(x) ? " key" : ""}"><b>${esc(fl(x))}${b}</b>${renderData(v[x], {}, x)}</div>`;
  }).join("");
  const un = (v.unreadable_fields || []).filter(Boolean);
  if (un.length) html += `<div class="row"><b>⚠ ${esc(t("unreadable"))}</b>${esc(un.map(fl).join(", "))}</div>`;
  return html;
}
function speechOf(v) {   // what to read aloud: skip evidence/unreadable/empty
  if (v == null || isNR(v)) return "";
  if (typeof v === "string") return T[S.lang].v[v] || v;
  if (Array.isArray(v)) return v.map(speechOf).filter(Boolean).join("। ");
  if (v.raw) return v.raw;
  return Object.entries(v).filter(([k]) => !["evidence", "unreadable_fields"].includes(k))
    .map(([k, x]) => { const s = speechOf(x); return s ? `${fl(k)}: ${s}` : ""; }).filter(Boolean).join("। ");
}
function actionBtn(label, fn) { const b = el("button", "act", esc(label)); b.onclick = () => fn(b); return b; }
function showResult(kind, ev, out) {
  const imgs = (ev.images || []).map(u => `<img src="${esc(u)}" alt="">`).join("");
  out.innerHTML = (imgs ? `<div class="thumbs">${imgs}</div>` : "") + renderData(ev.v, ev.v.evidence || {});
  const bar = el("div", "actions");
  bar.append(actionBtn("🔊 " + t("listen"), b => speak(speechOf(ev.v), b)));
  if (kind !== "news") bar.append(actionBtn(t("askAbout"), () => startChatAbout(ev.record_id, kind)));
  if (kind === "label" && S.plantRec) bar.append(actionBtn(t("matchBtn"), () => runMatch(ev.record_id, out)));
  out.append(bar);
}
async function runMatch(labelId, out) {
  const box = el("div", "out"); out.append(box);
  await run("/api/match", form({ plant_id: S.plantRec, label_id: labelId }), box, { onResult: (ev, r) => showResult("match", ev, r) });
}

/* ---------- history lists (plant / label records) ---------- */
async function loadHist(kind) {
  const box = $(kind + "Hist"), rows = await getJSON("/api/records?kind=" + kind);
  box.innerHTML = rows.length ? "" : `<p class="hint">${esc(t("empty"))}</p>`;
  for (const r of rows) {
    const it = el("div", "hist", `<img src="/img/${esc(r.images[0] || "")}" alt=""><span>${esc(r.title)}<small>${esc(when(r.created))}</small></span>`);
    it.onclick = async () => { const d = await getJSON("/api/records/" + r.id); showResult(kind, { v: d.data, images: d.images.map(n => "/img/" + n), record_id: d.id }, $(kind + "Out")); if (kind === "plant") S.plantRec = d.id; $(kind + "Out").scrollIntoView({ behavior: "smooth" }); };
    const x = el("button", "x", "✕"); x.onclick = async e => { e.stopPropagation(); if (confirm(t("del"))) { await fetch("/api/records/" + r.id, { method: "DELETE" }); loadHist(kind); } };
    it.append(x); box.append(it);
  }
}

/* ---------- voice: output (Piper offline -> browser Nepali -> Hindi fallback) and input (mic) ---------- */
let VOICES = []; const loadVoices = () => VOICES = window.speechSynthesis ? speechSynthesis.getVoices() : [];
if (window.speechSynthesis) { speechSynthesis.onvoiceschanged = loadVoices; loadVoices(); }
const voiceFor = p => VOICES.find(v => v.lang.toLowerCase().startsWith(p));
const speakable = s => String(s).replace(/[*_#`>•]/g, " ").replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, "")
  .replace(/(\d)\s*ml\s*\/\s*L/gi, "$1 मिलिलिटर प्रति लिटर").replace(/(\d)\s*g\s*\/\s*L/gi, "$1 ग्राम प्रति लिटर").replace(/(\d)\s*kg\s*\/\s*ha/gi, "$1 किलो प्रति हेक्टर")
  .replace(/(\d)\s*ml\b/gi, "$1 मिलिलिटर").replace(/(\d)\s*%/g, "$1 प्रतिशत").replace(/\s+/g, " ").trim();
function sentences(text, max = 300) {
  const out = []; let cur = "";
  for (const p of text.split(/(?<=[।.!?])\s+/)) { if (cur && (cur + " " + p).length > max) { out.push(cur); cur = p; } else cur = (cur + " " + p).trim(); }
  if (cur) out.push(cur); return out;
}
let playing = null;
async function speak(raw, btn) {
  if (playing) { const same = playing.btn === btn; playing.stop(); if (same) return; }
  const parts = sentences(S.lang === "ne" ? speakable(raw) : String(raw)); if (!parts.length) return;
  let stopped = false, audio = null, spoken = false;
  const mark = on => { if (btn) btn.textContent = (on ? "⏹ " : "🔊 ") + t("listen"); };
  const me = playing = { btn, stop() { stopped = true; try { speechSynthesis.cancel(); } catch {} audio?.pause(); mark(false); if (playing === me) playing = null; } };
  mark(true);
  if (S.health.tts && S.lang === "ne") {   // offline neural voice from the server
    try {
      for (const p of parts) {
        if (stopped) return;
        const r = await fetch("/api/tts", { method: "POST", body: form({ text: p }) }); if (!r.ok) throw new Error("tts");
        audio = new Audio(URL.createObjectURL(await r.blob())); audio.playbackRate = +$("rate").value;
        await new Promise((res, rej) => { audio.onended = res; audio.onerror = rej; audio.play().catch(rej); }); spoken = true;
      }
      return me.stop();
    } catch { if (stopped || spoken) return me.stop(); }
  }
  if (!window.speechSynthesis) { toast(t("noNe")); return me.stop(); }
  let v = S.lang === "ne" ? voiceFor("ne") : voiceFor("en");
  if (S.lang === "ne" && !v) { v = voiceFor("hi"); toast(v ? t("noNeHi") : t("noNe")); if (!v) return me.stop(); }
  let i = 0;
  const next = () => {
    if (stopped) return; if (i >= parts.length) return me.stop();
    const u = new SpeechSynthesisUtterance(parts[i++]); if (v) u.voice = v; u.lang = v ? v.lang : "ne-NP"; u.rate = +$("rate").value; u.onend = next; u.onerror = next; speechSynthesis.speak(u);
  };
  next();
}
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
function attachMic(btn, input) {   // needs internet in Chrome and https/localhost; hidden otherwise
  if (!SR || !window.isSecureContext) { btn.hidden = true; return; }
  let rec = null;
  btn.onclick = () => {
    if (rec) return rec.stop();
    rec = new SR(); rec.lang = S.lang === "ne" ? "ne-NP" : "en-US"; rec.interimResults = true;
    rec.onresult = e => input.value = [...e.results].map(r => r[0].transcript).join(" ");
    rec.onend = () => { rec = null; btn.classList.remove("rec"); }; rec.onerror = () => {};
    rec.start(); btn.classList.add("rec");
  };
}

/* ---------- chat bubbles (shared by Chat and Docs) ---------- */
function bubble(log, role, text = "", image = "") {
  const b = el("div", "m " + (role === "user" ? "u" : "a"), (image ? `<img src="/img/${esc(image)}" alt="">` : "") + `<div class="res">${md(text)}</div>`);
  log.append(b); log.scrollTop = log.scrollHeight; return b;
}
function bubbleTools(b, text, sources) {
  const bar = el("div", "actions small");
  bar.append(actionBtn("🔊", btn => speak(text(), btn)), actionBtn("📋", () => navigator.clipboard?.writeText(text()).then(() => toast("✓"))));
  b.append(bar);
  if (sources?.length) b.append(el("details", "src", `<summary>${esc(t("sources"))} (${sources.length})</summary>` + sources.map(s => `<p><b>${esc(t("page"))} ${s.page}:</b> ${esc(s.snippet)}…</p>`).join("")));
}
function fillLog(log, msgs) {
  log.innerHTML = "";
  for (const m of msgs) { const b = bubble(log, m.role, m.content, m.image || ""); if (m.role === "assistant") bubbleTools(b, () => b.querySelector(".res").innerText, m.meta?.sources); }
}

/* ---------- tab: plant ---------- */
async function sendPlant(force = false) {
  const f = await PICK.plant; if (!f) return alert(t("need"));
  const fd = form({ image: f, note: $("plantNote").value, force: force ? "true" : null });
  await run("/api/plant", fd, $("plantOut"), {
    onWarn: (ev, r) => r.append(actionBtn(t("retry"), () => sendPlant(true))),
    onResult: (ev, r) => { S.plantRec = ev.record_id; showResult("plant", ev, r); loadHist("plant"); },
  });
}
/* ---------- tab: label ---------- */
async function sendLabel(force = false) {
  const f = await PICK.front; if (!f) return alert(t("need"));
  const b = await PICK.back;
  const fd = form({ front: f, back: b || null, kind: $("kind").value, force: force ? "true" : null });
  await run("/api/label", fd, $("labelOut"), {
    onWarn: (ev, r) => r.append(actionBtn(t("retry"), () => sendLabel(true))),
    onResult: (ev, r) => { showResult("label", ev, r); loadHist("label"); },
  });
}

/* ---------- tab: documents ---------- */
async function loadDocs() {
  const box = $("docList"), rows = await getJSON("/api/docs");
  box.innerHTML = "";
  for (const d of rows) {
    const it = el("div", "hist" + (d.id === S.docId ? " sel" : ""), `<span>📄 ${esc(d.name)}<small>${d.pages} ${esc(t("pages"))} · ${esc(when(d.created))}</small></span>`);
    it.onclick = () => selectDoc(d); const x = el("button", "x", "✕");
    x.onclick = async e => { e.stopPropagation(); if (confirm(t("del"))) { await fetch("/api/docs/" + d.id, { method: "DELETE" }); if (S.docId === d.id) { S.docId = ""; $("docBox").hidden = true; } loadDocs(); } };
    it.append(x); box.append(it);
  }
}
async function selectDoc(d) {
  S.docId = d.id; $("docBox").hidden = false; $("docName").textContent = "📄 " + d.name;
  $("docSum").innerHTML = d.summary ? `<div class="row">${md(d.summary)}</div>` : "";
  fillLog($("docLog"), await getJSON(`/api/docs/${d.id}/thread`)); loadDocs();
}
async function uploadDoc(file) {
  if (!file) return;
  const f = await shrink(file, 1600);
  await run("/api/docs", form({ file: f, ocr: $("ocr").checked ? "true" : null }), $("docStat"), {
    onResult: async ev => { $("docStat").innerHTML = `<p class="hint">✅ ${esc(ev.v.name)}</p>`; await loadDocs(); selectDoc(ev.v); },
  });
}
async function askDoc() {
  const q = $("docQ").value.trim(); if (!q || !S.docId || S.busy) return;
  $("docQ").value = ""; S.busy = true; const log = $("docLog"); bubble(log, "user", q); const b = bubble(log, "assistant"); let src = [];
  const { text } = await run(`/api/docs/${S.docId}/ask`, form({ question: q }), b, { onEvent: ev => { if (ev.t === "sources") src = ev.v; }, onDelta: () => log.scrollTop = log.scrollHeight });
  if (text) bubbleTools(b, () => text, src); S.busy = false;
}
async function summarizeDoc() {
  if (!S.docId) return;
  await run(`/api/docs/${S.docId}/summary`, form({}), $("docSum")); loadDocs();
}

/* ---------- tab: news ---------- */
function renderNews(sumEl, s) {
  sumEl.innerHTML = `<span class="chip">${esc(T[S.lang].cat[s.category] || s.category || "")}</span><div class="row">${md(s.summary)}</div>` +
    (s.key_points?.length ? `<b>${esc(fl("key_points"))}</b>${renderData(s.key_points)}` : "") + (s.farmer_relevance ? `<p class="hint">${esc(s.farmer_relevance)}</p>` : "");
  const bar = el("div", "actions small"); bar.append(actionBtn("🔊 " + t("listen"), b => speak(`${s.summary}। ${(s.key_points || []).join("। ")}`, b))); sumEl.append(bar);
}
async function loadNews() {
  const rows = await getJSON("/api/news?lang=" + S.lang), box = $("newsList");
  box.innerHTML = rows.length ? "" : `<p class="hint">${esc(t("noNews"))}</p>`;
  for (const a of rows) {
    const c = el("div", "news", `<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer" class="nt">${esc(a.title)}</a><small>${esc(a.source)} ${esc(a.published.slice(0, 16))}</small><div class="sum"></div>`);
    c.dataset.id = a.id; const sum = c.querySelector(".sum");
    if (a.summary) renderNews(sum, a.summary); else c.append(actionBtn("📝 " + t("newsSum"), () => summarizeNews(c)));
    box.append(c);
  }
}
async function summarizeNews(card) {
  const sum = card.querySelector(".sum"); card.querySelector(":scope > .act")?.remove();
  await run(`/api/news/${card.dataset.id}/summary`, form({}), sum, { onResult: (ev, r) => renderNews(r, ev.v) });
}
async function refreshNews() {
  await run("/api/news/refresh", form({}), $("newsStat"), { onResult: (ev, r) => { r.innerHTML = `<p class="hint">✅ ${ev.v.new} ${esc(t("newCount"))}</p>`; } });
  loadNews();
}
async function summarizeAll() {
  S.stopAll = false;
  for (const c of document.querySelectorAll("#newsList .news")) {
    if (S.stopAll) break; if (c.querySelector(".sum").children.length) continue;
    await summarizeNews(c);
  }
}

/* ---------- tab: chat ---------- */
async function loadChatList() {
  const rows = await getJSON("/api/chats"), box = $("chatHist"); box.innerHTML = rows.length ? "" : `<p class="hint">${esc(t("empty"))}</p>`;
  for (const c of rows) {
    const it = el("div", "hist" + (c.id === S.chatId ? " sel" : ""), `<span>💬 ${esc(c.title)}<small>${esc(when(c.updated))}</small></span>`);
    it.onclick = async () => { const d = await getJSON("/api/chats/" + c.id); S.chatId = c.id; setCtx(""); fillLog($("log"), d.messages); $("chatHist").hidden = true; };
    const x = el("button", "x", "✕"); x.onclick = async e => { e.stopPropagation(); if (confirm(t("del"))) { await fetch("/api/chats/" + c.id, { method: "DELETE" }); if (S.chatId === c.id) newChat(); loadChatList(); } };
    it.append(x); box.append(it);
  }
}
function setCtx(label) { const c = $("chatCtx"); c.hidden = !label; c.textContent = label ? t("ctxChip") + label : ""; if (!label) S.chatRef = ""; }
function newChat() { S.chatId = ""; setCtx(""); $("log").innerHTML = ""; PICK.chat = null; $("chatImgChip").hidden = true; }
function startChatAbout(recordId, kind) { newChat(); S.chatRef = recordId; setCtx(kind); show(4); $("chatQ").focus(); }
async function sendChat() {
  const q = $("chatQ").value.trim(), img = PICK.chat ? await PICK.chat : null;
  if ((!q && !img) || S.busy) return; S.busy = true;
  const log = $("log"); bubble(log, "user", q || t("chatDef"), ""); if (img) log.lastChild.prepend(Object.assign(new Image(), { src: URL.createObjectURL(img) }));
  $("chatQ").value = ""; PICK.chat = null; $("chatImgChip").hidden = true;
  const b = bubble(log, "assistant");
  const { text } = await run("/api/chat", form({ message: q, chat_id: S.chatId, record_id: S.chatRef, image: img }), b, {
    onEvent: ev => { if (ev.t === "meta") S.chatId = ev.chat_id; }, onDelta: () => log.scrollTop = log.scrollHeight });
  if (text) bubbleTools(b, () => text); setCtx(""); S.busy = false; loadChatList();
}

/* ---------- shell: tabs, language, theme, font size, health ---------- */
const SECS = ["plant", "label", "doc", "news", "chat"];
function show(i) {
  S.tab = i; localStorage.tab = i;
  SECS.forEach((s, j) => { $(s).classList.toggle("on", i === j); $("t" + j).classList.toggle("on", i === j); });
  if (i === 2) loadDocs(); if (i === 3) loadNews(); if (i === 4) loadChatList();
}
function apply() {
  document.documentElement.lang = S.lang;
  document.querySelectorAll("[data-t]").forEach(e => e.textContent = t(e.dataset.t));
  document.querySelectorAll("[data-p]").forEach(e => e.placeholder = t(e.dataset.p));
  $("tabs").innerHTML = ""; T[S.lang].tabs.forEach((x, i) => { const b = el("button", "", esc(x)); b.id = "t" + i; b.onclick = () => show(i); $("tabs").append(b); });
  $("ne").classList.toggle("on", S.lang === "ne"); $("en").classList.toggle("on", S.lang === "en"); show(S.tab); pollHealth();
}
async function pollHealth() {
  try { S.health = await getJSON("/api/health"); } catch { S.health = {}; }
  const h = S.health; const m = !h.ollama ? t("ollamaDown") : !h.installed ? t("noModel").replaceAll("{m}", h.model) : !h.loaded ? t("warming") : "";
  $("banner").hidden = !m; $("banner").textContent = m;
}
function setFs(d) { const px = Math.min(26, Math.max(15, (+localStorage.fs || 18) + d)); localStorage.fs = px; document.documentElement.style.setProperty("--fs", px + "px"); }

$("ne").onclick = () => { S.lang = "ne"; localStorage.lang = "ne"; apply(); }; $("en").onclick = () => { S.lang = "en"; localStorage.lang = "en"; apply(); };
$("theme").onclick = () => { const d = document.body.dataset.theme === "dark"; document.body.dataset.theme = d ? "" : "dark"; localStorage.theme = d ? "" : "dark"; };
$("fsUp").onclick = () => setFs(2); $("fsDown").onclick = () => setFs(-2);
$("plantGo").onclick = () => sendPlant(); $("labelGo").onclick = () => sendLabel();
$("docFile").onchange = e => { uploadDoc(e.target.files[0]); e.target.value = ""; };
$("docGo").onclick = askDoc; $("docSumBtn").onclick = summarizeDoc; $("docQ").onkeydown = e => e.key === "Enter" && askDoc();
$("newsRefresh").onclick = refreshNews; $("newsAll").onclick = summarizeAll;
$("chatGo").onclick = sendChat; $("chatQ").onkeydown = e => e.key === "Enter" && sendChat(); $("chatNew").onclick = newChat;
$("chatHistBtn").onclick = () => { $("chatHist").hidden = !$("chatHist").hidden; if (!$("chatHist").hidden) loadChatList(); };
$("chatImg").onchange = e => { const f = e.target.files[0]; if (!f) return; PICK.chat = shrink(f, 1280); const c = $("chatImgChip"); c.hidden = false; c.textContent = "📷 " + f.name + "  ✕"; c.onclick = () => { PICK.chat = null; c.hidden = true; }; e.target.value = ""; };
attachMic($("chatMic"), $("chatQ")); attachMic($("docMic"), $("docQ"));

document.body.dataset.theme = localStorage.theme || ""; setFs(0);
mountPickers(); apply(); loadHist("plant"); loadHist("label"); setInterval(pollHealth, 15000);
