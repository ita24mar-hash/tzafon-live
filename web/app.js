"use strict";
// רדאר LIVE – ממשק המשתמש. כל טקסט מהשרת מוכנס כ-textContent בלבד (ללא innerHTML).

const TYPES = {
  security: ["ביטחון", "🛡️"], accident: ["תאונה", "🚗"], fire: ["שריפה", "🔥"], closure: ["חסימה", "🚧"],
  infrastructure: ["תשתיות", "⚡"], weather: ["מזג אוויר", "🌧️"], hazard: ["מפגע", "⚠️"], medical: ["רפואי", "🚑"],
  earthquake: ["רעידת אדמה", "〰️"], cyber: ["סייבר", "🔒"], health: ["בריאות הציבור", "⚕️"],
  other: ["אחר", "📌"],
};
// סמל קטן לכל סוג אירוע (קו, 24x24) – כדי שיבינו במבט מה קרה
const ICONS = {
  security: "M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6z",
  fire: "M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.7 2.3-4.8.2 1.6 1 2.6 2.2 3 .2-3-.8-5.6.5-8.2z",
  accident: "M4 13l2-6h12l2 6v4H4z M4 13h16 M7 17v2 M17 17v2 M7.5 15h.01 M16.5 15h.01",
  closure: "M3 9h18v5H3z M7 9l3 5 M12 9l3 5 M17 9l3 5 M6 14v6 M18 14v6",
  infrastructure: "M13 3L5 14h6l-1 7 8-11h-6z",
  weather: "M7 15a4 4 0 0 1 .5-8 5 5 0 0 1 9.5 1.5A3.5 3.5 0 0 1 17 15z M8 18l-1 2 M12 18l-1 2 M16 18l-1 2",
  hazard: "M12 3l9 17H3z M12 10v4 M12 17h.01",
  medical: "M10 4h4v6h6v4h-6v6h-4v-6H4v-4h6z",
  earthquake: "M2 12h4l2-5 3 11 3-14 3 10 2-2h3",
  health: "M12 21s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.5-7 10-7 10z M9 12h6 M12 9v6",
  cyber: "M7 11V8a5 5 0 0 1 10 0v3 M5 11h14v10H5z M12 15v2",
  other: "M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z M12 10h.01",
};
const iconSvg = (t) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${ICONS[t] || ICONS.other}"/></svg>`;
function icon(t, cls = "ico") {
  const s = document.createElement("span");
  s.className = cls;
  s.innerHTML = iconSvg(t);           // מחרוזות קבועות מהקוד בלבד
  return s;
}
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
// אזורים (זהים ל-app/gazetteer.py REGIONS). כל אירוע משויך לאזור לפי היישובים שהוזכרו בו.
const REGIONS = [
  ["galil-elyon", "הגליל העליון והגולן"], ["galil-maaravi", "הגליל המערבי ומרכז הגליל"],
  ["kineret-amakim", "כנרת והעמקים"], ["haifa", "חיפה והקריות"], ["sharon", "השרון וחדרה"], ["dan", "גוש דן"],
  ["shfela", "השפלה"], ["jerusalem", "ירושלים והסביבה"], ["south", "הדרום"], ["yosh", "יהודה ושומרון"],
];
const REGION_NAME = Object.fromEntries(REGIONS);
const GENRE_NAME = { opinion: "מאמר או דעה", politics: "פוליטיקה או הצהרה", followup: "סיכום, מעצר או המשך",
  guidance: "הנחיות כלליות", abroad: "ידיעה מחו״ל", article: "כתבה ארוכה", obituary: "הודעת אבל" };
