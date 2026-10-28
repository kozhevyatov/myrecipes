/* Service worker «Мои рецепты».
 * - Оболочка приложения (HTML/JS/CSS) — сначала сеть, при отсутствии сети — кэш.
 * - Собранные файлы /assets/* (имена с хешем) и фото /api/uploads/* — сначала кэш.
 * - Остальной /api/* не кэшируется: данные всегда свежие.
 */
const VERSION = "v1";
const SHELL = `shell-${VERSION}`;
const STATIC = `static-${VERSION}`;
const PHOTOS = "photos-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.json", "/favicon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  const keep = [SHELL, STATIC, PHOTOS];
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !keep.includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function cacheFirst(request, cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) {
    cache.put(request, response.clone());
    if (maxEntries) {
      cache.keys().then((keys) => keys.length > maxEntries && cache.delete(keys[0]));
    }
  }
  return response;
}

async function networkFirst(request) {
  const cache = await caches.open(SHELL);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put("/", response.clone());
    return response;
  } catch {
    return (await cache.match("/")) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/uploads/")) {
    event.respondWith(cacheFirst(request, PHOTOS, 300));
  } else if (url.pathname.startsWith("/api/")) {
    return; // данные — только из сети
  } else if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request, STATIC));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
  }
});
