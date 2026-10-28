/** Форматирование для рецептов: время, количества, склонения. */

export function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

export function formatMinutes(total: number | null | undefined): string | null {
  if (total === null || total === undefined) return null;
  if (total < 60) return `${total} мин`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} ч ${m} мин` : `${h} ч`;
}

export function formatServings(n: number) {
  return `${n} ${plural(n, "порция", "порции", "порций")}`;
}

const FRACTIONS: [number, string][] = [
  [0.25, "¼"],
  [0.333, "⅓"],
  [0.5, "½"],
  [0.667, "⅔"],
  [0.75, "¾"],
];

/** Красиво выводит количество: 1.5 → «1½» для штук/ложек, 152.3 → «150» для граммов. */
export function formatAmount(value: number | null, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "";
  const u = unit.toLowerCase();
  const isMass = ["г", "мл", "гр"].includes(u);

  if (isMass) {
    // Граммы и миллилитры — округляем до «кухонной» точности
    const rounded = value >= 100 ? Math.round(value / 5) * 5 : value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
    return String(rounded).replace(".", ",");
  }

  const whole = Math.floor(value);
  const frac = value - whole;
  if (frac < 0.05) return String(whole);
  if (frac > 0.95) return String(whole + 1);
  const match = FRACTIONS.find(([f]) => Math.abs(frac - f) < 0.06);
  if (match && value < 10) return `${whole || ""}${match[1]}`;
  return String(Math.round(value * 100) / 100).replace(".", ",");
}

export const DIFFICULTY = ["", "Легко", "Средне", "Сложно"] as const;

export const UNITS = ["г", "кг", "мл", "л", "шт", "ч. л.", "ст. л.", "стакан", "щепотка", "зубчик", "пучок", "по вкусу"];