// "קרוב אליי": כשהוא פעיל, הסינון לפי מרחק מחליף את הסינון לפי אזור
const nearOn = () => state.filters.location_id === "gps" && !!state.gps;
const inRegion = (e, r) => nearOn() || !r || (e.regions || []).includes(r);
const regionIn = (r) => nearOn() ? `עד ${state.filters.radius_km || 10} ק"מ ממך`
  : r ? "ב" + REGION_NAME[r].replace(/^ה/, "") : "בכל הארץ";

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
const SEV = { 3: "קריטי", 2: "בינוני", 1: "נמוך" };
const NOW_MS = 2 * 3600 * 1000;      // "עכשיו" = השעתיים האחרונות
const isNow = (iso) => Date.now() - new Date(iso).getTime() <= NOW_MS;
function since(iso) {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "עכשיו";
  if (m < 60) return `לפני ${m} דק׳`;
  const h = Math.round(m / 60);
  if (h < 24) return h === 1 ? "לפני שעה" : h === 2 ? "לפני שעתיים" : `לפני ${h} שעות`;
  const d = Math.round(h / 24);
  return d === 1 ? "לפני יום" : `לפני ${d} ימים`;
}
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
    ` · ${clock(r.published_at)}`, r.relation === "copy" ? " (העתק)" : r.relation === "update" ? " (עדכון)" : r.relation === "recap" ? " (סיכום בדיעבד)" : ""));
  const n = e.independent_sources;
  return el("article", { class: `ev sev-${e.severity}${e.status === "ended" ? " ended" : ""}${isNow(e.updated_at) ? "" : " earlier"}${pos.first ? " first" : ""}${pos.last ? " last" : ""}`,
    style: `--c: var(--t-${e.event_type})` },
    el("div", { class: "ev-time", title: clock(e.updated_at) }, hhmm(e.updated_at), el("small", {}, dayLabel(e.updated_at))),
    el("div", { class: "ev-rail" }, icon(e.event_type, "ev-dot")),
    el("div", { class: "ev-body" },
      el("div", { class: "ev-kind" }, el("span", { class: `sev-badge s${e.severity || 1}` }, SEV[e.severity || 1]),
        label, el("span", { class: "ev-ago" }, " · " + since(e.updated_at)),
        e.status === "ended" && el("span", { class: "ended" }, " · הסתיים"),
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

function renderTimeline(target, events, { groupByDay = false, splitNow = false } = {}) {
  const out = [];
  let day = null;
  const grp = (e) => groupByDay ? dayLabel(e.updated_at) : splitNow ? (isNow(e.updated_at) ? "בשעתיים האחרונות" : "מוקדם יותר") : null;
  events.forEach((e, i) => {
    const d = grp(e);
    const newDay = d !== null && d !== day;
    if (newDay) { out.push(el("div", { class: "day" }, d)); day = d; }
    const next = events[i + 1];
    const last = !next || (d !== null && grp(next) !== d);
    out.push(eventCard(e, { first: i === 0 || newDay, last }));
  });
  target.replaceChildren(...out);
}

/* ---------- זמנים ---------- */
const FRESH_MS = 24 * 3600 * 1000;   // רק הודעה מ-24 השעות האחרונות נחשבת עדכנית
const isRecent = (iso) => Date.now() - new Date(iso).getTime() <= FRESH_MS;
// חלון הזמן של הפיד והכותרת: שעתיים / 6 שעות / 24 שעות (ברירת מחדל 24, נשמר במכשיר)
const WIN_TXT = { 2: "בשעתיים האחרונות", 6: "ב-6 השעות האחרונות", 24: "ב-24 השעות האחרונות" };
const inWindow = (iso) => Date.now() - new Date(iso).getTime() <= (state.windowH || 24) * 3600 * 1000;

/* אזהרות על מקורות שלא פרסמו לאחרונה או שהקריאה מהם נכשלה */
function renderSourceWarnings(sources, meta) {
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
  if (events.length) renderTimeline(target, events, { splitNow: true });
  else target.replaceChildren(el("p", { class: "empty-state" }, emptyText));
}

/* ---------- תמונת מצב בראש הפיד ---------- */
/* ---------- תקציר: מה קורה בכל תחום, נבנה מהאירועים עצמם (בלי AI – לא ממציא כלום) ---------- */
const BRIEF_ORDER = ["security", "earthquake", "health", "fire", "accident", "medical", "closure", "infrastructure", "weather",
  "cyber", "hazard", "other"];
const NATIONAL = "כל הארץ";
const placeOf = (e) => (e.places || [])[0] || (e.location && e.location.name_he) || "";
const isNational = (e) => (e.places || []).includes(NATIONAL) || (e.regions || []).length >= REGIONS.length;
function briefItem(e) {
  const bits = [hhmm(e.updated_at)];
  if (e.status === "ended") bits.push("הסתיים");
  return `${placeOf(e)} (${bits.join(", ")})`;
}
// אזהרה ארצית: מה קרה, במילים של ההודעה – עד הפסיק/הנקודה הראשונים
function nationalItem(e) {
  const r = (e.reports || [])[0], text = (r && r.content) || e.summary || e.title || "";
  let short = text.replace(/^[^:]{0,40}:\s*/, "").split(/[.,!]/)[0].trim();
  if (short.length > 60) short = short.slice(0, 58) + "…";
  return `${short || TYPES[e.event_type][0]} (${hhmm(e.updated_at)})`;
}
function renderBrief(recent) {
  const box = $("#brief");
  if (!box) return;
  const bySevTime = (a, b) => (b.severity || 1) - (a.severity || 1) || new Date(b.updated_at) - new Date(a.updated_at);
  const local = recent.filter((e) => !isNational(e) && inRegion(e, state.region));
  const national = recent.filter((e) => isNational(e) && (e.severity || 1) >= 1).sort(bySevTime);
  const elsewhere = state.region ? recent.filter((e) => !isNational(e) && !inRegion(e, state.region)
    && (e.severity || 1) === 3).sort(bySevTime) : [];
  const rows = [];
  for (const k of BRIEF_ORDER) {
    const evs = local.filter((e) => e.event_type === k && (e.severity || 1) >= 2).sort(bySevTime);
    if (!evs.length) continue;
    const top = evs.slice(0, 2).map(briefItem).join(" · ");
    rows.push(el("li", { class: `b-row t-${k}`, style: `--c: var(--t-${k})` }, icon(k, "b-ico"),
      el("span", {}, el("b", {}, TYPES[k][0] + ": "), top + (evs.length > 2 ? ` ועוד ${evs.length - 2}` : ""))));
  }
  const low = local.filter((e) => (e.severity || 1) < 2).length;
  const head = rows.length ? `${regionIn(state.region)}, ב-24 השעות האחרונות:` : `${regionIn(state.region)}: אין אירועים בחומרה בינונית ומעלה ב-24 השעות האחרונות.`;
  const extra = [];
  if (national.length) extra.push(el("li", { class: "b-row b-nat" }, icon(national[0].event_type, "b-ico"),
    el("span", {}, el("b", {}, "בכל הארץ: "), national.slice(0, 2).map(nationalItem).join(" · "))));
  if (elsewhere.length) extra.push(el("li", { class: "b-row b-else" }, icon(elsewhere[0].event_type, "b-ico"),
    el("span", {}, el("b", {}, "קריטי בשאר הארץ: "), elsewhere.slice(0, 3).map((e) => `${TYPES[e.event_type][0]} ב${placeOf(e)} (${hhmm(e.updated_at)})`).join(" · "))));
  const parts = [el("p", { class: "b-head" }, head), el("ul", {}, ...rows, ...extra)];
  if (low) parts.push(el("p", { class: "b-foot" }, `ועוד ${low === 1 ? "אירוע אחד" : low + " אירועים"} בחומרה נמוכה באזור.`));
  // תקציר כסיפור (נכתב ב-AI מהאירועים עצמם ונבדק מולם). בלי סיפור – הרשימה לבדה
  const st = !nearOn() && (state.stories || {})[state.region || "all"];
  if (st && st.text) {
    const story = [el("p", { class: "b-head" }, `${regionIn(state.region)}, ב-24 השעות האחרונות`),
      el("p", { class: "b-story", dir: "auto" }, st.text),
      el("p", { class: "b-meta" }, `✨ נכתב אוטומטית בעזרת AI מתוך הדיווחים בלבד · ${hhmm(st.at)}` +
        (st.current ? "" : " · יש דיווחים חדשים, הסיפור יתעדכן בקרוב") + ". ייתכנו טעויות – הפירוט המלא למטה."),
      el("details", { class: "b-more" }, el("summary", {}, "פירוט לפי תחום"), ...parts)];
    box.replaceChildren(...story);
  } else box.replaceChildren(...parts);
  box.hidden = false;
}

/* ---------- לוח המצב: שעון ומונים לפי חומרה ---------- */
function renderBoard() {
  const box = $("#board");
  if (!box) return;
  const evs = state.boardEvents || [], now = new Date();
  const n = (k) => evs.filter((e) => (e.severity || 1) === k).length;
  const cell = (k, label) => el("button", { type: "button", class: `cell c${k}${n(k) ? "" : " zero"}${state.minSev === k ? " on" : ""}`,
    "aria-label": `${label}: ${n(k)} אירועים. הצג מחומרה זו ומעלה`,
    onclick: () => { state.minSev = k; store.set("tl_minsev", k); state.drawSev && state.drawSev(); loadEvents(); } },
    el("b", {}, String(n(k))), el("span", {}, label));
  box.replaceChildren(
    el("div", { class: "board-clock" }, el("b", { id: "clock" }, hhmm(now.toISOString())),
      el("span", {}, now.toLocaleDateString("he-IL", { weekday: "long", day: "numeric", month: "numeric" }))),
    el("div", { class: "board-cells" }, cell(3, "קריטי"), cell(2, "בינוני"), cell(1, "נמוך")),
    el("p", { class: "board-caption" }, `אירועים ${regionIn(state.region)} ${WIN_TXT[state.windowH || 24]}`));
}
setInterval(() => { const c = $("#clock"); if (c) c.textContent = hhmm(new Date().toISOString()); }, 20000);

function renderPulse(recent, filtered, meta, sources, restCount = 0) {
  const n = recent.length, h = $("#pulse-head"), where = regionIn(state.region);
  const scope = filtered ? "לפי הסינון, " : "";
  const t = state.filters.type && TYPES[state.filters.type] ? TYPES[state.filters.type][0] : null;
  // הכותרת לפי חלון הזמן שנבחר; כמה מהם "עכשיו" (שעתיים) מופיע בשורה שמתחת
  const win = WIN_TXT[state.windowH || 24];
  const now = recent.filter((e) => isNow(e.updated_at)).length;
  const what = t ? `אירועים מסוג ${t}` : "אירועים";
  h.textContent = n === 0 ? (filtered || t ? `אין ${what} ${where} ${win}` : `שקט ${where} ${win}`)
    : n === 1 ? `${scope}אירוע אחד ${where} ${win}` : `${scope}${n} ${what} ${where} ${win}`;
  h.className = n === 0 && !filtered ? "quiet" : "";
  const lastEv = recent[0];
  const checked = meta.generated_at || meta.server_time;
  const on = sources.filter((x) => x.enabled && !x.is_demo);
  const quiet = on.filter((x) => x.status === "error" || !x.newest_published_at || !isRecent(x.newest_published_at));
  $("#pulse-sub").textContent = checked
    ? `${n && (state.windowH || 24) > 2 ? (now === 0 ? "אין חדש בשעתיים האחרונות" : now === 1 ? "אחד מהם בשעתיים האחרונות"
        : `${now} מהם בשעתיים האחרונות`) + (lastEv ? `, האחרון ${since(lastEv.updated_at)}. ` : ". ") : ""}` +
      `${restCount ? (restCount === 1 ? "אירוע אחד" : restCount + " אירועים") + " בשאר הארץ. " : ""}` +
      `${state.lowHidden ? (state.lowHidden === 1 ? "אירוע אחד בחומרה נמוכה מוסתר" : state.lowHidden + " אירועים בחומרה נמוכה מוסתרים") + ". " : ""}` +
      `נבדק ${ago(checked)}.`
    : "";
  const link = $("#pulse-sources");
  link.hidden = true;                 // מקורות שקטים מוצגים רק בלשונית המקורות
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
    const [allTypes, meta, sources, stories] = await Promise.all([fetchEvents(q), getData("meta"),
      getData("sources").catch(() => []), getData("stories").catch(() => ({}))]);
    state.stories = stories || {};
    // הסינון לפי סוג נעשה כאן, כדי שאפשר יהיה להציג כמה אירועים יש מכל סוג
    // חומרה: ברירת המחדל מסתירה אירועים בחומרה נמוכה (למשל פצוע אחד במצב קל, רכב בוער)
    const bySev = allTypes.filter((e) => (e.severity || 1) >= state.minSev);
    state.boardEvents = allTypes.filter((e) => inWindow(e.updated_at) && inRegion(e, state.region));
    renderBoard();
    renderBrief(allTypes.filter((e) => isRecent(e.updated_at)));
    state.lowHidden = allTypes.filter((e) => (e.severity || 1) < state.minSev && inWindow(e.updated_at)
      && inRegion(e, state.region)).length;
    state.typeCounts = {};
    for (const e of bySev) state.typeCounts[e.event_type] = (state.typeCounts[e.event_type] || 0) + 1;
    state.typeTotal = bySev.length;
    const events = f.type ? bySev.filter((e) => e.event_type === f.type) : bySev;
    if (state.drawChips) state.drawChips();
    state.events = events;
    // "לפי הסינון" רק כשיש סינון שהמשתמש בחר ושלא כבר מופיע בכותרת ("קרוב אליי" מופיע בה כ"עד X ק"מ ממך")
    const filtered = !!(f.type || f.hours || f.verification || (f.location_id && f.location_id !== "gps"));
    renderActiveFilters();
    const recentAll = events.filter((e) => inWindow(e.updated_at)), olderEv = events.filter((e) => !inWindow(e.updated_at));
    // האזור שנבחר קודם, ומתחתיו שאר הארץ
    const recentEv = recentAll.filter((e) => inRegion(e, state.region));
    const restEv = state.region ? recentAll.filter((e) => !inRegion(e, state.region)) : [];
    olderEv.sort((a, b) => inRegion(b, state.region) - inRegion(a, state.region) || 0);
    renderFeed($("#feed"), recentEv, filtered ? "אין אירועים שתואמים את הסינון."
      : `כשיזוהה אירוע ${regionIn(state.region)} באחד המקורות, הוא יופיע כאן.`);
    $("#feed-rest-box").hidden = !restEv.length;
    renderTimeline($("#feed-rest"), restEv, { splitNow: true });
    renderTimeline($("#feed-archive"), olderEv, { groupByDay: true });
    $("#feed-archive-box").hidden = !olderEv.length;
    $("#feed-archive-title").textContent = `אירועים קודמים (${olderEv.length})`;
    renderPulse(recentEv, filtered, meta, sources, restEv.length);
    renderSourceWarnings(sources, meta);
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

// שורה גלויה מעל הפיד עם הסינונים שפעילים (נשמרים בין ביקורים), וכפתור לניקוי
const HOURS_TXT = { 3: "3 שעות אחרונות", 12: "12 שעות אחרונות", 24: "24 שעות אחרונות", 168: "שבוע אחרון" };
const VERIF_TXT = { official: "רק רשמי", multi_source: "רק מכמה מקורות", single_source: "רק ממקור אחד", retracted: "רק מה שהוכחש" };
function renderActiveFilters() {
  const box = $("#active-filters"), f = state.filters;
  if (!box) return;
  const parts = [];
  if (f.type) parts.push(TYPES[f.type] ? TYPES[f.type][0] : f.type);
  if (f.location_id && f.location_id !== "gps") {
    const l = state.locations.find((x) => String(x.id) === String(f.location_id));
    parts.push((l ? l.name_he : "מקום") + (f.radius_km ? ` + ${f.radius_km} ק"מ` : ""));
  }
  if (f.hours) parts.push(HOURS_TXT[f.hours] || f.hours + " שעות");
  if (f.verification) parts.push(VERIF_TXT[f.verification] || f.verification);
  box.hidden = !parts.length;
  if (!parts.length) return;
  box.replaceChildren(el("span", {}, "מסונן: " + parts.join(" · ")),
    el("button", { type: "button", class: "link-btn", onclick: () => {
      Object.assign(state.filters, { type: "", hours: "", verification: "" });
      if (state.filters.location_id !== "gps") { state.filters.location_id = ""; state.filters.radius_km = ""; }
      const keep = { ...state.filters };
      if (keep.location_id === "gps") { keep.location_id = ""; keep.radius_km = ""; }   // מיקום GPS לא נשמר
      store.set("tl_filters", keep);
      for (const [id, k] of [["#f-loc", "location_id"], ["#f-radius", "radius_km"], ["#f-hours", "hours"], ["#f-verif", "verification"]])
        if ($(id)) $(id).value = state.filters[k] || "";
      updateFilterSummary(); loadEvents();
    } }, "ניקוי הסינון"));
}

function updateFilterSummary() {
  const f = state.filters, n = ["location_id", "hours", "verification"].filter((k) => f[k]).length;
  const t = $("#more-filters-title");
  t.textContent = n ? `סינון פעיל (${n})` : "סינון לפי אזור, זמן ואימות";
  t.classList.toggle("active", n > 0);
}

function setupFilters() {
  state.minSev = Number(store.get("tl_minsev", 2));
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
          k === "" ? null : icon(k, "chip-ico"), label, el("b", {}, String(counts[k] || 0)))));
  };
  state.drawChips = draw;
  // בחירת רמת חומרה
  const sevRow = $("#sev-row");
  const drawSev = () => sevRow.replaceChildren(el("span", { class: "sev-label" }, "חומרה:"),
    ...[[3, "קריטי בלבד"], [2, "בינוני ומעלה"], [1, "הכול, כולל נמוך"]].map(([v, t]) =>
      el("button", { class: "seg" + (state.minSev === v ? " on" : ""), "aria-pressed": String(state.minSev === v),
        onclick: () => { state.minSev = v; store.set("tl_minsev", v); drawSev(); loadEvents(); } }, t)));
  drawSev();
  state.drawSev = drawSev;
  state.windowH = Number(store.get("tl_window", 24));
  const winRow = $("#win-row");
  const drawWin = () => winRow.replaceChildren(el("span", { class: "sev-label" }, "זמן:"),
    ...[[2, "שעתיים"], [6, "6 שעות"], [24, "24 שעות"]].map(([v, t]) =>
      el("button", { class: "seg" + (state.windowH === v ? " on" : ""), "aria-pressed": String(state.windowH === v),
        onclick: () => { state.windowH = v; store.set("tl_window", v); drawWin(); loadEvents(); } }, t)));
  drawWin();
  const pick = (k) => { state.filters.type = k; draw(); changed(); };
  const changed = () => {
    updateFilterSummary();
    const f = { ...state.filters };
    if (f.location_id === "gps") f.location_id = ""; // בחירת GPS לא נשמרת בין ביקורים
    store.set("tl_filters", f);
    loadEvents();
  };
  draw();
  locationOptions($("#f-loc"), "כל המקומות");
  updateFilterSummary();
  if (state.filters.location_id === "gps") state.filters.location_id = "";
  const bind = (id, key) => {
    const n = $(id); n.value = state.filters[key] ?? "";
    n.addEventListener("change", () => { state.filters[key] = n.value; changed(); });
  };
  bind("#f-loc", "location_id"); bind("#f-radius", "radius_km"); bind("#f-hours", "hours"); bind("#f-verif", "verification");

  // ---- "קרוב אליי": כפתור בולט בראש המסך + בחירת טווח ----
  const nb = $("#near-btn"), row = $("#near-row"), st = $("#near-state");
  const kmBtns = row.querySelectorAll("button[data-km]");
  const paint = () => {
    const on = nearOn();
    nb.classList.toggle("on", on); nb.setAttribute("aria-pressed", String(on));
    nb.querySelector("span").textContent = on ? "קרוב אליי · ביטול" : "קרוב אליי";
    row.hidden = !on;
    kmBtns.forEach((b) => { const sel = b.dataset.km === String(state.filters.radius_km); b.classList.toggle("on", sel);
      b.setAttribute("aria-pressed", String(sel)); });
  };
  const stop = () => {
    state.gps = null; state.filters.location_id = ""; state.filters.radius_km = "";
    $("#f-loc").value = ""; $("#f-radius").value = ""; st.textContent = ""; paint(); loadEvents();
  };
  nb.addEventListener("click", () => {
    if (nearOn()) { stop(); return; }
    if (!navigator.geolocation) { row.hidden = false; st.textContent = "המכשיר לא תומך בזיהוי מיקום."; return; }
    row.hidden = false; st.textContent = "מבקש הרשאה למיקום…";
    navigator.geolocation.getCurrentPosition((p) => {
      // עיגול ל-2 ספרות (~1 ק"מ): מיקום משוער בלבד, בזיכרון, לא נשמר ולא נשלח
      state.gps = { lat: p.coords.latitude.toFixed(2), lon: p.coords.longitude.toFixed(2) };
      if (!$("#f-loc option[value=gps]")) $("#f-loc").append(el("option", { value: "gps" }, "סביב המיקום שלי"));
      $("#f-loc").value = "gps"; state.filters.location_id = "gps";
      if (!state.filters.radius_km) { state.filters.radius_km = "10"; $("#f-radius").value = "10"; }
      st.textContent = "מיקום משוער, לא נשמר.";
      paint(); loadEvents();
    }, () => { st.textContent = "לא התקבלה הרשאה למיקום. אפשר לבחור אזור במקום."; },
    { enableHighAccuracy: false, maximumAge: 600000, timeout: 10000 });
  });
  kmBtns.forEach((b) => b.addEventListener("click", () => {
    state.filters.radius_km = b.dataset.km; $("#f-radius").value = b.dataset.km; paint(); loadEvents(); }));
  state.paintNear = paint;
  $("#f-loc").addEventListener("change", () => paint());
  paint();
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
  const hours = state.mapHours || 24;
  const inWindow = state.events.filter((e) => Date.now() - new Date(e.updated_at).getTime() <= hours * 3600 * 1000);
  for (const e of inWindow) {
    const l = e.location;
    // אירוע מוצג על המפה רק אם יש לו מיקום עם קואורדינטות. לא ממציאים נקודות.
    if (!l || l.lat === null || e.location_precision === "unknown") continue;
    shown++;
    const approx = e.location_precision === "approx" || l.coord_quality !== "verified";
    if (approx) L.circle([l.lat, l.lon], { radius: 1500, color: "#d93a26", weight: 1, dashArray: "4 4", fillOpacity: 0.08 }).addTo(state.layer);
    L.marker([l.lat, l.lon], { icon: L.divIcon({ className: `pin t-${e.event_type} sev-${e.severity || 1}`, html: iconSvg(e.event_type), iconSize: [28, 28] }) })
      .bindPopup(() => eventCard(e), { maxWidth: 300 }).addTo(state.layer);
  }
  const loc = state.locations.find((x) => String(x.id) === String(state.filters.location_id));
  if (loc && loc.lat !== null) state.map.setView([loc.lat, loc.lon], 12);
  else {
    // המפה מתמקדת באירועים: קודם באזור שנבחר, ואם אין בו – בכל האירועים
    const pts = (ev) => ev.filter((e) => e.location && e.location.lat !== null).map((e) => [e.location.lat, e.location.lon]);
    const mine = pts(inWindow.filter((e) => inRegion(e, state.region))), all = pts(inWindow);
    const use = mine.length ? mine : all;
    if (use.length) state.map.fitBounds(use, { padding: [30, 30], maxZoom: 12 });
  }
  $("#map-note").textContent = `על המפה ${shown} מתוך ${inWindow.length} אירועים ${hours === 24 ? "מהיממה האחרונה" : "מ-48 השעות האחרונות"}. עיגול מקווקו = מיקום משוער. ` +
    "אירועים ללא מיקום מזוהה מופיעים בפיד בלבד.";
  setTimeout(() => state.map.invalidateSize(), 50);
}

