"use strict";
// צפון LIVE – ממשק המשתמש. כל טקסט מהשרת מוכנס כ-textContent בלבד (ללא innerHTML).

const TYPES = {
  security: ["ביטחון", "🛡️"], accident: ["תאונה", "🚗"], fire: ["שריפה", "🔥"], closure: ["חסימה", "🚧"],
  infrastructure: ["תשתיות", "⚡"], weather: ["מזג אוויר", "🌧️"], hazard: ["מפגע", "⚠️"], other: ["אחר", "📌"],
};
const STATUS = { new: "חדש", ongoing: "מתמשך", ended: "הסתיים", unknown: "מצב לא ידוע" };
const VERIF = {
  single_source: "דיווח ראשוני · מקור אחד", multi_source: "כמה מקורות עצמאיים",
  official: "אומת ע״י גורם רשמי", retracted: "הוכחש / תוקן",
};
const SRC_STATUS = { configured: "הוגדר – טרם נבדק", verified: "החיבור נבדק", ingesting: "קולט מידע אמיתי", error: "שגיאה" };
const KIND = { telegram: "טלגרם", rss: "RSS", api: "API", website: "אתר", other: "אחר" };
const LOC_KIND = { locality: "יישובים", region: "אזורים", road: "כבישים", junction: "צמתים" };

// מצב סטטי: האתר מוגש מ-GitHub Pages וקורא קובצי JSON שנבנו בהרצת האיסוף, בלי שרת.
const STATIC = document.documentElement.dataset.static === "1";
const $ = (s) => document.querySelector(s);
function el(tag, props = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) n.append(c);
  return n;
}
const store = {
  get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* אחסון לא זמין */ } },
};

const state = {
  filters: store.get("tl_filters", { type: "", location_id: "", radius_km: "", hours: "", verification: "" }),
  gps: null, // נשמר בזיכרון בלבד, לא נשלח לשמירה ולא נכתב למכשיר
  locations: [], events: [], map: null, layer: null, editing: null, seg: null,
};

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = sessionStorage.getItem("tl_admin");
  if (opts.admin && token) headers.Authorization = "Bearer " + token;
  const r = await fetch(path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || "שגיאת שרת"), { status: r.status });
  return data;
}

const getData = (name) => (STATIC ? api(`data/${name}.json?t=${Date.now()}`) : api("api/" + name));

