import { Link } from "react-router";
import type { Nutrition } from "@/lib/api";
import { plural } from "@/lib/format";

function fmt(n: number) {
  return n >= 10 ? String(Math.round(n)) : String(n).replace(".", ",");
}

/** КБЖУ на порцию. Значения примерные — по справочнику продуктов. */
export function NutritionCard({ nutrition, servings, readOnly }: { nutrition: Nutrition; servings: number; readOnly?: boolean }) {
  const v = nutrition.per_serving;
  const empty = nutrition.counted === 0;

  return (
    <div className="rounded-3xl border bg-card p-5 sm:p-6 print:hidden">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">На порцию</h2>
        {!empty && nutrition.weight_g > 0 && (
          <span className="text-xs text-muted-foreground">
            ≈ {Math.round(nutrition.weight_g / Math.max(servings, 1))} г
          </span>
        )}
      </div>

      {empty ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Для расчёта не хватает данных о продуктах.{" "}
          <Link to="/products" className="font-medium text-primary hover:underline">
            Заполнить в справочнике
          </Link>
        </p>
      ) : (
        <>
          <p className="mt-3 flex items-baseline gap-1.5">
            <span className="title-display text-4xl tabular-nums">{fmt(v.kcal)}</span>
            <span className="text-sm text-muted-foreground">ккал</span>
          </p>
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            {[
              ["Белки", v.protein],
              ["Жиры", v.fat],
              ["Углеводы", v.carbs],
            ].map(([label, value]) => (
              <div key={label as string} className="rounded-2xl bg-muted/70 px-2 py-2.5">
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="mt-0.5 font-semibold tabular-nums">{fmt(value as number)} г</dd>
              </div>
            ))}
          </dl>
        </>
      )}

      {nutrition.missing.length > 0 && !empty && (
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          Без учёта: {nutrition.missing.slice(0, 4).join(", ")}
          {nutrition.missing.length > 4 &&
            ` и ещё ${nutrition.missing.length - 4} ${plural(nutrition.missing.length - 4, "продукт", "продукта", "продуктов")}`}
          .{" "}
          {!readOnly && (
            <Link to={`/products?q=${encodeURIComponent(nutrition.missing[0])}`} className="font-medium text-primary hover:underline">
            Дополнить
          </Link>
          )}
        </p>
      )}
    </div>
  );
}