/* ---------- המעקב שלי (מקומי במכשיר) ---------- */
// אזורים כלליים (זהים ל-AREAS ב-app/gazetteer.py)
const AREAS = [["upper-galilee", "הגליל העליון"], ["golan", "רמת הגולן"], ["western-galilee", "הגליל המערבי ומרכז הגליל"],
  ["lower-galilee", "הגליל התחתון וטבריה"], ["valleys", "העמקים ונצרת"], ["haifa", "חיפה והקריות"],
  ["sharon", "השרון וחדרה"], ["dan", "גוש דן"], ["shfela", "השפלה"], ["jerusalem", "ירושלים והסביבה"],
  ["south", "הדרום"], ["yosh", "יהודה ושומרון"]];
const AREA_NAME = Object.fromEntries(AREAS);
const kmBetween = (a, b, c, d) => {
  const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(x));
};
function ruleLabel(r) {
  const type = r.type ? TYPES[r.type][0] : "כל הסוגים";
  if (r.near) return `${type} · עד ${r.near} ק"מ ממני`;
  if (r.area) return `${type} · ${AREA_NAME[r.area] || r.area}`;
  const old = r.loc && state.locations.find((l) => String(l.id) === r.loc);
  return `${type} · ${old ? old.name_he : "כל הארץ"}`;
}
function getApproxLocation() {
  // מיקום משוער (~1 ק"מ) בזיכרון בלבד; הדפדפן זוכר את ההרשאה, אנחנו לא שומרים את המיקום
  return new Promise((ok, fail) => {
    if (state.gps) return ok(state.gps);
    if (!navigator.geolocation) return fail(new Error("המכשיר לא תומך בזיהוי מיקום"));
    navigator.geolocation.getCurrentPosition((p) => {
      state.gps = { lat: p.coords.latitude.toFixed(2), lon: p.coords.longitude.toFixed(2) }; ok(state.gps);
    }, () => fail(new Error("לא התקבלה הרשאה למיקום")), { enableHighAccuracy: false, maximumAge: 600000, timeout: 10000 });
  });
}
function setupAlerts() {
  $("#a-loc").replaceChildren(el("option", { value: "" }, "כל הארץ"),
    el("option", { value: "near" }, "📍 קרוב אליי"),
    ...AREAS.map(([id, name]) => el("option", { value: id }, name)));
  $("#a-loc").addEventListener("change", () => { $("#a-km-wrap").hidden = $("#a-loc").value !== "near"; });
  $("#a-type").replaceChildren(el("option", { value: "" }, "כל הסוגים"),
    ...Object.entries(TYPES).map(([k, [label]]) => el("option", { value: k }, label)));
  $("#a-add").addEventListener("click", () => {
    const rules = store.get("tl_rules", []);
    const v = $("#a-loc").value, rule = { type: $("#a-type").value };
    if (v === "near") rule.near = Number($("#a-km").value); else if (v) rule.area = v;
    const same = (a, b) => a.type === b.type && (a.near || 0) === (b.near || 0) && (a.area || "") === (b.area || "") && !a.loc;
    if (!rules.some((r) => same(r, rule))) rules.push(rule);
    store.set("tl_rules", rules); drawAlerts();
  });
}
async function drawAlerts() {
  const rules = store.get("tl_rules", []);
  $("#a-rules").replaceChildren(...rules.map((r, i) => el("li", {}, ruleLabel(r),
    el("button", { class: "btn ghost small", onclick: () => { rules.splice(i, 1); store.set("tl_rules", rules); drawAlerts(); } }, "הסרה"))));
  if (!rules.length) { renderFeed($("#a-feed"), [], "עדיין לא הוגדרו כללים."); return; }
  try {
    const events = await fetchEvents({ hours: 24 });
    let me = null, note = "";
    if (rules.some((r) => r.near)) {
      try { me = await getApproxLocation(); } catch (err) { note = ` (${err.message} – כללי "קרוב אליי" לא נבדקו)`; }
    }
    const match = (r, e) => {
      if (r.type && r.type !== e.event_type) return false;
      if (r.near) {
        const l = e.location;
        return !!(me && l && l.lat !== null && kmBetween(+me.lat, +me.lon, l.lat, l.lon) <= r.near);
      }
      if (r.area) return (e.areas || []).includes(r.area);
      return !r.loc || String(e.location?.id) === r.loc;          // כלל ישן לפי מקום מסוים
    };
    const hit = events.filter((e) => rules.some((r) => match(r, e)));
    renderFeed($("#a-feed"), hit, "אין אירועים תואמים ב-24 השעות האחרונות." + note);
  } catch (e) { renderFeed($("#a-feed"), [], "לא ניתן לטעון: " + e.message); }
}