function km(lat1, lon1, lat2, lon2) {
  const r = Math.PI / 180, a = Math.sin(((lat2 - lat1) * r) / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin(((lon2 - lon1) * r) / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(a));
}

// סינון בצד הלקוח למצב הסטטי – אותם כללים כמו בשרת (repo.list_events)
function filterEvents(events, q) {
  const locId = q.location_id ? Number(q.location_id) : null, radius = q.radius_km ? Number(q.radius_km) : null;
  let center = null;
  if (locId !== null) {
    const l = state.locations.find((x) => x.id === locId);
    if (l && l.lat !== null && radius) center = [l.lat, l.lon];
  } else if (q.lat && q.lon && radius) center = [Number(q.lat), Number(q.lon)];
  const since = q.hours ? Date.now() - Number(q.hours) * 3600000 : null;
  return events.filter((e) => {
    if (q.type && e.event_type !== q.type) return false;
    if (q.verification && e.verification !== q.verification) return false;
    if (since && new Date(e.updated_at).getTime() < since) return false;
    const has = e.location && e.location.lat !== null;
    const d = center && has ? km(center[0], center[1], e.location.lat, e.location.lon) : null;
    e.distance_km = d === null ? null : Math.round(d * 10) / 10;
    if (locId !== null) return e.location?.id === locId || (d !== null && d <= radius);
    if (center) return d !== null && d <= radius;
    return true;
  });
}

async function fetchEvents(q) {
  if (!STATIC) return api("api/events?" + new URLSearchParams(q));
  return filterEvents(await getData("events"), q);
}

function ago(iso) {
  if (!iso) return "";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "עכשיו";
  if (m < 60) return `לפני ${m} דק׳`;
  if (m < 1440) return `לפני ${Math.round(m / 60)} שע׳`;
  return `לפני ${Math.round(m / 1440)} ימים`;
}
const clock = (iso) => new Date(iso).toLocaleString("he-IL", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" });

/* ---------- כרטיס אירוע ---------- */
function eventCard(e) {
  const [label, icon] = TYPES[e.event_type] || TYPES.other;
  const loc = e.location
    ? `${e.location.name}${e.location_precision === "approx" ? " (מיקום משוער)" : ""}`
    : "מיקום לא ידוע";
  const links = e.reports.map((r, i) => r.url
    ? el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, r.source_name)
    : el("span", {}, r.source_name + " (אין קישור)")).flatMap((n, i) => (i ? [" · ", n] : [n]));
  return el("article", { class: `card sev-${e.severity} ${e.status === "ended" ? "ended" : ""}` },
    el("div", { class: "card-head" },
      el("span", { class: "tag" }, `${icon} ${label}`),
      el("span", { class: "tag" }, STATUS[e.status]),
      el("span", { class: `tag ${e.verification}` }, VERIF[e.verification]),
      e.is_demo && el("span", { class: "tag demo" }, "נתוני הדגמה")),
    el("h3", {}, e.title),
    el("div", { class: "meta" },
      el("span", {}, "📍 " + loc),
      e.distance_km !== null && el("span", {}, `כ-${e.distance_km} ק״מ`),
      el("span", { title: clock(e.first_reported_at) }, "פורסם " + ago(e.first_reported_at)),
      e.occurred_at ? el("span", {}, "זמן האירוע: " + clock(e.occurred_at)) : el("span", {}, "זמן האירוע לא ידוע"),
      e.updated_at !== e.first_reported_at && el("span", {}, "עודכן " + ago(e.updated_at))),
    e.summary && el("p", {}, e.summary),
    el("div", { class: "srcs" }, `${e.independent_sources} מקורות עצמאיים: `, links));
}

/* ---------- הודעה גולמית ממקור ---------- */
function rawCard(r) {
  return el("article", { class: "card raw" },
    el("div", { class: "card-head" },
      el("span", { class: "tag" }, r.source_name),
      r.is_official && el("span", { class: "tag official" }, "מקור רשמי"),
      el("span", { class: "tag" }, "הודעה גולמית · טרם נותחה"),
      r.edited_at && el("span", { class: "tag" }, "נערכה")),
    el("p", { class: "raw-text", dir: "auto" }, r.content || "(הודעה ללא טקסט – תמונה או סרטון בלבד)"),
    el("div", { class: "meta" },
      el("span", {}, "פורסם: " + clock(r.published_at) + " (" + ago(r.published_at) + ")"),
      el("span", {}, "נקלט: " + clock(r.ingested_at))),
    el("div", { class: "srcs" }, r.url
      ? el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "להודעה המקורית בטלגרם")
      : "אין קישור למקור"));
}

function setSeg(which) {
  state.seg = which;
  $("#raw-pane").hidden = which !== "raw"; $("#events-pane").hidden = which !== "events";
  $("#seg-raw").classList.toggle("on", which === "raw"); $("#seg-events").classList.toggle("on", which === "events");
}

function renderFeed(target, events, emptyText) {
  target.replaceChildren(...(events.length ? events.map(eventCard) : [el("p", { class: "empty" }, emptyText)]));
}

