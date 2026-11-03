import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { TrendingDown, TrendingUp } from "lucide-react";
import { api, type CostHistory, type RecipeCost } from "@/lib/api";
import { formatMoney, plural } from "@/lib/format";
import { cn } from "@/lib/utils";

function monthYear(iso: string) {
  return new Date(iso).toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
}

/** Мини-график себестоимости по снимкам. */
function Sparkline({ points }: { points: CostHistory["points"] }) {
  const w = 240;
  const h = 48;
  const values = points.map((p) => p.total);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const t0 = new Date(points[0].taken_at).getTime();
  const t1 = new Date(points[points.length - 1].taken_at).getTime();
  const tspan = t1 - t0 || 1;
  const xy = points.map((p) => {
    const x = ((new Date(p.taken_at).getTime() - t0) / tspan) * (w - 8) + 4;
    const y = h - 4 - ((p.total - min) / span) * (h - 8);
    return [x, y] as const;
  });
  const last = xy[xy.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-12 w-full text-primary" aria-hidden>
      <polyline
        points={xy.map(([x, y]) => `${x},${y}`).join(" ")}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={last[0]} cy={last[1]} r="3.5" fill="currentColor" />
    </svg>
  );
}

function History({ recipeId }: { recipeId: number }) {
  const history = useQuery({ queryKey: ["recipe-cost-history", recipeId], queryFn: () => api.recipes.costHistory(recipeId) });
  const h = history.data;
  if (!h || h.points.length < 2) {
    return (
      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
        История появится, когда изменятся цены. Снимки записываются сами — при новой цене и раз в месяц.
      </p>
    );
  }
  const up = (h.change_pct ?? 0) > 0;
  return (
    <div className="mt-5 border-t pt-4">
      {h.change_pct !== null && h.since && (
        <p className="flex items-center gap-1.5 text-sm">
          {up ? <TrendingUp className="size-4 text-primary" /> : <TrendingDown className="size-4 text-muted-foreground" />}
          <span className={cn("font-semibold tabular-nums", up && "text-primary")}>
            {h.change_pct > 0 ? "+" : ""}
            {String(h.change_pct).replace(".", ",")}%
          </span>
          <span className="text-muted-foreground">с {monthYear(h.since)}</span>
        </p>
      )}
      <Sparkline points={h.points} />
      {h.drivers.length > 0 && (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Подорожало сильнее всего:{" "}
          {h.drivers.map((d) => `${d.name} ${formatMoney(d.before)} → ${formatMoney(d.after)}`).join(", ")}
        </p>
      )}
    </div>
  );
}

/** Себестоимость рецепта по последним ценам продуктов. */
export function CostCard({ cost, recipeId, servings }: { cost: RecipeCost; recipeId: number; servings: number }) {
  const empty = cost.counted === 0;
  const notCounted = cost.total_count - cost.counted;

  return (
    <div className="rounded-3xl border bg-card p-5 sm:p-6 print:hidden">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xl font-semibold">Себестоимость</h2>
        {!empty && servings > 1 && (
          <span className="text-xs text-muted-foreground">
            порция ≈ <span className="tabular-nums">{formatMoney(cost.per_serving)}</span>
          </span>
        )}
      </div>

      {empty ? (
        <p className="mt-3 text-sm text-muted-foreground">
          У продуктов этого рецепта ещё нет цен.{" "}
          <Link
            to={`/products?q=${encodeURIComponent(cost.missing[0] ?? "")}`}
            className="font-medium text-primary hover:underline"
          >
            Указать цены
          </Link>
        </p>
      ) : (
        <>
          <p className="mt-3 flex items-baseline gap-1.5">
            <span className="title-display text-4xl tabular-nums">{formatMoney(cost.total)}</span>
            <span className="text-sm text-muted-foreground">за рецепт</span>
          </p>
          {cost.lines.length > 0 && (
            <ul className="mt-4 grid gap-1.5 text-sm">
              {cost.lines.slice(0, 3).map((l) => (
                <li key={l.product_id} className="flex items-baseline gap-2">
                  <span className="truncate">{l.name}</span>
                  <span className="min-w-4 flex-1 border-b border-dotted border-border" />
                  <span className="tabular-nums text-muted-foreground">{formatMoney(l.cost)}</span>
                </li>
              ))}
            </ul>
          )}
          <History recipeId={recipeId} />
        </>
      )}

      {!empty && notCounted > 0 && (
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          Без учёта {notCounted} {plural(notCounted, "ингредиента", "ингредиентов", "ингредиентов")}:{" "}
          {cost.missing.slice(0, 4).join(", ")}
          {cost.missing.length > 4 && "…"}.{" "}
          <Link
            to={`/products?q=${encodeURIComponent(cost.missing[0] ?? "")}`}
            className="font-medium text-primary hover:underline"
          >
            Дополнить
          </Link>
        </p>
      )}
      {cost.stale.length > 0 && (
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
          Давно не обновляли цену: {cost.stale.slice(0, 3).join(", ")}
          {cost.stale.length > 3 && "…"} — сумма может быть занижена.
        </p>
      )}
    </div>
  );
}