/* ---------- התראות לטלפון (Web Push דרך push.ilradar.stream) ---------- */
const PUSH_API = "https://push.ilradar.stream";
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window
  && location.protocol === "https:";
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
function keyBytes(b64) {
  const s = atob(b64.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((b64.length + 3) % 4));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
async function pushCall(path, body) {
  const res = await fetch(PUSH_API + path, body ? { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "שירות ההתראות לא זמין כרגע");
  return data;
}
async function currentSub() {
  if (!pushSupported()) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? reg.pushManager.getSubscription() : null;
}
function pushStatus(text, active) {
  $("#p-status").textContent = text;
  $("#p-on").textContent = active ? "שמירת שינויים" : "הפעלת התראות";
  $("#p-test").hidden = !active; $("#p-off").hidden = !active;
}
function pushPrefsLabel(p) {
  const where = p.where === "near" ? `עד ${p.km} ק"מ ממך` : p.where ? REGION_NAME[p.where] : "כל הארץ";
  return `${where} · ${p.sev === 2 ? "בינוניים וקריטיים" : "רק קריטיים"}`;
}
async function setupPush() {
  $("#p-where").replaceChildren(el("option", { value: "" }, "כל הארץ"), el("option", { value: "near" }, "📍 קרוב אליי"),
    ...REGIONS.map(([id, name]) => el("option", { value: id }, name)));
  const saved = store.get("tl_push", { where: state.region || "", km: 10, sev: 3 });
  $("#p-where").value = saved.where; $("#p-km").value = String(saved.km); $("#p-sev").value = String(saved.sev);
  $("#p-km-wrap").hidden = saved.where !== "near";
  $("#p-where").addEventListener("change", () => { $("#p-km-wrap").hidden = $("#p-where").value !== "near"; });

  if (!pushSupported()) {
    $("#p-on").disabled = true;
    pushStatus(isIOS() && !isStandalone()
      ? "באייפון: קודם מוסיפים את האפליקציה למסך הבית (בספארי: כפתור השיתוף ← \"הוספה למסך הבית\"), ואז פותחים אותה משם ומפעילים כאן."
      : "הדפדפן הזה לא תומך בהתראות. נסו בכרום או בספארי עדכני.", false);
    return;
  }
  const sub = await currentSub().catch(() => null);
  if (sub && Notification.permission === "granted") pushStatus("✓ ההתראות פעילות: " + pushPrefsLabel(saved), true);
  else if (Notification.permission === "denied") pushStatus("ההתראות חסומות בהגדרות הדפדפן לאתר הזה. כדי להפעיל: הגדרות האתר ← התראות ← לאפשר.", false);

  $("#p-on").addEventListener("click", async () => {
    const btn = $("#p-on"); btn.disabled = true;
    try {
      const prefs = { where: $("#p-where").value, km: Number($("#p-km").value), sev: Number($("#p-sev").value) };
      pushStatus("מפעיל…", false);
      if ((await Notification.requestPermission()) !== "granted") throw new Error("לא אושרו התראות. אפשר לאשר בהגדרות האתר בדפדפן.");
      const reg = await navigator.serviceWorker.ready;
      let s = await reg.pushManager.getSubscription();
      if (!s) {
        const { publicKey } = await pushCall("/vapid");
        s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) });
      }
      const body = { subscription: s.toJSON(), prefs: { minSev: prefs.sev } };
      if (prefs.where === "near") {
        const me = await getApproxLocation();
        Object.assign(body.prefs, { mode: "near", lat: +me.lat, lon: +me.lon, km: prefs.km });
      } else Object.assign(body.prefs, { mode: "regions", regions: prefs.where ? [prefs.where] : [] });
      await pushCall("/subscribe", body);
      store.set("tl_push", prefs);
      pushStatus("✓ ההתראות פעילות: " + pushPrefsLabel(prefs) + (prefs.where === "near" ? ". המיקום נקבע עכשיו – אם עברת מקום, לחצו שוב \"שמירת שינויים\"." : ""), true);
    } catch (err) {
      const s = await currentSub().catch(() => null);
      pushStatus("לא הצלחנו להפעיל: " + err.message, !!s);
    } finally { btn.disabled = false; }
  });
  $("#p-test").addEventListener("click", async () => {
    try {
      const s = await currentSub();
      if (!s) throw new Error("ההתראות לא פעילות במכשיר הזה");
      const r = await pushCall("/test", { endpoint: s.endpoint });
      $("#p-status").textContent = r.ok ? "נשלחה התראת ניסיון – היא אמורה להופיע תוך כמה שניות." : "השליחה נכשלה. נסו לכבות ולהפעיל מחדש.";
    } catch (err) { $("#p-status").textContent = err.message; }
  });
  $("#p-off").addEventListener("click", async () => {
    try {
      const s = await currentSub();
      if (s) { await pushCall("/unsubscribe", { endpoint: s.endpoint }).catch(() => {}); await s.unsubscribe(); }
      pushStatus("ההתראות כובו.", false);
    } catch (err) { $("#p-status").textContent = err.message; }
  });
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