/* ---------- טעינה וסינון ---------- */
async function loadEvents() {
  const f = state.filters, q = {};
  if (f.type) q.type = f.type;
  if (f.hours) q.hours = f.hours;
  if (f.verification) q.verification = f.verification;
  if (f.location_id === "gps" && state.gps) {
    q.lat = state.gps.lat; q.lon = state.gps.lon; q.radius_km = f.radius_km || 10;
  } else if (f.location_id && f.location_id !== "gps") {
    q.location_id = f.location_id;
    if (f.radius_km) q.radius_km = f.radius_km;
  }
  try {
    const [events, meta, raw] = await Promise.all([fetchEvents(q), getData("meta"), getData("raw")]);
    state.events = events;
    const filtered = Object.keys(q).length > 0;
    renderFeed($("#feed"), events, filtered ? "אין אירועים שתואמים את הסינון."
      : "עדיין אין אירועים מאומתים. הודעות גולמיות אינן הופכות לאירועים, אינן מופיעות על המפה ואינן מפעילות התראות עד שיתווסף שלב הניתוח והאימות.");
    $("#raw").replaceChildren(...(raw.length ? raw.map(rawCard) : [el("p", { class: "empty" }, "עדיין לא נקלטו הודעות ממקור אמיתי.")]));
    if (state.seg === null) setSeg(raw.length && !events.length ? "raw" : "events");
    const checked = meta.generated_at || meta.server_time;
    $("#updated").textContent = STATIC ? "נבדק " + ago(checked)
      : meta.last_updated ? "עדכון אחרון: " + ago(meta.last_updated) : "אין נתונים";
    const b = $("#demo-banner");
    if (STATIC) {
      const failed = (meta.collector || []).filter((r) => r.error);
      const none = meta.real_reports_ingested === 0;
      b.hidden = !none && meta.run_ok;
      b.textContent = none ? "ניסוי: עדיין לא נקלטה אף הודעה אמיתית מטלגרם. המערכת אינה פעילה."
        : "ההרצה האחרונה נכשלה (" + failed.map((r) => r.source + ": " + r.error).join("; ") + "). מוצגות הודעות מהרצות קודמות.";
      $("#run-status").textContent = `הרצה אחרונה: ${clock(meta.generated_at)} · ${meta.run_ok ? "הצליחה" : "נכשלה"} · ` +
        `הודעה חדשה נקלטה לאחרונה: ${meta.last_message_ingested_at ? clock(meta.last_message_ingested_at) : "אף פעם"} · ` +
        `סך הכול ${meta.real_reports_ingested} הודעות`;
    } else {
      b.hidden = !(meta.demo_events > 0);
      b.textContent = meta.real_reports_ingested === 0
        ? "שלב א: מוצגים נתוני הדגמה בלבד. עדיין לא נקלט מידע ממקור אמיתי."
        : "חלק מהאירועים המוצגים הם נתוני הדגמה ומסומנים ככאלה.";
    }
    if (state.map) drawMap();
  } catch (e) {
    renderFeed($("#feed"), [], "לא ניתן לטעון נתונים כרגע: " + e.message);
    $("#updated").textContent = "אין חיבור לשרת";
  }
}

function locationOptions(select, first) {
  select.replaceChildren(el("option", { value: "" }, first));
  for (const [kind, title] of Object.entries(LOC_KIND)) {
    const items = state.locations.filter((l) => l.kind === kind);
    if (items.length) select.append(el("optgroup", { label: title }, items.map((l) => el("option", { value: l.id }, l.name_he))));
  }
}

function setupFilters() {
  const chips = $("#type-chips");
  const draw = () => chips.replaceChildren(
    el("button", { class: "chip" + (state.filters.type ? "" : " on"), onclick: () => pick("") }, "הכול"),
    ...Object.entries(TYPES).map(([k, [label, icon]]) =>
      el("button", { class: "chip" + (state.filters.type === k ? " on" : ""), onclick: () => pick(k) }, `${icon} ${label}`)));
  const pick = (k) => { state.filters.type = k; draw(); changed(); };
  const changed = () => {
    const f = { ...state.filters };
    if (f.location_id === "gps") f.location_id = ""; // בחירת GPS לא נשמרת בין ביקורים
    store.set("tl_filters", f);
    loadEvents();
  };
  draw();
  locationOptions($("#f-loc"), "כל הצפון");
  if (state.filters.location_id === "gps") state.filters.location_id = "";
  const bind = (id, key) => {
    const n = $(id); n.value = state.filters[key] ?? "";
    n.addEventListener("change", () => { state.filters[key] = n.value; changed(); });
  };
  bind("#f-loc", "location_id"); bind("#f-radius", "radius_km"); bind("#f-hours", "hours"); bind("#f-verif", "verification");

  $("#gps").addEventListener("click", () => {
    const s = $("#gps-state");
    if (!navigator.geolocation) { s.textContent = "המכשיר לא תומך במיקום."; return; }
    s.textContent = "מבקש הרשאה…";
    navigator.geolocation.getCurrentPosition((p) => {
      // עיגול ל-2 ספרות (~1 ק"מ): השרת מקבל מיקום משוער בלבד, ושום דבר לא נשמר
      state.gps = { lat: p.coords.latitude.toFixed(2), lon: p.coords.longitude.toFixed(2) };
      if (!$("#f-loc option[value=gps]")) $("#f-loc").append(el("option", { value: "gps" }, "סביב המיקום שלי"));
      $("#f-loc").value = "gps"; state.filters.location_id = "gps";
      if (!state.filters.radius_km) { state.filters.radius_km = "10"; $("#f-radius").value = "10"; }
      s.textContent = "מוצגים אירועים סביבך (מיקום משוער, לא נשמר).";
      loadEvents();
    }, () => { s.textContent = "לא התקבלה הרשאה – אפשר לבחור אזור ידנית."; },
    { enableHighAccuracy: false, maximumAge: 600000, timeout: 10000 });
  });
}

