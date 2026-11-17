import { useId, useState } from "react";
import { ChevronDown, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Select } from "@/components/ui/select";
import type { Category, RecipeSourceSummary, TagInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

type Options<T> = {
  items: T[];
  loading: boolean;
  error?: string;
  retry: () => void;
};

type FilterKey = "category" | "source" | "mine" | "fav";

type Props = {
  categoryId?: number;
  selectedTags: string[];
  onAddTag: (name: string) => void;
  onRemoveTag: (name: string) => void;
  sourceId?: number;
  mine: boolean;
  favorites: boolean;
  searchActive: boolean;
  categories: Options<Category>;
  tags: Options<TagInfo>;
  sources: Options<RecipeSourceSummary>;
  onChange: (key: FilterKey, value: string | null) => void;
  onAll: () => void;
  onReset: () => void;
};

function OptionError({ error, retry }: { error?: string; retry: () => void }) {
  if (!error) return null;
  return <div role="alert" className="grid justify-items-start gap-1 text-xs text-destructive"><p>{error}</p><button type="button" className="rounded underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={retry}>Повторить загрузку</button></div>;
}

export function RecipeFilters({ categoryId, selectedTags, onAddTag, onRemoveTag, sourceId, mine, favorites, searchActive, categories, tags, sources, onChange, onAll, onReset }: Props) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const category = categories.items.find((item) => item.id === categoryId);
  const source = sources.items.find((item) => item.id === sourceId);
  const selected = [
    ...(categoryId ? [{ key: "category" as const, label: category?.name ?? `Категория №${categoryId}`, kind: "Категория" }] : []),
    ...selectedTags.map((name) => ({ key: "tag" as const, label: name, kind: "Тег" })),
    ...(sourceId ? [{ key: "source" as const, label: source?.name ?? `Источник №${sourceId}`, kind: "Источник" }] : []),
  ];
  const filtered = selected.length > 0 || mine || favorites || searchActive;
  const showSources = sources.items.length > 0 || Boolean(sourceId) || sources.loading || Boolean(sources.error);

  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex flex-wrap items-center gap-2" aria-label="Фильтры рецептов">
        <Chip className="px-3" active={!selected.length && !mine && !favorites} aria-pressed={!selected.length && !mine && !favorites} onClick={onAll}>Все</Chip>
        <Chip className="px-3" active={favorites} aria-pressed={favorites} onClick={() => onChange("fav", favorites ? null : "1")}>Избранное</Chip>
        <Chip className="px-3" active={mine} aria-pressed={mine} onClick={() => onChange("mine", mine ? null : "1")}>Мои</Chip>
        <Button type="button" size="sm" variant="outline" className="h-9 rounded-full px-3 sm:ml-auto" aria-expanded={open} aria-controls={`${id}-panel`} onClick={() => setOpen((value) => !value)}>
          <SlidersHorizontal /> Фильтры
          {selected.length > 0 && <span className="rounded-full bg-primary/10 px-1.5 text-xs text-primary">{selected.length}</span>}
          <ChevronDown className={cn("transition-transform", open && "rotate-180")} />
        </Button>
      </div>

      {(selected.length > 0 || filtered) && (
        <div className="flex min-w-0 flex-wrap items-center gap-2" aria-label="Выбранные фильтры">
          {selected.map((item) => <button key={`${item.key}:${item.label}`} type="button" title={item.label} aria-label={`Убрать фильтр «${item.kind}: ${item.label}»`} onClick={() => item.key === "tag" ? onRemoveTag(item.label) : onChange(item.key, null)} className="inline-flex h-8 min-w-0 max-w-full items-center gap-2 rounded-full bg-accent px-3 text-xs text-accent-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring sm:max-w-xs"><span className="truncate">{item.kind}: {item.label}</span><X className="size-3 shrink-0" /></button>)}
          {selectedTags.length > 1 && <span className="text-xs text-muted-foreground">Все выбранные теги</span>}
          <button type="button" className="shrink-0 rounded px-1 py-1 text-xs text-muted-foreground underline underline-offset-4 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring" onClick={onReset}>Сбросить всё</button>
        </div>
      )}

      <div id={`${id}-panel`} hidden={!open} className={cn("min-w-0 rounded-2xl border bg-card p-4", open && "grid gap-4 sm:grid-cols-2", open && showSources && "lg:grid-cols-3")}>
        <div className="grid min-w-0 content-start gap-2">
          <label htmlFor={`${id}-category`} className="text-sm font-medium">Категория</label>
          <Select id={`${id}-category`} className="min-w-0 max-w-full truncate" value={categoryId ?? ""} disabled={categories.loading && !categories.items.length} onChange={(event) => onChange("category", event.target.value || null)}>
            <option value="">{categories.loading ? "Загрузка категорий…" : "Все категории"}</option>
            {categoryId && !category && <option value={categoryId}>{`Категория №${categoryId}`}</option>}
            {categories.items.map((item) => <option key={item.id} value={item.id}>{item.name}{item.recipe_count > 0 ? ` (${item.recipe_count})` : ""}</option>)}
          </Select>
          <OptionError error={categories.error} retry={categories.retry} />
        </div>
        <div className="grid min-w-0 content-start gap-2">
          <label htmlFor={`${id}-tag`} className="text-sm font-medium">Добавить тег</label>
          <Select id={`${id}-tag`} className="min-w-0 max-w-full truncate" value="" disabled={selectedTags.length >= 20 || (tags.loading && !tags.items.length)} onChange={(event) => { if (event.target.value) onAddTag(event.target.value); }}>
            <option value="">{tags.loading ? "Загрузка тегов…" : selectedTags.length >= 20 ? "Выбрано 20 тегов" : "Выберите тег или кухню"}</option>
            {tags.items.filter((item) => !selectedTags.includes(item.name.trim().toLowerCase())).map((item) => <option key={item.name} value={item.name}>{item.name}{item.recipe_count > 0 ? ` (${item.recipe_count})` : ""}</option>)}
          </Select>
          <OptionError error={tags.error} retry={tags.retry} />
        </div>
        {showSources && <div className="grid min-w-0 content-start gap-2">
          <label htmlFor={`${id}-source`} className="text-sm font-medium">Источник рецептов</label>
          <Select id={`${id}-source`} className="min-w-0 max-w-full truncate" value={sourceId ?? ""} disabled={sources.loading && !sources.items.length} onChange={(event) => onChange("source", event.target.value || null)}>
            <option value="">{sources.loading ? "Загрузка источников…" : "Все источники и свои рецепты"}</option>
            {sourceId && !source && <option value={sourceId}>{`Источник №${sourceId}`}</option>}
            {sources.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </Select>
          <OptionError error={sources.error} retry={sources.retry} />
        </div>}
      </div>
    </div>
  );
}