/* ---------- הצעות של סוכן המקורות ---------- */
const pct = (x) => (x === null || x === undefined ? "—" : Math.round(x * 100) + "%");
function candidateCard(c) {
  const rec = c.verdict === "recommended";
  const regions = Object.entries(c.regions || {}).sort((a, b) => b[1] - a[1]).map(([r]) => REGION_NAME[r]).filter(Boolean);
  return el("article", { class: "card src" + (c.verdict === "unsuitable" ? " ended" : "") },
    el("div", { class: "card-head" },
      el("span", { class: "tag " + (rec ? "st-ingesting" : c.verdict === "possible" ? "single_source" : "") },
        rec ? "מומלץ לבדיקה" : c.verdict === "possible" ? "אפשרי" : "לא מתאים"),
      c.verified && el("span", { class: "tag official" }, "מאומת בטלגרם")),
    el("h3", {}, c.title || c.username),
    el("p", { class: "note" }, c.reason + "."),
    el("dl", { class: "times" },
      el("dt", {}, c.kind === "rss" ? "אתר" : "קישור"), el("dd", {}, el("a", { href: c.url, target: "_blank", rel: "noopener noreferrer", dir: "ltr" },
        c.kind === "rss" ? c.username : "t.me/" + c.username)),
      el("dt", {}, "דיווחים מתוך ההודעות"), el("dd", {}, `${pct(c.report_share)} (בצפון: ${pct(c.north_share)})`),
      regions.length && el("dt", {}, "אזורים"), regions.length && el("dd", {}, regions.join(", ")),
      el("dt", {}, "מנויים"), el("dd", { dir: "ltr" }, c.subscribers ? String(c.subscribers) : "—"),
      el("dt", {}, "הודעה אחרונה"), el("dd", {}, c.newest ? ago(c.newest) : "—"),
      el("dt", {}, "הוזכר אצל"), el("dd", {}, (c.mentioned_by || []).join(", "))),
    ...(c.samples || []).map((t) => el("blockquote", { class: "sample" }, t)));
}

