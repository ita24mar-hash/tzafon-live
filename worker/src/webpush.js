// שליחת Web Push לפי התקן (RFC 8291 הצפנה, RFC 8292 VAPID) – רק עם WebCrypto, בלי ספריות.
// עובד גם ב-Cloudflare Workers וגם ב-Node 20+ (לבדיקות).

const enc = new TextEncoder();

export function b64u(buf) {
  const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function unb64u(s) {
  const t = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(t + "===".slice((t.length + 3) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function concat(...parts) {
  const n = parts.reduce((a, p) => a + p.length, 0);
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, data));
}

/** מפתחות VAPID חדשים. מחזיר { publicKey (base64url, 65 בתים), privateJwk } */
export async function generateVapid() {
  const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const pub = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  const privateJwk = await crypto.subtle.exportKey("jwk", kp.privateKey);
  return { publicKey: b64u(pub), privateJwk };
}

/** כותרת Authorization של VAPID לשרת ההתראות שבכתובת endpoint */
export async function vapidHeader(endpoint, vapid, subject) {
  const aud = new URL(endpoint).origin;
  const header = b64u(enc.encode(JSON.stringify({ typ: "JWT", alg: "ES256" })));
  const exp = Math.floor(Date.now() / 1000) + 12 * 3600;
  const payload = b64u(enc.encode(JSON.stringify({ aud, exp, sub: subject })));
  const key = await crypto.subtle.importKey("jwk", vapid.privateJwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(`${header}.${payload}`));
  return `vapid t=${header}.${payload}.${b64u(sig)}, k=${vapid.publicKey}`;
}

/** הצפנת התוכן לפי aes128gcm. p256dh ו-auth כפי שהדפדפן מסר (base64url). */
export async function encryptPayload(plaintext, p256dh, auth, salt = crypto.getRandomValues(new Uint8Array(16))) {
  const uaPub = unb64u(p256dh);
  const authSecret = unb64u(auth);
  const as = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const asPub = new Uint8Array(await crypto.subtle.exportKey("raw", as.publicKey));
  const uaKey = await crypto.subtle.importKey("raw", uaPub, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: "ECDH", public: uaKey }, as.privateKey, 256));

  const prkKey = await hmac(authSecret, shared);
  const keyInfo = concat(enc.encode("WebPush: info\0"), uaPub, asPub, new Uint8Array([1]));
  const ikm = await hmac(prkKey, keyInfo);
  const prk = await hmac(salt, ikm);
  const cek = (await hmac(prk, concat(enc.encode("Content-Encoding: aes128gcm\0"), new Uint8Array([1])))).slice(0, 16);
  const nonce = (await hmac(prk, concat(enc.encode("Content-Encoding: nonce\0"), new Uint8Array([1])))).slice(0, 12);

  const body = concat(enc.encode(plaintext), new Uint8Array([2]));    // 2 = הרשומה האחרונה
  const aes = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, aes, body));

  const rs = new Uint8Array([0, 0, 16, 0]);                           // 4096
  return concat(salt, rs, new Uint8Array([asPub.length]), asPub, ct);
}

/** שולח התראה אחת. מחזיר את קוד התשובה של שרת ההתראות (201 = נשלח, 404/410 = המנוי כבר לא קיים). */
export async function sendPush(sub, payload, vapid, subject, { ttl = 3600, urgency = "high", topic } = {}) {
  const body = await encryptPayload(JSON.stringify(payload), sub.p256dh, sub.auth);
  const headers = {
    "Content-Encoding": "aes128gcm",
    "Content-Type": "application/octet-stream",
    TTL: String(ttl),
    Urgency: urgency,
    Authorization: await vapidHeader(sub.endpoint, vapid, subject),
  };
  if (topic) headers.Topic = topic;
  const res = await fetch(sub.endpoint, { method: "POST", headers, body });
  return res.status;
}
