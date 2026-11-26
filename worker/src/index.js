// רדאר LIVE – שירות התראות לטלפון (Cloudflare Worker, תוכנית חינמית).
//   GET  /vapid        המפתח הציבורי שהדפדפן צריך כדי להירשם
//   POST /subscribe    הרשמה או עדכון העדפות
//   POST /unsubscribe  ביטול
//   POST /test         התראת ניסיון למכשיר שנרשם
//   כל 5 דקות (cron)   קורא את האירועים מהאתר ושולח התראות למי שמתאים
// מה נשמר: כתובת ההתראות שהדפדפן נתן, והעדפות (אזורים, או מיקום מעוגל לכקילומטר + טווח, וחומרה). בלי שם, טלפון או מייל.

import { generateVapid, sendPush } from "./webpush.js";
import { REGIONS, KMS, plan, prune, message } from "./match.js";

const PUSH_HOSTS = [/^fcm\.googleapis\.com$/, /^updates\.push\.services\.mozilla\.com$/, /(^|\.)push\.apple\.com$/,
  /\.notify\.windows\.com$/];
const MAX_PER_RUN = 3;     // לכל מכשיר: לכל היותר התראה אחת בכל ריצה, שמסכמת עד 3 אירועים

function cors(req, env) {
  const origin = req.headers.get("Origin") || "";
  const ok = env.ALLOWED_ORIGINS.split(",").map((s) => s.trim()).includes(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : env.SITE_URL.replace(/\/$/, ""),
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

const json = (data, status, headers) =>
  new Response(JSON.stringify(data), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8" } });

async function subId(endpoint) {
  const h = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(endpoint)));
  return "s:" + [...h.slice(0, 16)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function getVapid(env) {
  const v = await env.KV.get("vapid", "json");
  if (v) return v;
  const fresh = await generateVapid();
  await env.KV.put("vapid", JSON.stringify(fresh));
  return fresh;
}

/** בדיקת קלט ההרשמה. מחזיר רשומה לשמירה, או מחרוזת שגיאה. */
function validate(body) {
  const s = body && body.subscription;
  if (!s || typeof s.endpoint !== "string" || !s.keys) return "חסרים פרטי מנוי";
  let u;
  try { u = new URL(s.endpoint); } catch { return "כתובת לא תקינה"; }
  if (u.protocol !== "https:" || !PUSH_HOSTS.some((re) => re.test(u.hostname))) return "שירות התראות לא מוכר";
  if (typeof s.keys.p256dh !== "string" || typeof s.keys.auth !== "string") return "חסרים מפתחות";
  const p = body.prefs || {};
  const rec = { e: s.endpoint, p: s.keys.p256dh, a: s.keys.auth, v: p.minSev === 2 ? 2 : 3, t: Date.now() };
  if (p.mode === "near") {
    const la = Math.round(Number(p.lat) * 100) / 100, lo = Math.round(Number(p.lon) * 100) / 100;
    if (!(la > 29 && la < 34) || !(lo > 34 && lo < 36)) return "המיקום מחוץ לישראל";
    if (!KMS.includes(Number(p.km))) return "טווח לא תקין";
    Object.assign(rec, { m: "near", la, lo, km: Number(p.km) });
  } else {
    const r = Array.isArray(p.regions) ? [...new Set(p.regions.filter((x) => REGIONS.includes(x)))] : [];
    Object.assign(rec, { m: "regions", r });
  }
  if (JSON.stringify(rec).length > 1000) return "פרטי המנוי ארוכים מדי";
  return rec;
}

async function listSubs(env) {
  const subs = [];
  let cursor;
  do {
    const page = await env.KV.list({ prefix: "s:", cursor });
    for (const k of page.keys) if (k.metadata) subs.push({ id: k.name, ...k.metadata });
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor);
  return subs.map((s) => ({ ...s, endpoint: s.e, p256dh: s.p, auth: s.a }));
}

async function deliver(env, sub, payload, vapid) {
  try {
    const status = await sendPush(sub, payload, vapid, env.SITE_URL, { urgency: "high", ttl: 3600 });
    if (status === 404 || status === 410) await env.KV.delete(sub.id);   // המכשיר ביטל או הוסר
    return status;
  } catch (err) {
    console.log("push failed", String(err));
    return 0;
  }
}

async function run(env) {
  const res = await fetch(env.EVENTS_URL + "?t=" + Date.now(), { cf: { cacheTtl: 0 }, headers: { "Cache-Control": "no-cache" } });
  if (!res.ok) { console.log("events fetch", res.status); return; }
  const events = await res.json();
  if (!Array.isArray(events)) return;
  const state = await env.KV.get("sent", "json");
  const subs = await listSubs(env);
  const { plan: todo, sent } = plan(events, subs, state || {});
  // בהרצה הראשונה: רק לומדים מה כבר קיים, לא שולחים על אירועים שקרו לפני שהשירות עלה
  if (state) {
    const vapid = await getVapid(env);
    for (const { sub, events: evs } of todo) await deliver(env, sub, message(evs.slice(0, MAX_PER_RUN), env.SITE_URL), vapid);
    if (todo.length) console.log(`sent to ${todo.length} of ${subs.length}`);
  }
  const next = prune(sent, events);
  if (JSON.stringify(next) !== JSON.stringify(state)) await env.KV.put("sent", JSON.stringify(next));
}

export default {
  async fetch(req, env) {
    const h = cors(req, env);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    const path = new URL(req.url).pathname;
    try {
      if (req.method === "GET" && path === "/vapid") return json({ publicKey: (await getVapid(env)).publicKey }, 200, h);
      if (req.method === "GET" && path === "/") return json({ ok: true, service: "ilradar push" }, 200, h);
      if (req.method !== "POST") return json({ error: "not found" }, 404, h);
      const body = await req.json().catch(() => null);
      if (path === "/subscribe") {
        const rec = validate(body);
        if (typeof rec === "string") return json({ error: rec }, 400, h);
        await env.KV.put(await subId(rec.e), "1", { metadata: rec });
        return json({ ok: true }, 200, h);
      }
      if (path === "/unsubscribe") {
        if (!body || typeof body.endpoint !== "string") return json({ error: "חסרה כתובת" }, 400, h);
        await env.KV.delete(await subId(body.endpoint));
        return json({ ok: true }, 200, h);
      }
      if (path === "/test") {
        if (!body || typeof body.endpoint !== "string") return json({ error: "חסרה כתובת" }, 400, h);
        const id = await subId(body.endpoint);
        const { metadata } = await env.KV.getWithMetadata(id);
        if (!metadata) return json({ error: "המכשיר לא רשום" }, 404, h);
        const status = await deliver(env, { id, ...metadata, endpoint: metadata.e, p256dh: metadata.p, auth: metadata.a },
          { title: "🟢 רדאר LIVE · התראת ניסיון", body: "ההתראות פועלות. כך ייראה עדכון על אירוע באזור שלך.", url: env.SITE_URL, tag: "ilradar-test" },
          await getVapid(env));
        return json({ ok: status >= 200 && status < 300, status }, 200, h);
      }
      return json({ error: "not found" }, 404, h);
    } catch (err) {
      console.log("error", String(err));
      return json({ error: "שגיאה בשרת" }, 500, h);
    }
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(run(env));
  },
};