/* ---------- מפה ---------- */
function drawMap() {
  if (!window.L) { $("#map-note").textContent = "ספריית המפה לא נטענה (בדקו חיבור לאינטרנט)."; return; }
  if (!state.map) {
    state.map = L.map("map").setView([32.98, 35.45], 10);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "© OpenStreetMap contributors" }).addTo(state.map);
    state.layer = L.layerGroup().addTo(state.map);
  }
  state.layer.clearLayers();
  let shown = 0;
  for (const e of state.events) {
    const l = e.location;
    // אירוע מוצג על המפה רק אם יש לו מיקום עם קואורדינטות. לא ממציאים נקודות.
    if (!l || l.lat === null || e.location_precision === "unknown") continue;
    shown++;
    const approx = e.location_precision === "approx" || l.coord_quality !== "verified";
    if (approx) L.circle([l.lat, l.lon], { radius: 1500, color: "#d93a26", weight: 1, dashArray: "4 4", fillOpacity: 0.08 }).addTo(state.layer);
    L.marker([l.lat, l.lon], { icon: L.divIcon({ className: "pin", html: (TYPES[e.event_type] || TYPES.other)[1], iconSize: [28, 28] }) })
      .bindPopup(() => eventCard(e), { maxWidth: 300 }).addTo(state.layer);
  }
  const loc = state.locations.find((x) => String(x.id) === String(state.filters.location_id));
  if (loc && loc.lat !== null) state.map.setView([loc.lat, loc.lon], 12);
  $("#map-note").textContent = `על המפה ${shown} מתוך ${state.events.length} אירועים. עיגול מקווקו = מיקום משוער. ` +
    "אירועים ללא מיקום מזוהה מופיעים בפיד בלבד.";
  setTimeout(() => state.map.invalidateSize(), 50);
}

/* ---------- התראות (מקומי במכשיר) ---------- */
function setupAlerts() {
  locationOptions($("#a-loc"), "כל האזורים");
  $("#a-type").replaceChildren(el("option", { value: "" }, "כל הסוגים"),
    ...Object.entries(TYPES).map(([k, [label]]) => el("option", { value: k }, label)));
  $("#a-add").addEventListener("click", () => {
    const rules = store.get("tl_rules", []);
    const rule = { loc: $("#a-loc").value, type: $("#a-type").value };
    if (!rules.some((r) => r.loc === rule.loc && r.type === rule.type)) rules.push(rule);
    store.set("tl_rules", rules); drawAlerts();
  });
}
async function drawAlerts() {
  const rules = store.get("tl_rules", []);
  const name = (id) => state.locations.find((l) => String(l.id) === id)?.name_he || "כל האזורים";
  $("#a-rules").replaceChildren(...rules.map((r, i) => el("li", {},
    `${r.type ? TYPES[r.type][0] : "כל הסוגים"} · ${name(r.loc)}`,
    el("button", { class: "btn ghost small", onclick: () => { rules.splice(i, 1); store.set("tl_rules", rules); drawAlerts(); } }, "הסרה"))));
  if (!rules.length) { renderFeed($("#a-feed"), [], "עדיין לא הוגדרו כללים."); return; }
  try {
    const events = await fetchEvents({ hours: 24 });
    const hit = events.filter((e) => rules.some((r) =>
      (!r.type || r.type === e.event_type) && (!r.loc || String(e.location?.id) === r.loc)));
    renderFeed($("#a-feed"), hit, "אין אירועים תואמים ב-24 השעות האחרונות.");
  } catch (e) { renderFeed($("#a-feed"), [], "לא ניתן לטעון: " + e.message); }
}

