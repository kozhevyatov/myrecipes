import { useState, type ChangeEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import type { PriceInput, PriceUnit } from "@/lib/api";

export const PRICE_UNITS: PriceUnit[] = ["г", "кг", "мл", "л", "шт"];

const toStr = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v).replace(".", ","));
const toNum = (s: string) => {
  const n = Number(s.trim().replace(",", "."));
  return s.trim() && Number.isFinite(n) && n > 0 ? n : null;
};
const decimal = (set: (v: string) => void) => (e: ChangeEvent<HTMLInputElement>) =>
  set(e.target.value.replace(/[^\d.,]/g, ""));

/** Цена «как на ценнике»: 220 ₽ за 180 г. Поля можно заполнить заранее — прошлой ценой. */
export function PriceForm({
  initial,
  pending,
  onSubmit,
  onCancel,
}: {
  initial?: { price?: number | null; package_amount?: number | null; package_unit?: PriceUnit | null };
  pending?: boolean;
  onSubmit: (data: PriceInput) => void;
  onCancel: () => void;
}) {
  const [price, setPrice] = useState(toStr(initial?.price));
  const [amount, setAmount] = useState(toStr(initial?.package_amount));
  const [unit, setUnit] = useState<PriceUnit>(initial?.package_unit ?? "г");
  const p = toNum(price);
  const a = toNum(amount);

  return (
    <form
      className="flex flex-wrap items-center gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (p && a) onSubmit({ price: p, package_amount: a, package_unit: unit });
      }}
    >
      <Input
        className="h-10 w-24 text-right"
        inputMode="decimal"
        placeholder="Цена"
        value={price}
        onChange={decimal(setPrice)}
        onFocus={(e) => e.target.select()}
        autoFocus
        aria-label="Цена"
      />
      <span>₽ за</span>
      <Input
        className="h-10 w-20 text-right"
        inputMode="decimal"
        placeholder="180"
        value={amount}
        onChange={decimal(setAmount)}
        aria-label="Размер упаковки"
      />
      <div className="w-20">
        <Select className="h-10" value={unit} onChange={(e) => setUnit(e.target.value as PriceUnit)} aria-label="Единица">
          {PRICE_UNITS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
        </Select>
      </div>
      <Button size="sm" type="submit" disabled={!p || !a || pending}>
        Сохранить
      </Button>
      <Button size="sm" variant="ghost" type="button" onClick={onCancel}>
        Отмена
      </Button>
    </form>
  );
}
