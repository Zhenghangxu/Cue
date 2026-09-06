// Bump this version whenever the offline page changes.
const CACHE_NAME = "cue-offline-v2";
const OFFLINE_URL = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.add(new Request(OFFLINE_URL, { cache: "reload" }));
  })());
  // Let open windows finish using their current worker before updating.
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((key) => key.startsWith("cue-offline-") && key !== CACHE_NAME)
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  // Keep API data, credentials, media, and Next.js assets out of Cache Storage.
  if (request.method !== "GET" || request.mode !== "navigate" ||
      url.origin !== self.location.origin ||
      /^\/(?:api|_next)(?:\/|$)/.test(url.pathname)) return;

  event.respondWith((async () => {
    try {
      const response = await fetch(request);
      if (response.status < 500) return response;
    } catch {
      // A stopped local server and an offline browser both use the fallback.
    }
    const cache = await caches.open(CACHE_NAME);
    return await cache.match(OFFLINE_URL) ?? new Response("Cue is unavailable. Start the Cue server and try again.", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  })());
});