async function loadCandidates() {
  const box = $("#candidates");
  let d;
  try { d = await getData("candidates"); } catch { box.replaceChildren(); return; }
  const good = d.candidates.filter((c) => c.verdict !== "unsuitable"), bad = d.candidates.filter((c) => c.verdict === "unsuitable");
  box.replaceChildren(
    el("h3", {}, "מקורות שהסוכן מציע"),
    el("p", { class: "note" }, `הסוכן רץ ${ago(d.generated_at)}: בדק ${d.checked} ערוצי טלגרם` +
      (d.sites_checked ? ` ו-${d.sites_checked} אתרים` : "") + ". " +
      "מקור נכנס לאיסוף רק אחרי שתאשר אותו. לאישור: בקש מ-Claude לעבור על ההצעות."),
    ...(good.length ? good.map(candidateCard) : [el("p", { class: "empty" }, "אין כרגע הצעות מתאימות.")]),
    bad.length && el("details", { class: "archive" }, el("summary", {}, `נבדקו ולא מתאימים (${bad.length})`), ...bad.map(candidateCard)));
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
    loadCandidates();
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
  for (const v of ["feed", "summary", "map", "alerts", "admin"]) $("#view-" + v).hidden = v !== view;
  if (view !== "feed") window.scrollTo(0, 0);      // לא להשאיר את המסך החדש גלול למטה
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === view));
  if (view === "map") drawMap();
  if (view === "alerts") drawAlerts();
  if (view === "admin") {
    if (STATIC) loadSourcesReadOnly();
    else if (sessionStorage.getItem("tl_admin")) loadSources();
  }
}

