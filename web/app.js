"use strict";
// צפון LIVE – ממשק המשתמש. כל טקסט מהשרת מוכנס כ-textContent בלבד (ללא innerHTML).

const TYPES = {
  security: ["ביטחון", "🛡️"], accident: ["תאונה", "🚗"], fire: ["שריפה", "🔥"], closure: ["חסימה", "🚧"],
  infrastructure: ["תשתיות", "⚡"], weather: ["מזג אוויר", "🌧️"], hazard: ["מפגע", "⚠️"], medical: ["רפואי", "🚑"],
  other: ["אחר", "📌"],
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
  locations: [], events: [], map: null, layer: null, editing: null,
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
const TRUST = {
  official: "מקור רשמי", multi_source: "כמה מקורות עצמאיים", single_source: "מקור יחיד, לא רשמי", retracted: "הוכחש או תוקן",
};
const hhmm = (iso) => new Date(iso).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
const dayLabel = (iso) => {
  const d = new Date(iso), t = new Date(); const y = new Date(); y.setDate(t.getDate() - 1);
  if (d.toDateString() === t.toDateString()) return "היום";
  if (d.toDateString() === y.toDateString()) return "אתמול";
  return d.toLocaleDateString("he-IL", { weekday: "long", day: "numeric", month: "numeric" });
};

// שורה בציר הזמן. כל הטקסט נכנס כ-textContent.
function eventCard(e, pos = {}) {
  const [label] = TYPES[e.event_type] || TYPES.other;
  const where = e.location
    ? e.location.name + (e.location.lat !== null && e.location_precision === "approx" ? ", מיקום משוער" : "")
    : "מיקום לא ידוע";
  const reports = e.reports.map((r) => el("li", {},
    r.url ? el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, r.source_name) : r.source_name,
    ` · ${clock(r.published_at)}`, r.relation === "copy" ? " (העתק)" : r.relation === "update" ? " (עדכון)" : ""));
  const n = e.independent_sources;
  return el("article", { class: `ev sev-${e.severity}${e.status === "ended" ? " ended" : ""}${pos.first ? " first" : ""}${pos.last ? " last" : ""}`,
    style: `--c: var(--t-${e.event_type})` },
    el("div", { class: "ev-time", title: clock(e.updated_at) }, hhmm(e.updated_at)),
    el("div", { class: "ev-rail" }, el("span", { class: "ev-dot" })),
    el("div", { class: "ev-body" },
      el("div", { class: "ev-kind" }, label, e.status === "ended" && el("span", { class: "ended" }, " · הסתיים"),
        e.is_demo && el("span", { class: "tag-demo" }, " נתוני הדגמה ")),
      el("h3", {}, e.title),
      !e.location && el("div", { class: "ev-where" }, "מיקום לא ידוע"),
      e.summary && el("p", { class: "ev-text", dir: "auto" }, e.summary),
      el("div", { class: "ev-foot" },
        el("span", { class: `trust ${e.verification}` }, TRUST[e.verification]),
        el("details", { class: "ev-more" },
          el("summary", {}, n === 1 ? "המקור" : `${n} מקורות`),
          el("ul", {}, reports),
          el("p", {}, (e.places && e.places.length > 1 ? "מקומות שהוזכרו: " + e.places.join(", ") : "מקום: " + where) + "."),
          el("p", {}, `פורסם לראשונה ${clock(e.first_reported_at)}. ` +
            (e.analyzer && e.analyzer.startsWith("rules") ? "האירוע זוהה אוטומטית לפי כללים, ללא בדיקה אנושית." : ""))))));
}

function renderTimeline(target, events, { groupByDay = false } = {}) {
  const out = [];
  let day = null;
  events.forEach((e, i) => {
    const d = dayLabel(e.updated_at);
    const newDay = groupByDay && d !== day;
    if (newDay) { out.push(el("div", { class: "day" }, d)); day = d; }
    const next = events[i + 1];
    const last = !next || (groupByDay && dayLabel(next.updated_at) !== d);
    out.push(eventCard(e, { first: i === 0 || newDay, last }));
  });
  target.replaceChildren(...out);
}

