/** Даты для меню: локальные дни без часовых поясов (YYYY-MM-DD). */

export function iso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function parseIso(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

/** Понедельник недели, в которую попадает дата. */
export function weekStart(d: Date): Date {
  const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (r.getDay() + 6) % 7; // пн = 0
  return addDays(r, -dow);
}

export const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
export const WEEKDAYS_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];
const MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

export function dayLabel(d: Date): string {
  return `${d.getDate()} ${MONTHS_GEN[d.getMonth()]}`;
}

export function rangeLabel(start: Date, end: Date): string {
  if (start.getMonth() === end.getMonth()) return `${start.getDate()}–${end.getDate()} ${MONTHS_GEN[end.getMonth()]}`;
  return `${dayLabel(start)} – ${dayLabel(end)}`;
}

export function relativeDay(d: Date): string | null {
  const today = new Date();
  const t = iso(today);
  const s = iso(d);
  if (s === t) return "Сегодня";
  if (s === iso(addDays(today, 1))) return "Завтра";
  if (s === iso(addDays(today, -1))) return "Вчера";
  return null;
}

export const SLOTS = [
  { id: "breakfast", label: "Завтрак" },
  { id: "lunch", label: "Обед" },
  { id: "dinner", label: "Ужин" },
  { id: "snack", label: "Перекус" },
] as const;