/* ---------- בחירת אזור (בלי GPS) ---------- */
function setupRegion() {
  // הפיד מציג את כל הארץ. אזור אישי ו"קרוב אליי" קבוע נמצאים ב"המעקב שלי"
  state.region = "";
  const dlg = $("#region-dialog"), btn = $("#region-btn");
  const label = () => { btn.textContent = state.region ? `האזור שלי: ${REGION_NAME[state.region]} · שינוי` : "כל הארץ · בחירת אזור"; };
  const pick = (r) => { state.region = r; store.set("tl_region", r); label(); dlg.close(); loadEvents(); };
  $("#region-list").replaceChildren(
    ...REGIONS.map(([id, name]) => el("button", { type: "button", class: "region-opt", onclick: () => pick(id) }, name)),
    el("button", { type: "button", class: "region-opt all", onclick: () => pick("") }, "כל הארץ, בלי אזור מועדף"));
  btn.hidden = true;
}

/* ---------- התקנה כאפליקציה ---------- */
function setupInstall() {
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  }
  const btn = $("#install-btn");
  if (!btn) return;
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (standalone) return;                                   // כבר מותקן
  let prompt = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); prompt = e; btn.hidden = false; });
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  if (ios) btn.hidden = false;                              // באייפון אין חלון התקנה – מציגים הסבר
  btn.addEventListener("click", async () => {
    if (prompt) { prompt.prompt(); await prompt.userChoice; prompt = null; btn.hidden = true; return; }
    $("#install-help").hidden = !$("#install-help").hidden;
  });
}

function setupTheme() {
  const apply = (t) => { document.documentElement.dataset.theme = t; };
  apply(store.get("tl_theme", "dark"));       // חדר מצב כהה כברירת מחדל
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
  setupRegion(); setupFilters(); setupAlerts(); setupAdmin(); setupInstall(); setupPush().catch(() => {});
  // טווח הזמן על המפה: כפתורים שצפים על המפה עצמה, כך שהם תמיד גלויים
  state.mapHours = Number(store.get("tl_maphours", 24));
  const hb = document.querySelectorAll("#map-hours-box button");
  const markHours = () => hb.forEach((b) => { const on = Number(b.dataset.h) === state.mapHours;
    b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  hb.forEach((b) => b.addEventListener("click", () => {
    state.mapHours = Number(b.dataset.h); store.set("tl_maphours", state.mapHours); markHours(); state.map && drawMap(); }));
  markHours();
  await loadEvents();
  setInterval(() => { if (!document.hidden) loadEvents(); }, 60000);
}
start();
