const CACHE = "firecrawlapp-v1";
const SHELL = [
  "/",
  "/style.css",
  "/app.js",
  "/vendor/chart.umd.min.js",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      Promise.all(
        SHELL.map((url) =>
          fetch(url)
            .then((res) => (res.ok ? cache.put(url, res.clone()) : null))
            .catch(() => null)
        )
      ).then(() => self.skipWaiting())
    )
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (req.url.includes("/api/status") || req.url.includes("/api/products")) {
            const clone = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, clone));
          }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req)
          .then((res) => {
            const clone = res.clone();
            caches.open(CACHE).then((cache) => cache.put(req, clone));
            return res;
          })
          .catch(() => (req.mode === "navigate" ? caches.match("/") : undefined))
    )
  );
});
