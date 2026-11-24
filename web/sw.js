// Service worker: מאפשר התקנה כאפליקציה ופתיחה מהירה.
// קבצי האפליקציה נשמרים במטמון; הנתונים (data/*.json) תמיד נטענים מהרשת קודם, כדי שלא יוצג מידע ישן כעדכני.
const SHELL = "shell-v1";
const FILES = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest", "icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;     // מפה, גופנים – ישירות מהרשת
  if (url.pathname.includes("/data/")) {
    // נתונים: רשת בלבד. בלי רשת – הדפדפן יחזיר שגיאה והאפליקציה תציג "אין חיבור" ולא נתונים ישנים
    return;
  }
  // קבצי האפליקציה: רשת קודם (כדי לקבל גרסה חדשה), ואם אין רשת – מהמטמון
  e.respondWith(fetch(e.request).then((res) => {
    const copy = res.clone();
    caches.open(SHELL).then((c) => c.put(e.request, copy));
    return res;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("index.html"))));
});
