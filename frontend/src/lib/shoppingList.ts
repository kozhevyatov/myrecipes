/** Последний выбранный список покупок — запоминаем на устройстве. */
const KEY = "shopping-list";

export function getLastList(): number | null {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

export function setLastList(id: number) {
  try {
    localStorage.setItem(KEY, String(id));
  } catch {
    /* приватный режим */
  }
}