/* ---------- הודעה גולמית ממקור ---------- */
const FRESH_MS = 24 * 3600 * 1000;   // רק הודעה מ-24 השעות האחרונות נחשבת עדכנית
const isRecent = (iso) => Date.now() - new Date(iso).getTime() <= FRESH_MS;

function rawCard(r) {
  const recent = isRecent(r.published_at);
  return el("article", { class: "card raw" + (recent ? "" : " old") },
    el("div", { class: "card-head" },
      el("span", { class: "tag" }, r.source_name),
      r.is_official ? el("span", { class: "tag official" }, "מקור רשמי")
        : el("span", { class: "tag single_source" }, "מקור לא רשמי · לא מאומת"),
      r.historical && el("span", { class: "tag historical" }, "היסטורית · נקלטה באיחור, אינה דיווח חדש"),
      !recent && !r.historical && el("span", { class: "tag historical" }, "ישנה מ-24 שעות"),
      r.edited_at && el("span", { class: "tag" }, "נערכה"),
      r.noise && el("span", { class: "tag st-error" }, "סונן: " + r.noise),
      !r.noise && r.analysis && (r.analysis.relevant
        ? el("span", { class: "tag st-ingesting" }, `נכלל באירוע · ${TYPES[r.analysis.type][0]} · ${r.analysis.location}`)
        : el("span", { class: "tag" }, r.analysis.north ? "לא נכלל: לא זוהה סוג אירוע" : "לא נכלל: לא זוהה מקום בצפון"))),
    el("p", { class: "raw-text", dir: "auto" }, r.content || "(הודעה ללא טקסט – תמונה או סרטון בלבד)"),
    r.content && r.content.endsWith("…") && el("p", { class: "note" }, "פתיח בלבד. הטקסט המלא נמצא בהודעה המקורית."),
    el("dl", { class: "times" },
      el("dt", {}, "פורסם בטלגרם"), el("dd", {}, clock(r.published_at) + " (" + ago(r.published_at) + ")"),
      el("dt", {}, "נקלט במערכת"), el("dd", {}, clock(r.ingested_at) + " (" + ago(r.ingested_at) + ")")),
    el("div", { class: "srcs" }, r.url
      ? el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "להודעה המקורית בטלגרם")
      : "אין קישור למקור"));
}

function renderRaw(raw, sources, meta) {
  const noise = raw.filter((r) => r.noise), reports = raw.filter((r) => !r.noise);
  const recent = reports.filter((r) => isRecent(r.published_at)), old = reports.filter((r) => !isRecent(r.published_at));
  $("#raw-noise").replaceChildren(...noise.map(rawCard));
  $("#noise").hidden = !noise.length;
  $("#noise-title").textContent = `סוננו · ${noise.length} הודעות שאינן דיווח`;
  $("#raw").replaceChildren(...(recent.length ? recent.map(rawCard) : [el("p", { class: "empty" },
    raw.length ? "אין דיווחים מ-24 השעות האחרונות. המקורות לא פרסמו הודעות חדשות בפרק הזמן הזה."
               : "עדיין לא נקלטו הודעות ממקור אמיתי.")]));
  $("#raw-archive").replaceChildren(...old.map(rawCard));
  $("#archive").hidden = !old.length;
  $("#archive-title").textContent = `ארכיון · ${old.length} הודעות ישנות מ-24 שעות`;
  // אזהרה לכל מקור פעיל שלא פרסם ב-24 השעות האחרונות: קריאה מוצלחת ≠ מקור עדכני
  const warn = [];
  for (const s of sources.filter((x) => x.enabled && !x.is_demo)) {
    if (s.status === "error") warn.push(`⚠️ ${s.name}: הקריאה האחרונה נכשלה – ${s.last_error || "שגיאה"}.`);
    else if (!s.newest_published_at) warn.push(`⚠️ ${s.name}: עדיין לא נקלטה ממנו אף הודעה.`);
    else if (!isRecent(s.newest_published_at))
      warn.push(`⚠️ ${s.name} לא פרסם הודעה ב-24 השעות האחרונות (האחרונה: ${clock(s.newest_published_at)}, ${ago(s.newest_published_at)}). ` +
        "הקריאה מטלגרם הצליחה, אבל אין ממנו דיווח עדכני.");
  }
  if (STATIC && meta.generated_at && Date.now() - new Date(meta.generated_at).getTime() > 3600 * 1000)
    warn.push(`⚠️ האיסוף לא רץ מעל שעה (קריאה אחרונה ${ago(meta.generated_at)}). ייתכן שההרצות המתוזמנות נעצרו.`);
  $("#source-warnings").replaceChildren(...warn.map((t) => el("p", { class: "warn" }, t)));
}


