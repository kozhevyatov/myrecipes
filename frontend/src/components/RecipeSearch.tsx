import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Search, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { api, type RecipeQuery } from "@/lib/api";

type Props = {
  value: string;
  onChange: (value: string) => void;
  onSelectTag: (name: string) => void;
  filters: Pick<RecipeQuery, "category_id" | "tags" | "source_id" | "mine" | "favorites">;
  online: boolean;
};

export function RecipeSearch({ value, onChange, onSelectTag, filters, online }: Props) {
  const [query, setQuery] = useState(value.trim());
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const limitReached = (filters.tags?.length ?? 0) >= 20;
  const eligible = online && value.trim().length >= 2 && !limitReached;
  useEffect(() => {
    const timer = setTimeout(() => setQuery(value.trim()), 300);
    return () => clearTimeout(timer);
  }, [value]);
  const suggestions = useQuery({
    queryKey: ["tag-suggestions", query, filters],
    queryFn: ({ signal }) => api.catalog.tagSuggestions({ ...filters, q: query, limit: 8 }, signal),
    enabled: eligible && query === value.trim() && focused && !dismissed,
    staleTime: 30_000,
  });
  const show = eligible && focused && !dismissed;
  const settled = query === value.trim();
  const items = settled ? suggestions.data ?? [] : [];

  return (
    <div
      className={`${online ? "sticky top-[65px]" : "relative"} z-20 -mx-1 -my-2 min-w-0 bg-background px-1 py-2 print:static`}
      onFocus={() => setFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          input.current?.focus();
          setDismissed(true);
        }
      }}
    >
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={input}
          className="h-13 rounded-full border-transparent bg-card pr-11 pl-11 shadow-[0_1px_2px_rgb(0_0_0/0.04),0_0_0_1px_var(--border)] focus-visible:shadow-none"
          placeholder="Название или тег — например, «салат»"
          value={value}
          maxLength={100}
          onFocus={() => setDismissed(false)}
          onChange={(event) => {
            onChange(event.target.value);
            setDismissed(false);
          }}
          type="text"
          aria-label="Поиск рецептов"
          aria-controls={show ? `${id}-suggestions` : undefined}
          enterKeyHint="search"
          autoComplete="off"
        />
        {value && <button type="button" className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md p-1 text-muted-foreground hover:text-foreground" onClick={() => { onChange(""); input.current?.focus(); }} aria-label="Очистить"><X className="size-4" /></button>}
      </div>

      {show && (
        <div id={`${id}-suggestions`} className="absolute top-full right-1 left-1 max-h-[min(40vh,16rem)] overflow-y-auto rounded-2xl border bg-card p-3 shadow-lg" aria-label="Подсказки по тегам">
          <p className="mb-2 text-xs text-muted-foreground">Теги и кухни · нажмите, чтобы уточнить поиск</p>
          {!settled || suggestions.isPending ? <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" />Ищем теги…</p> : suggestions.isError ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-xs"><span>Не удалось загрузить подсказки.</span><button type="button" className="rounded underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring" onClick={() => { suggestions.refetch(); }}>Повторить</button></div>
          ) : items.length > 0 ? (
            <div className="flex min-w-0 flex-wrap gap-2" role="group" aria-label="Подходящие теги">
              {items.map((item) => <button key={item.name} type="button" title={item.name} className="inline-flex min-h-9 min-w-0 max-w-full items-center gap-2 rounded-full bg-accent px-3 py-1.5 text-sm text-accent-foreground outline-none hover:bg-accent/70 focus-visible:ring-2 focus-visible:ring-ring" onClick={() => { onSelectTag(item.name); input.current?.focus(); }}><span className="truncate">{item.name}</span><span className="shrink-0 text-xs tabular-nums opacity-65">{item.recipe_count}</span></button>)}
            </div>
          ) : <p role="status" className="text-xs text-muted-foreground">Подходящих тегов нет — поиск по названию продолжает работать.</p>}
        </div>
      )}
      {limitReached && focused && <p role="status" className="mt-2 text-xs text-muted-foreground">Выбрано 20 тегов. Уберите один, чтобы добавить другой.</p>}
    </div>
  );
}
