// איזה אירוע שולחים למי. בלי תלות ב-Cloudflare, כדי שאפשר יהיה לבדוק ב-Node.

export const REGIONS = ["galil-elyon", "galil-maaravi", "kineret-amakim", "haifa", "sharon", "dan", "shfela",
  "jerusalem", "south", "yosh"];
export const KMS = [2, 5, 10, 25, 50];
const NATIONAL = "כל הארץ";
export const FRESH_MS = 2 * 3600 * 1000;      // מתריעים רק על אירוע שדווח לראשונה בשעתיים האחרונות

export const TYPES = {
  security: ["ביטחון", "🛡️"], accident: ["תאונה", "🚗"], fire: ["שריפה", "🔥"], closure: ["חסימה", "🚧"],
  infrastructure: ["תשתיות", "⚡"], weather: ["מזג אוויר", "🌧️"], hazard: ["מפגע", "⚠️"], medical: ["רפואי", "🚑"],
  earthquake: ["רעידת אדמה", "〰️"], cyber: ["סייבר", "🔒"], health: ["בריאות הציבור", "⚕️"], other: ["אחר", "📌"],
};
const SEV = { 3: "קריטי", 2: "בינוני", 1: "נמוך" };

/** מזהה קבוע לאירוע. מזהה המספרי באתר משתנה בכל הרצה, ולכן לא משתמשים בו. */
export function eventKey(e) {
  const place = (e.location && e.location.name) || (e.places || [])[0] || "";
  return `${e.event_type}|${place}|${e.first_reported_at}`;
}

export function isNational(e) {
  return (e.places || []).includes(NATIONAL) || (e.regions || []).length >= REGIONS.length;
}

function km(lat1, lon1, lat2, lon2) {
  const R = 6371, r = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * r / 2) ** 2 +
    Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/** האם האירוע ראוי להתראה בכלל (לא הדגמה, לא הסתיים, חדש) */
export function eligible(e, now = Date.now()) {
  if (!e || e.is_demo || e.status === "ended" || e.verification === "retracted") return false;
  const t = Date.parse(e.first_reported_at);
  return Number.isFinite(t) && now - t <= FRESH_MS;
}

/** האם האירוע מתאים להעדפות של מנוי אחד (בלי בדיקת חומרה) */
export function inArea(sub, e) {
  if (isNational(e)) return (e.severity || 1) >= 3;            // אירוע ארצי – רק כשהוא קריטי
  if (sub.m === "near") {
    const l = e.location;
    if (!l || typeof l.lat !== "number" || typeof l.lon !== "number") return false;
    return km(sub.la, sub.lo, l.lat, l.lon) <= sub.km;
  }
  if (!sub.r || !sub.r.length) return true;                     // כל הארץ
  return (e.regions || []).some((r) => sub.r.includes(r));
}

/**
 * מי צריך לקבל מה. sent = { [eventKey]: החומרה הגבוהה שכבר נשלחה עליה התראה }.
 * מנוי מקבל התראה כשהאירוע הגיע לחומרה שהוא בחר ועוד לא הגיע אליה קודם.
 * מחזיר { plan: [{ sub, events }], sent: מצב מעודכן }
 */
export function plan(events, subs, sent, now = Date.now()) {
  const fresh = events.filter((e) => eligible(e, now));
  const next = { ...sent };
  const out = [];
  for (const sub of subs) {
    const evs = fresh.filter((e) => {
      const sev = e.severity || 1, prev = sent[eventKey(e)] || 0;
      return sev >= sub.v && prev < sub.v && inArea(sub, e);
    }).sort((a, b) => (b.severity || 1) - (a.severity || 1) || Date.parse(b.updated_at) - Date.parse(a.updated_at));
    if (evs.length) out.push({ sub, events: evs });
  }
  for (const e of fresh) {
    const k = eventKey(e);
    next[k] = Math.max(next[k] || 0, e.severity || 1);
  }
  return { plan: out, sent: next };
}

/** מוחק מהמצב אירועים ישנים, כדי שהוא לא יגדל לנצח */
export function prune(sent, events) {
  const keep = new Set(events.map(eventKey));
  const out = {};
  for (const [k, v] of Object.entries(sent)) if (keep.has(k)) out[k] = v;
  return out;
}

/** תוכן ההתראה שמוצג בטלפון */
export function message(events, site) {
  const e = events[0];
  const [type, icon] = TYPES[e.event_type] || TYPES.other;
  const place = (e.location && e.location.name) || (e.places || [])[0] || "";
  const sev = SEV[e.severity || 1];
  const title = `${e.severity >= 3 ? "🔴" : "🟠"} ${icon} ${type}${place ? " · " + place : ""} · ${sev}`;
  let body = (e.title || e.summary || "").trim();
  if (body.length > 140) body = body.slice(0, 139) + "…";
  if (e.verification === "single_source") body += "\n(דיווח ראשוני ממקור אחד, לא מאומת)";
  if (events.length > 1) body += `\n+ עוד ${events.length - 1} אירועים באזור שלך`;
  return { title, body, url: site, tag: events.length > 1 ? "ilradar-multi" : eventKey(e).slice(0, 60) };
}