function renderFeed(target, events, emptyText) {
  if (events.length) renderTimeline(target, events);
  else target.replaceChildren(el("p", { class: "empty-state" }, emptyText));
}

/* ---------- תמונת מצב בראש הפיד ---------- */
function renderPulse(recent, filtered, meta, sources) {
  const n = recent.length, h = $("#pulse-head");
  const scope = filtered ? "לפי הסינון, " : "";
  const t = state.filters.type && TYPES[state.filters.type] ? TYPES[state.filters.type][0] : null;
  h.textContent = n === 0 ? (t ? `אין אירועים מסוג ${t} ב-24 השעות האחרונות`
    : filtered ? "אין אירועים שתואמים את הסינון ב-24 השעות האחרונות" : "שקט בצפון ב-24 השעות האחרונות")
    : n === 1 ? `${scope}אירוע אחד בצפון ב-24 השעות האחרונות` : `${scope}${n} אירועים בצפון ב-24 השעות האחרונות`;
  h.className = n === 0 && !filtered ? "quiet" : "";
  const checked = meta.generated_at || meta.server_time;
  const on = sources.filter((x) => x.enabled && !x.is_demo);
  const quiet = on.filter((x) => x.status === "error" || !x.newest_published_at || !isRecent(x.newest_published_at));
  $("#pulse-sub").textContent = checked
    ? `${n === 0 && !filtered ? "לא זוהו אירועים ב" + on.length + " המקורות שנבדקו. " : ""}נבדק ${ago(checked)}.`
    : "";
  const link = $("#pulse-sources");
  link.hidden = !quiet.length;
  link.textContent = quiet.length === 1 ? "מקור אחד לא פרסם ב-24 השעות האחרונות" : `${quiet.length} מקורות לא פרסמו ב-24 השעות האחרונות`;
  const fresh = STATIC && checked && Date.now() - new Date(checked).getTime() < 3600 * 1000 && meta.run_ok !== false;
  $("#live-dot").classList.toggle("on", !!fresh);
}

