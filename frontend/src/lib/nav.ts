/**
 * Навигация «Назад» по смыслу, а не по истории браузера.
 *
 * Рецепт → «Назад» ведёт в раздел, откуда пришли (Рецепты с фильтрами, Меню, «Что есть дома»…).
 * Редактирование и режим готовки → «Назад» ведёт на сам рецепт.
 * Если прошлый экран в истории как раз тот, куда ведём, — просто шаг назад (без новых записей
 * в истории); иначе переход с заменой текущей записи. Так не бывает хождения по кругу.
 */
import { useLocation, useNavigate } from "react-router";

const KEY = "nav-section";
// Разделы, в которые возвращаемся из рецепта
const SECTIONS = ["/", "/plan", "/pantry", "/shopping", "/products", "/profile", "/admin"];

const idx = (): number | null => {
  const v = (window.history.state as { idx?: number } | null)?.idx;
  return typeof v === "number" ? v : null;
};

type Saved = { path: string; idx: number | null };

export function isSection(pathname: string) {
  return SECTIONS.includes(pathname);
}

/** Вызывается при каждом переходе: запоминаем последний открытый раздел. */
export function rememberSection(pathname: string, search: string) {
  if (!isSection(pathname)) return;
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ path: pathname + search, idx: idx() } satisfies Saved));
  } catch {
    /* приватный режим */
  }
}

function saved(): Saved | null {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

/** «Назад» со страницы рецепта: в раздел, откуда пришли. */
export function useBackToSection() {
  const navigate = useNavigate();
  return () => {
    const s = saved();
    const current = idx();
    if (s && s.idx !== null && current !== null && current === s.idx + 1) navigate(-1);
    else navigate(s?.path ?? "/", { replace: true });
  };
}

/** Ссылка на дочерний экран рецепта (редактирование, готовка) — помечаем, что пришли с рецепта. */
export const fromRecipe = { fromRecipe: true };

/** «Назад» с дочернего экрана: на рецепт. */
export function useBackToRecipe(recipeId: number | string) {
  const navigate = useNavigate();
  const location = useLocation();
  const cameFromRecipe = Boolean((location.state as { fromRecipe?: boolean } | null)?.fromRecipe);
  return () => {
    if (cameFromRecipe) navigate(-1);
    else navigate(`/recipes/${recipeId}`, { replace: true });
  };
}

/** Путь раздела для перехода после удаления рецепта и т.п. */
export function sectionPath() {
  return saved()?.path ?? "/";
}
