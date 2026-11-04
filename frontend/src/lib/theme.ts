import { useEffect, useState } from "react";

/** Темы оформления. dark — признак тёмной гаммы (класс .dark на <html>), cls — свой класс палитры. */
export const THEMES = [
  { id: "light", label: "Крем", hint: "светлая, терракота", dark: false, cls: "", meta: "#faf7f2", bg: "#faf7f2", accent: "#c8603a" },
  { id: "blueberry", label: "Голубика", hint: "светлая, холодная", dark: false, cls: "theme-blueberry", meta: "#f5f7fc", bg: "#f5f7fc", accent: "#4d5bc4" },
  { id: "rosemary", label: "Розмарин", hint: "светлая, тёмно-зелёная", dark: false, cls: "theme-rosemary", meta: "#f7f8f3", bg: "#f7f8f3", accent: "#2f6b4a" },
  { id: "dark", label: "Уголь", hint: "тёмная, терракота", dark: true, cls: "", meta: "#1c1917", bg: "#1f1a17", accent: "#e07a4f" },
  { id: "plum", label: "Слива", hint: "тёмная, ягодная", dark: true, cls: "theme-plum", meta: "#221720", bg: "#221720", accent: "#e8739a" },
  { id: "basil", label: "Базилик", hint: "тёмная, хвойная", dark: true, cls: "theme-basil", meta: "#141d18", bg: "#141d18", accent: "#7cc79a" },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];
const CLASSES = THEMES.map((t) => t.cls).filter(Boolean);

function current(): ThemeId {
  const el = document.documentElement;
  const byClass = THEMES.find((t) => t.cls && el.classList.contains(t.cls));
  if (byClass) return byClass.id;
  return el.classList.contains("dark") ? "dark" : "light";
}

export function applyTheme(id: ThemeId) {
  const t = THEMES.find((x) => x.id === id) ?? THEMES[0];
  const el = document.documentElement;
  el.classList.remove(...CLASSES);
  if (t.cls) el.classList.add(t.cls);
  el.classList.toggle("dark", t.dark);
  el.style.colorScheme = t.dark ? "dark" : "light";
  // Цвет строки состояния / панели браузера под тему
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.remove());
  const meta = document.createElement("meta");
  meta.name = "theme-color";
  meta.content = t.meta;
  document.head.appendChild(meta);
}

export function useTheme() {
  const [theme, setTheme] = useState<ThemeId>(current);

  useEffect(() => {
    applyTheme(theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* приватный режим — не страшно */
    }
  }, [theme]);

  return { theme, setTheme, info: THEMES.find((t) => t.id === theme) ?? THEMES[0] };
}