/* ---------- טעינה וסינון ---------- */
async function loadEvents() {
  const f = state.filters, q = {};
  if (f.hours) q.hours = f.hours;
  if (f.verification) q.verification = f.verification;
  if (f.location_id === "gps" && state.gps) {
    q.lat = state.gps.lat; q.lon = state.gps.lon; q.radius_km = f.radius_km || 10;
  } else if (f.location_id && f.location_id !== "gps") {
    q.location_id = f.location_id;
    if (f.radius_km) q.radius_km = f.radius_km;
  }
  try {
    const [allTypes, meta, raw, sources] = await Promise.all([fetchEvents(q), getData("meta"), getData("raw"),
      getData("sources").catch(() => [])]);
    // הסינון לפי סוג נעשה כאן, כדי שאפשר יהיה להציג כמה אירועים יש מכל סוג
    state.typeCounts = {};
    for (const e of allTypes) state.typeCounts[e.event_type] = (state.typeCounts[e.event_type] || 0) + 1;
    state.typeTotal = allTypes.length;
    const events = f.type ? allTypes.filter((e) => e.event_type === f.type) : allTypes;
    if (state.drawChips) state.drawChips();
    state.events = events;
    const filtered = Object.keys(q).length > 0 || !!f.type;
    const recentEv = events.filter((e) => isRecent(e.updated_at)), olderEv = events.filter((e) => !isRecent(e.updated_at));
    renderFeed($("#feed"), recentEv, filtered ? "אין אירועים שתואמים את הסינון."
      : "כשיזוהה אירוע בצפון באחד המקורות, הוא יופיע כאן.");
    renderTimeline($("#feed-archive"), olderEv, { groupByDay: true });
    $("#feed-archive-box").hidden = !olderEv.length;
    $("#feed-archive-title").textContent = `אירועים קודמים (${olderEv.length})`;
    renderPulse(recentEv, filtered, meta, sources);
    renderRaw(raw, sources, meta);
    const checked = meta.generated_at || meta.server_time;
    $("#updated").textContent = STATIC ? "עודכן " + ago(checked)
      : meta.last_updated ? "עדכון אחרון: " + ago(meta.last_updated) : "אין נתונים";
    const b = $("#demo-banner");
    if (STATIC) {
      const failed = (meta.collector || []).filter((r) => r.error);
      const none = meta.real_reports_ingested === 0;
      b.hidden = !none && meta.run_ok;
      b.textContent = none ? "ניסוי: עדיין לא נקלטה אף הודעה אמיתית מטלגרם. המערכת אינה פעילה."
        : "ההרצה האחרונה נכשלה (" + failed.map((r) => r.source + ": " + r.error).join("; ") + "). מוצגות הודעות מהרצות קודמות.";
      $("#run-status").textContent = `קריאה אחרונה מטלגרם: ${clock(meta.generated_at)} (${ago(meta.generated_at)})` +
        ` · הקריאה ${meta.run_ok ? "הצליחה" : "נכשלה"}` +
        ` · הודעה אחרונה שפורסמה במקורות: ${meta.newest_published_at ? clock(meta.newest_published_at) : "אין"}` +
        ` · ${meta.real_reports_ingested} הודעות שמורות`;
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

function updateFilterSummary() {
  const f = state.filters, n = ["location_id", "hours", "verification"].filter((k) => f[k]).length;
  const t = $("#more-filters-title");
  t.textContent = n ? `סינון פעיל (${n})` : "סינון לפי אזור, זמן ואימות";
  t.classList.toggle("active", n > 0);
}

function setupFilters() {
  const chips = $("#type-chips");
  // רק סוגים שיש בהם אירועים (וסוג שנבחר), עם מספר. כך התפריט קצר ונכנס במסך בלי גלילה הצידה.
  const draw = () => {
    const counts = state.typeCounts || {};
    const shown = Object.entries(TYPES).filter(([k]) => counts[k] || state.filters.type === k)
      .sort((a, b) => (counts[b[0]] || 0) - (counts[a[0]] || 0));
    chips.replaceChildren(
      el("button", { class: "chip" + (state.filters.type ? "" : " on"), "aria-pressed": String(!state.filters.type), onclick: () => pick("") },
        "הכול", el("b", {}, String(state.typeTotal ?? ""))),
      ...shown.map(([k, [label]]) =>
        el("button", { class: "chip" + (state.filters.type === k ? " on" : ""), style: `--c: var(--t-${k})`,
          "aria-pressed": String(state.filters.type === k), onclick: () => pick(k) },
          el("i", {}), label, el("b", {}, String(counts[k] || 0)))));
  };
  state.drawChips = draw;
  const pick = (k) => { state.filters.type = k; draw(); changed(); };
  const changed = () => {
    updateFilterSummary();
    const f = { ...state.filters };
    if (f.location_id === "gps") f.location_id = ""; // בחירת GPS לא נשמרת בין ביקורים
    store.set("tl_filters", f);
    loadEvents();
  };
  draw();
  locationOptions($("#f-loc"), "כל הצפון");
  updateFilterSummary();
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
    L.marker([l.lat, l.lon], { icon: L.divIcon({ className: `pin t-${e.event_type}`, html: "", iconSize: [16, 16] }) })
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

const IDENTITY = {
  telegram_verified: ["רשמי · מאומת בטלגרם", "official"],
  official_link: ["רשמי · קישור מחשבון רשמי של הגוף", "official"],
  self_declared: ["מציג עצמו כרשמי · לא אומת", "single_source"],
  unofficial: ["לא רשמי", "single_source"],
};

function sourceHealth(s) {
  if (!s.enabled) return ["מושבת", ""];
  if (s.status === "error") return ["שגיאה בקריאה", "st-error"];
  if (!s.newest_published_at) return ["לא נקלטו הודעות", "st-error"];
  if (!isRecent(s.newest_published_at)) return ["תקין · לא פרסם ב-24 שעות", "single_source"];
  return ["תקין · פרסם ב-24 השעות האחרונות", "st-ingesting"];
}

function sourceRow(s) {
  const [health, hcls] = sourceHealth(s);
  const [idText, idCls] = IDENTITY[s.identity] || [s.is_official ? "רשמי" : "לא רשמי", s.is_official ? "official" : "single_source"];
  const when = (iso) => (iso ? `${clock(iso)} (${ago(iso)})` : "—");
  return el("article", { class: "card src" + (s.enabled ? "" : " ended") },
    el("div", { class: "card-head" },
      el("span", { class: `tag ${hcls}` }, health),
      el("span", { class: `tag ${idCls}` }, idText),
      s.last_gap > 0 && el("span", { class: "tag st-error" }, `ייתכן שהוחמצו ${s.last_gap} הודעות`)),
    el("h3", {}, s.name),
    el("dl", { class: "times" },
      el("dt", {}, "קישור"), el("dd", {}, el("a", { href: s.url || s.address, target: "_blank", rel: "noopener noreferrer", dir: "ltr" },
        (s.url || s.address).replace("https://", ""))),
      el("dt", {}, "סוג מקור"), el("dd", {}, `${KIND[s.kind]}${s.category ? " · " + s.category : ""}`),
      el("dt", {}, "פרסום אחרון במקור"), el("dd", {}, when(s.newest_published_at)),
      el("dt", {}, "בדיקה אחרונה"), el("dd", {}, when(s.last_check_at)),
      el("dt", {}, "הודעות שנקלטו"), el("dd", {}, String(s.ingested_count)),
      s.evidence && el("dt", {}, "בסיס לזיהוי"), s.evidence && el("dd", {}, s.evidence)),
    s.note && el("p", { class: "note" }, s.note),
    s.last_error && el("p", { class: "error" }, "שגיאה: " + s.last_error));
}

async function loadSourcesReadOnly() {
  $("#admin-static").hidden = false; $("#admin-login").hidden = true; $("#admin-panel").hidden = true;
  try {
    const list = (await getData("sources")).filter((x) => !x.is_demo);
    const on = list.filter((x) => x.enabled), off = list.filter((x) => !x.enabled);
    const ok = on.filter((x) => sourceHealth(x)[1] === "st-ingesting").length;
    $("#sources-ro").replaceChildren(
      el("p", { class: "status" }, `${on.length} מקורות פעילים · ${ok} פרסמו ב-24 השעות האחרונות · ${off.length} נבדקו ולא הופעלו`),
      el("h3", {}, "מקורות פעילים"), ...on.map(sourceRow),
      off.length && el("details", { class: "archive" },
        el("summary", {}, `מקורות שנבדקו ולא הופעלו (${off.length})`), ...off.map(sourceRow)));
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
  $("#pulse-sources").addEventListener("click", () => show("admin"));
  setupFilters(); setupAlerts(); setupAdmin();
  await loadEvents();
  setInterval(() => { if (!document.hidden) loadEvents(); }, 60000);
}
start();