/* ---------- ניהול מקורות ---------- */
function sourceCard(s) {
  const act = async (fn) => { try { await fn(); } catch (e) { $("#src-err").textContent = e.message; } loadSources(); };
  return el("article", { class: "card" },
    el("div", { class: "card-head" },
      el("span", { class: "tag" }, KIND[s.kind]),
      el("span", { class: `tag st-${s.status}` }, SRC_STATUS[s.status]),
      !s.enabled && el("span", { class: "tag" }, "מושבת"),
      s.is_official && el("span", { class: "tag official" }, "רשמי"),
      s.is_demo && el("span", { class: "tag demo" }, "הדגמה")),
    el("h3", {}, s.name),
    el("div", { class: "meta" },
      el("span", { dir: "ltr" }, s.address),
      el("span", {}, "עדיפות " + s.priority),
      el("span", {}, "הודעות שנקלטו: " + s.ingested_count),
      el("span", {}, "קליטה אחרונה: " + (s.last_ingest_at ? ago(s.last_ingest_at) : "אף פעם")),
      el("span", {}, "בדיקה אחרונה: " + (s.last_check_at ? ago(s.last_check_at) : "לא בוצעה"))),
    s.last_error && el("p", { class: "error" }, "שגיאה: " + s.last_error),
    el("div", { class: "row" },
      el("button", { class: "btn ghost small", onclick: () => act(async () => {
        const r = await api(`api/admin/sources/${s.id}/test`, { method: "POST", admin: true });
        $("#src-err").textContent = ""; $("#src-msg").textContent = `${s.name}: ${r.message}`;
      }) }, "בדיקת חיבור"),
      el("button", { class: "btn ghost small", onclick: () => act(() =>
        api(`api/admin/sources/${s.id}`, { method: "PATCH", admin: true, body: { enabled: !s.enabled } })) },
        s.enabled ? "השבתה" : "הפעלה"),
      el("button", { class: "btn ghost small", onclick: () => editSource(s) }, "עריכה"),
      el("button", { class: "btn ghost small", onclick: () => {
        if (window.confirm(`למחוק את "${s.name}" וכל ההודעות שנקלטו ממנו?`))
          act(() => api(`api/admin/sources/${s.id}`, { method: "DELETE", admin: true }));
      } }, "מחיקה")));
}

function editSource(s) {
  state.editing = s ? s.id : null;
  $("#src-form-title").textContent = s ? "עריכת מקור" : "הוספת מקור";
  $("#s-cancel").hidden = !s;
  $("#s-kind").disabled = !!s;
  $("#s-name").value = s?.name || ""; $("#s-kind").value = s?.kind || "telegram";
  $("#s-address").value = s?.address || ""; $("#s-priority").value = s?.priority || 3;
  $("#s-official").checked = !!s?.is_official;
  for (const o of $("#s-coverage").options) o.selected = !!s?.coverage.includes(Number(o.value));
  for (const c of document.querySelectorAll("#s-types input")) c.checked = !!s?.wanted_types.includes(c.value);
  if (s) $("#src-form").scrollIntoView({ behavior: "smooth" });
}

async function loadSources() {
  try {
    const list = await api("api/admin/sources", { admin: true });
    $("#admin-login").hidden = true; $("#admin-panel").hidden = false;
    $("#sources").replaceChildren(...(list.length ? list.map(sourceCard) : [el("p", { class: "empty" }, "עדיין לא הוגדרו מקורות.")]));
  } catch (e) {
    sessionStorage.removeItem("tl_admin");
    $("#admin-login").hidden = false; $("#admin-panel").hidden = true;
    $("#admin-err").textContent = e.status === 401 ? "קוד מנהל שגוי." : e.message;
  }
}

