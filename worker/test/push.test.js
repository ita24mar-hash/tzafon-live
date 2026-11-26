// בדיקות: הצפנה (מפענחים בצד "הדפדפן" לפי התקן), חתימת VAPID, והתאמת אירועים למנויים.
import { test } from "node:test";
import assert from "node:assert/strict";
import { encryptPayload, generateVapid, vapidHeader, b64u, unb64u } from "../src/webpush.js";
import { plan, prune, message, eventKey, inArea } from "../src/match.js";

const enc = new TextEncoder();
async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, data));
}
const cat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let i = 0; for (const x of a) { o.set(x, i); i += x.length; } return o; };

test("הצפנה לפי RFC 8291 – הדפדפן מצליח לפענח", async () => {
  const ua = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const uaPub = new Uint8Array(await crypto.subtle.exportKey("raw", ua.publicKey));
  const auth = crypto.getRandomValues(new Uint8Array(16));
  const msg = JSON.stringify({ title: "שריפה · כרמיאל", body: "בדיקה" });
  const blob = await encryptPayload(msg, b64u(uaPub), b64u(auth));

  const salt = blob.slice(0, 16), idlen = blob[20], asPub = blob.slice(21, 21 + idlen), ct = blob.slice(21 + idlen);
  assert.equal(new DataView(blob.buffer, blob.byteOffset + 16, 4).getUint32(0), 4096);
  const asKey = await crypto.subtle.importKey("raw", asPub, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: asKey }, ua.privateKey, 256));
  const ikm = await hmac(await hmac(auth, shared), cat(enc.encode("WebPush: info\0"), uaPub, asPub, new Uint8Array([1])));
  const prk = await hmac(salt, ikm);
  const cek = (await hmac(prk, cat(enc.encode("Content-Encoding: aes128gcm\0"), new Uint8Array([1])))).slice(0, 16);
  const nonce = (await hmac(prk, cat(enc.encode("Content-Encoding: nonce\0"), new Uint8Array([1])))).slice(0, 12);
  const k = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["decrypt"]);
  const pt = new Uint8Array(await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, k, ct));
  assert.equal(pt[pt.length - 1], 2);
  assert.equal(new TextDecoder().decode(pt.slice(0, -1)), msg);
});

test("חתימת VAPID תקינה", async () => {
  const v = await generateVapid();
  assert.equal(unb64u(v.publicKey).length, 65);
  const h = await vapidHeader("https://fcm.googleapis.com/fcm/send/abc", v, "https://ilradar.stream/");
  const [, jwt] = h.match(/^vapid t=([^,]+), k=/);
  const [hd, pl, sig] = jwt.split(".");
  const claims = JSON.parse(new TextDecoder().decode(unb64u(pl)));
  assert.equal(claims.aud, "https://fcm.googleapis.com");
  const pub = await crypto.subtle.importKey("raw", unb64u(v.publicKey), { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
  assert.ok(await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, pub, unb64u(sig), enc.encode(`${hd}.${pl}`)));
});

const now = Date.parse("2026-11-27T10:00:00Z");
const ev = (o) => ({ event_type: "fire", severity: 3, status: "active", verification: "single_source", is_demo: false,
  first_reported_at: "2026-11-27T09:50:00Z", updated_at: "2026-11-27T09:55:00Z", places: ["כרמיאל"],
  regions: ["galil-maaravi"], location: { name: "כרמיאל", lat: 32.92, lon: 35.30 }, title: "שריפה ליד כרמיאל", ...o });

test("התאמה לפי אזור, מרחק וחומרה", () => {
  const north = { m: "regions", r: ["galil-maaravi"], v: 3 };
  const south = { m: "regions", r: ["south"], v: 3 };
  const near = { m: "near", la: 32.91, lo: 35.29, km: 5, v: 2 };
  const far = { m: "near", la: 31.25, lo: 34.79, km: 10, v: 2 };
  const all = { m: "regions", r: [], v: 3 };
  assert.ok(inArea(north, ev())); assert.ok(!inArea(south, ev()));
  assert.ok(inArea(near, ev())); assert.ok(!inArea(far, ev())); assert.ok(inArea(all, ev()));
  const nat = ev({ places: ["כל הארץ"], regions: [], location: null });
  assert.ok(inArea(south, nat));
  assert.ok(!inArea(south, { ...nat, severity: 2 }));
});

test("לא שולחים פעמיים, ושולחים כשהחומרה עולה", () => {
  const sub2 = { m: "regions", r: [], v: 2 }, sub3 = { m: "regions", r: [], v: 3 };
  const e2 = ev({ severity: 2 });
  let r = plan([e2], [sub2, sub3], {}, now);
  assert.deepEqual(r.plan.map((p) => p.sub), [sub2]);
  r = plan([e2], [sub2, sub3], r.sent, now);
  assert.equal(r.plan.length, 0);
  r = plan([ev({ severity: 3 })], [sub2, sub3], r.sent, now);
  assert.deepEqual(r.plan.map((p) => p.sub), [sub3]);
});

test("לא שולחים על ישן, הדגמה או אירוע שהסתיים", () => {
  const sub = { m: "regions", r: [], v: 2 };
  const old = ev({ first_reported_at: "2026-11-27T06:00:00Z" });
  assert.equal(plan([old, ev({ is_demo: true }), ev({ status: "ended" })], [sub], {}, now).plan.length, 0);
});

test("ניקוי מצב ותוכן ההודעה", () => {
  const e = ev();
  assert.deepEqual(prune({ [eventKey(e)]: 3, "x|y|z": 2 }, [e]), { [eventKey(e)]: 3 });
  const m = message([e, ev({ event_type: "accident" })], "https://ilradar.stream/");
  assert.match(m.title, /שריפה · כרמיאל · קריטי/);
  assert.match(m.body, /עוד 1 אירועים/);
  assert.match(m.body, /לא מאומת/);
});
