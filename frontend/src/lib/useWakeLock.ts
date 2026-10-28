import { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "keep-screen-on";

function readPref(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * «Не гасить экран» через Screen Wake Lock API.
 * Работает только по HTTPS. Браузер снимает блокировку, когда вкладка скрыта,
 * поэтому при возврате на страницу запрашиваем её заново.
 * В мобильном приложении (Expo) аналог — expo-keep-awake.
 */
export function useWakeLock({ force = false }: { force?: boolean } = {}) {
  const supported = typeof navigator !== "undefined" && "wakeLock" in navigator;
  const [pref, setEnabled] = useState<boolean>(() => supported && readPref());
  // force — режим готовки: экран не гаснет всегда, без оглядки на настройку
  const enabled = force || pref;
  const [active, setActive] = useState(false);
  const sentinel = useRef<WakeLockSentinel | null>(null);

  useEffect(() => {
    if (!supported || !enabled) return;
    let cancelled = false;

    const acquire = async () => {
      if (document.visibilityState !== "visible" || sentinel.current) return;
      try {
        const lock = await navigator.wakeLock.request("screen");
        if (cancelled) {
          lock.release().catch(() => {});
          return;
        }
        sentinel.current = lock;
        setActive(true);
        lock.addEventListener("release", () => {
          sentinel.current = null;
          setActive(false);
        });
      } catch {
        setActive(false); // например, режим энергосбережения
      }
    };

    acquire();
    document.addEventListener("visibilitychange", acquire);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", acquire);
      sentinel.current?.release().catch(() => {});
      sentinel.current = null;
      setActive(false);
    };
  }, [supported, enabled]);

  const toggle = (value: boolean) => {
    setEnabled(value);
    try {
      localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  return { supported, enabled, active, setEnabled: toggle };
}