async function loadSourcesReadOnly() {
  $("#admin-static").hidden = false; $("#admin-login").hidden = true; $("#admin-panel").hidden = true;
  try {
    const list = await getData("sources");
    $("#sources-ro").replaceChildren(...list.map((s) => el("article", { class: "card" },
      el("div", { class: "card-head" },
        el("span", { class: "tag" }, KIND[s.kind]),
        el("span", { class: `tag st-${s.status}` }, SRC_STATUS[s.status]),
        !s.enabled && el("span", { class: "tag" }, "מושבת"),
        s.is_official && el("span", { class: "tag official" }, "רשמי")),
      el("h3", {}, s.name),
      el("div", { class: "meta" },
        el("span", { dir: "ltr" }, s.address),
        el("span", {}, "הודעות שנקלטו: " + s.ingested_count),
        el("span", {}, "קליטה אחרונה: " + (s.last_ingest_at ? ago(s.last_ingest_at) : "אף פעם")),
        el("span", {}, "בדיקה אחרונה: " + (s.last_check_at ? ago(s.last_check_at) : "לא בוצעה"))),
      s.last_error && el("p", { class: "error" }, "שגיאה: " + s.last_error))));
  } catch (e) { $("#sources-ro").replaceChildren(el("p", { class: "empty" }, "לא ניתן לטעון: " + e.message)); }
}

function setupAdmin() {
  $("#s-coverage").replaceChildren(...state.locations.map((l) => el("option", { value: l.id }, l.name_he)));
  $("#s-types").replaceChildren(...Object.entries(TYPES).map(([k, [label]]) =>
    el("label", { class: "check" }, el("input", { type: "checkbox", value: k }), label)));
  $("#admin-enter").addEventListener("click", () => {
    $("#admin-err").textContent = "";
    sessionStorage.setItem("tl_admin", $("#admin-token").value.trim());
    $("#admin-token").value = ""; loadSources();
  });
  $("#admin-exit").addEventListener("click", () => {
    sessionStorage.removeItem("tl_admin"); $("#admin-panel").hidden = true; $("#admin-login").hidden = false;
  });
  $("#s-cancel").addEventListener("click", () => editSource(null));
  $("#src-form").addEventListener("submit", async (ev) => {
    ev.preventDefault(); $("#src-err").textContent = "";
    const body = {
      name: $("#s-name").value, address: $("#s-address").value, priority: Number($("#s-priority").value),
      is_official: $("#s-official").checked,
      coverage: [...$("#s-coverage").selectedOptions].map((o) => Number(o.value)),
      wanted_types: [...document.querySelectorAll("#s-types input:checked")].map((c) => c.value),
    };
    try {
      if (state.editing) await api(`api/admin/sources/${state.editing}`, { method: "PATCH", admin: true, body });
      else await api("api/admin/sources", { method: "POST", admin: true, body: { ...body, kind: $("#s-kind").value } });
      editSource(null); loadSources();
    } catch (e) { $("#src-err").textContent = e.message; }
  });
}

/* ---------- ניווט ועיצוב ---------- */
function show(view) {
  for (const v of ["feed", "map", "alerts", "admin"]) $("#view-" + v).hidden = v !== view;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  if (view === "map") drawMap();
  if (view === "alerts") drawAlerts();
  if (view === "admin") {
    if (STATIC) loadSourcesReadOnly();
    else if (sessionStorage.getItem("tl_admin")) loadSources();
  }
}

function setupTheme() {
  const apply = (t) => { document.documentElement.dataset.theme = t; };
  apply(store.get("tl_theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  $("#theme").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(t); store.set("tl_theme", t);
  });
}

async function start() {
  setupTheme();
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  try { state.locations = await getData("locations"); } catch { state.locations = []; }
  $("#seg-raw").addEventListener("click", () => setSeg("raw"));
  $("#seg-events").addEventListener("click", () => setSeg("events"));
  setupFilters(); setupAlerts(); setupAdmin();
  await loadEvents();
  setInterval(() => { if (!document.hidden) loadEvents(); }, 60000);
}
start();
