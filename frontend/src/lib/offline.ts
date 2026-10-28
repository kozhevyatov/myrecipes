/**
 * Избранные рецепты — без интернета.
 * Пока есть связь, скачиваем избранное: сам рецепт и фото. Service worker кладёт ответы
 * в кэш, а без сети отдаёт сохранённую копию.
 */
import { useEffect, useState } from "react";
import { api } from "./api";
import { clearQueue } from "./shoppingQueue";

const IDS_KEY = "offline-recipes";
const SYNC_KEY = "offline-synced-at";
const SYNC_EVERY = 10 * 60 * 1000;

function readIds(): Set<number> {
  try {
    return new Set(JSON.parse(localStorage.getItem(IDS_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function writeIds(ids: Set<number>) {
  try {
    localStorage.setItem(IDS_KEY, JSON.stringify([...ids]));
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event("offline-recipes"));
}

const supported = () => typeof navigator !== "undefined" && "serviceWorker" in navigator && !!navigator.serviceWorker.controller;

/** Скачать один рецепт и его фото (после добавления в избранное). */
export async function saveRecipeOffline(id: number) {
  if (!supported() || !navigator.onLine) return;
  try {
    const r = await api.recipes.get(id);
    await Promise.all(
      [r.image_url, r.thumb_url, r.author.avatar_url]
        .filter(Boolean)
        .map((u) => fetch(u!).catch(() => undefined)),
    );
    const ids = readIds();
    ids.add(id);
    writeIds(ids);
  } catch {
    /* не страшно — попробуем при следующей синхронизации */
  }
}

/** Синхронизация всего избранного. Не чаще раза в 10 минут, если не попросили принудительно. */
export async function syncFavoritesOffline(force = false) {
  if (!supported() || !navigator.onLine) return;
  try {
    const last = Number(localStorage.getItem(SYNC_KEY) || 0);
    if (!force && Date.now() - last < SYNC_EVERY) return;
    localStorage.setItem(SYNC_KEY, String(Date.now()));
  } catch {
    /* ignore */
  }
  try {
    // Этот запрос SW запомнит как «список избранного» для показа без сети
    const fav = await api.recipes.list({ favorites: true, limit: 100 });
    // Справочники для фильтров на главной
    await Promise.all([api.catalog.categories(), api.catalog.tags(), api.settings.get()].map((p) => p.catch(() => undefined)));
    // Списки покупок — свои и общие, со всеми пунктами
    try {
      const lists = await api.shopping.lists();
      await Promise.all(lists.map((l) => api.shopping.items(l.id).catch(() => undefined)));
    } catch {
      /* ignore */
    }
    const ids = new Set<number>();
    for (const item of fav.items) {
      await saveRecipeOffline(item.id);
      ids.add(item.id);
    }
    writeIds(ids);
  } catch {
    /* ignore */
  }
}

/** Выход: стереть сохранённое с устройства. */
export async function clearOfflineData() {
  try {
    localStorage.removeItem(IDS_KEY);
    localStorage.removeItem(SYNC_KEY);
    clearQueue();
  } catch {
    /* ignore */
  }
  try {
    navigator.serviceWorker?.controller?.postMessage("clear-user-data");
    await Promise.all(["api-v1", "photos-v1"].map((k) => caches.delete(k)));
  } catch {
    /* ignore */
  }
}

export function useOnline() {
  const [online, setOnline] = useState(() => (typeof navigator === "undefined" ? true : navigator.onLine));
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

export function useOfflineIds() {
  const [ids, setIds] = useState(readIds);
  useEffect(() => {
    const update = () => setIds(readIds());
    window.addEventListener("offline-recipes", update);
    return () => window.removeEventListener("offline-recipes", update);
  }, []);
  return ids;
}
