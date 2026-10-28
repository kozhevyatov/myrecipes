/* Service worker «Мои рецепты».
 * - Оболочка приложения (HTML) — сначала сеть, без сети — кэш.
 * - Собранные файлы /assets/* (имена с хешем), иконки и фото /api/uploads/* — сначала кэш.
 * - Чтение данных (рецепты, справочники, списки покупок) — сначала сеть, без сети — последняя
 *   сохранённая копия. Так избранные рецепты открываются на даче без интернета.
 * - Авторизация, админка, бэкап и любые изменения (POST/PATCH/DELETE) не кэшируются.
 */
const VERSION = "v5";
const SHELL = `shell-${VERSION}`;
const STATIC = `static-${VERSION}`;
const PHOTOS = "photos-v1";
const API = "api-v1";
// Копия списка избранного — показываем её вместо любого списка рецептов, если сети нет
const FAVORITES_KEY = "/api/__offline/favorites";

const OFFLINE_API = [
  /^\/api\/recipes$/,
  /^\/api\/recipes\/\d+$/,
  /^\/api\/(settings|categories|tags|products)$/,
  /^\/api\/setup\/status$/,
  /^\/api\/shopping\/lists$/,
  /^\/api\/shopping\/lists\/\d+\/items$/,
  /^\/api\/plan$/,
  /^\/api\/plan\/owners$/,
  /^\/api\/pantry$/,
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.json", "/favicon.svg"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  const keep = [SHELL, STATIC, PHOTOS, API];
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !keep.includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cache, maxEntries) {
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - maxEntries; i++) await cache.delete(keys[i]);
}

async function cacheFirst(request, cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) {
    await cache.put(request, response.clone());
    if (maxEntries) trim(cache, maxEntries);
  }
  return response;
}

async function networkFirstShell(request) {
  const cache = await caches.open(SHELL);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put("/", response.clone());
    return response;
  } catch {
    return (await cache.match("/")) || Response.error();
  }
}

async function networkFirstApi(request, url) {
  const cache = await caches.open(API);
  const key = url.pathname + url.search;
  try {
    const response = await fetch(request);
    if (response.ok) {
      await cache.put(key, response.clone());
      if (url.pathname === "/api/recipes" && url.searchParams.get("favorites") === "true") {
        await cache.put(FAVORITES_KEY, response.clone());
      }
      trim(cache, 500);
    }
    return response;
  } catch {
    // Любой список рецептов без сети — показываем избранное: именно эти рецепты сохранены целиком
    if (url.pathname === "/api/recipes") {
      const fav = await cache.match(FAVORITES_KEY);
      if (fav) return fav;
    }
    return (await cache.match(key)) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/uploads/")) {
    event.respondWith(cacheFirst(request, PHOTOS, 600));
  } else if (url.pathname.startsWith("/api/")) {
    if (OFFLINE_API.some((re) => re.test(url.pathname))) event.respondWith(networkFirstApi(request, url));
    // остальное API — только из сети
  } else if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request, STATIC));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirstShell(request));
  }
});

// Выход из аккаунта: стираем сохранённые данные с устройства
self.addEventListener("message", (event) => {
  if (event.data === "clear-user-data") {
    event.waitUntil(Promise.all([caches.delete(API), caches.delete(PHOTOS)]));
  }
});
