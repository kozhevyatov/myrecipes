import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Camera,
  ClipboardPaste,
  ImagePlus,
  Link2,
  Loader2,
  Plus,
  ScanText,
  Timer,
  Trash2,
  Wand2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, type Recipe, type RecipeDraft, type RecipeInput } from "@/lib/api";
import { DIFFICULTY, UNITS } from "@/lib/format";
import { useBackToRecipe, useBackToSection } from "@/lib/nav";
import { cn } from "@/lib/utils";

// ---------- состояние формы ----------
let seq = 0;
const key = () => `k${++seq}`;

type IngRow = { key: string; product: string; amount: string; unit: string; note: string };
type Group = { key: string; name: string; items: IngRow[] };
type StepRow = { key: string; text: string; timer: string; image: string | null; preview: string | null };
type PhotoRow = { key: string; image: string; url: string };

type Form = {
  title: string;
  description: string;
  category_id: string;
  servings: number;
  prep: string;
  cook: string;
  difficulty: string;
  is_public: boolean;
  tags: string[];
  groups: Group[];
  steps: StepRow[];
  source_url: string;
  image_token: string | null;
  photos: PhotoRow[];
};

const emptyIng = (): IngRow => ({ key: key(), product: "", amount: "", unit: "г", note: "" });
const emptyStep = (): StepRow => ({ key: key(), text: "", timer: "", image: null, preview: null });

function emptyForm(): Form {
  return {
    title: "",
    description: "",
    category_id: "",
    servings: 2,
    prep: "",
    cook: "",
    difficulty: "",
    is_public: true,
    tags: [],
    groups: [{ key: key(), name: "", items: [emptyIng(), emptyIng(), emptyIng()] }],
    steps: [emptyStep(), emptyStep()],
    source_url: "",
    image_token: null,
    photos: [],
  };
}

function toGroups(list: { product: string; amount: number | null; unit: string; note: string; group: string }[]): Group[] {
  const groups: Group[] = [];
  for (const ing of list) {
    const row: IngRow = {
      key: key(),
      product: ing.product,
      amount: ing.amount != null ? String(Math.round(ing.amount * 100) / 100).replace(".", ",") : "",
      unit: ing.unit,
      note: ing.note,
    };
    const last = groups[groups.length - 1];
    if (last && last.name === ing.group) last.items.push(row);
    else groups.push({ key: key(), name: ing.group, items: [row] });
  }
  if (groups.length === 0) groups.push({ key: key(), name: "", items: [emptyIng()] });
  return groups;
}

function fromDraft(d: RecipeDraft): Form {
  return {
    ...emptyForm(),
    title: d.title,
    description: d.description,
    category_id: d.category_id ? String(d.category_id) : "",
    servings: d.servings || 2,
    prep: d.prep_minutes != null ? String(d.prep_minutes) : "",
    cook: d.cook_minutes != null ? String(d.cook_minutes) : "",
    tags: d.tags,
    groups: toGroups(d.ingredients),
    steps: d.steps.length ? d.steps.map((s) => ({ ...emptyStep(), text: s.text })) : [emptyStep()],
    source_url: d.source_url,
    image_token: d.image_token,
  };
}

function fromRecipe(r: Recipe): Form {
  const groups = toGroups(r.ingredients);
  return {
    title: r.title,
    description: r.description,
    category_id: r.category ? String(r.category.id) : "",
    servings: r.servings,
    prep: r.prep_minutes != null ? String(r.prep_minutes) : "",
    cook: r.cook_minutes != null ? String(r.cook_minutes) : "",
    difficulty: r.difficulty ? String(r.difficulty) : "",
    is_public: r.is_public,
    tags: r.tags,
    groups,
    steps: r.steps.length
      ? r.steps.map((s) => ({
          key: key(),
          text: s.text,
          timer: s.timer_minutes ? String(s.timer_minutes) : "",
          image: s.image ?? null,
          preview: s.thumb_url ?? s.image_url ?? null,
        }))
      : [emptyStep()],
    source_url: r.source_url ?? "",
    image_token: null,
    photos: r.photos.map((p) => ({ key: key(), image: p.image, url: p.thumb_url ?? p.url })),
  };
}

const int = (s: string) => {
  const n = parseInt(s, 10);
  return Number.isFinite(n) && n >= 0 ? n : null;
};
const num = (s: string) => {
  const n = parseFloat(s.replace(",", ".").replace(/\s/g, ""));
  return Number.isFinite(n) && n >= 0 ? n : null;
};

function toInput(f: Form): RecipeInput {
  return {
    title: f.title.trim(),
    description: f.description.trim(),
    category_id: f.category_id ? Number(f.category_id) : null,
    servings: f.servings,
    prep_minutes: int(f.prep),
    cook_minutes: int(f.cook),
    difficulty: f.difficulty ? Number(f.difficulty) : null,
    is_public: f.is_public,
    source_url: f.source_url.trim() || null,
    image_token: f.image_token,
    tags: f.tags,
    ingredients: f.groups.flatMap((g) =>
      g.items
        .filter((i) => i.product.trim())
        .map((i) => ({
          product: i.product.trim(),
          amount: i.unit === "по вкусу" ? null : num(i.amount),
          unit: i.unit,
          note: i.note.trim(),
          group: g.name.trim(),
        })),
    ),
    steps: f.steps
      .filter((s) => s.text.trim())
      .map((s) => ({ text: s.text.trim(), timer_minutes: int(s.timer) || null, image: s.image })),
    photos: f.photos.map((p) => p.image),
  };
}

function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

// ---------- мелкие компоненты ----------
function Section({ title, hint, children, action }: { title: string; hint?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-3xl border bg-card p-5 sm:p-7">
      <div className="mb-5 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{title}</h2>
          {hint && <p className="mt-0.5 text-sm text-muted-foreground">{hint}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function IconBtn({ label, onClick, disabled, children, danger }: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-30",
        danger && "hover:text-destructive",
      )}
    >
      {children}
    </button>
  );
}

function TagsInput({ value, onChange, suggestions }: { value: string[]; onChange: (v: string[]) => void; suggestions: string[] }) {
  const [text, setText] = useState("");
  const add = (raw: string) => {
    const t = raw.trim().replace(/^#/, "").toLowerCase();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(text);
    } else if (e.key === "Backspace" && !text && value.length) {
      onChange(value.slice(0, -1));
    }
  };
  return (
    <div className="flex min-h-11 flex-wrap items-center gap-1.5 rounded-lg border border-input bg-card px-2 py-1.5 focus-within:border-primary focus-within:ring-4 focus-within:ring-ring/30">
      {value.map((t) => (
        <span key={t} className="flex items-center gap-1 rounded-full bg-accent py-1 pr-1.5 pl-3 text-sm font-medium text-accent-foreground">
          {t}
          <button type="button" onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`Убрать ${t}`}>
            <X className="size-3.5" />
          </button>
        </span>
      ))}
      <input
        list="tag-suggestions"
        className="min-w-32 flex-1 bg-transparent px-1.5 py-1 text-[15px] outline-none placeholder:text-muted-foreground/70"
        placeholder={value.length ? "" : "ужин, быстро, без глютена…"}
        value={text}
        onChange={(e) => {
          // выбор из подсказок / ввод через запятую на телефоне
          if (e.target.value.endsWith(",")) add(e.target.value.slice(0, -1));
          else setText(e.target.value);
        }}
        onKeyDown={onKey}
        onBlur={() => text && add(text)}
        enterKeyHint="done"
      />
      <datalist id="tag-suggestions">
        {suggestions.filter((s) => !value.includes(s)).map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
    </div>
  );
}

// ---------- страница ----------
export default function RecipeEditPage() {
  const { id } = useParams();
  const editing = id !== undefined;
  const recipeId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const backToRecipe = useBackToRecipe(recipeId);
  const backToSection = useBackToSection();
  const leave = editing ? backToRecipe : backToSection;

  const existing = useQuery({
    queryKey: ["recipe", recipeId],
    queryFn: () => api.recipes.get(recipeId),
    enabled: editing,
  });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.catalog.categories });
  const tags = useQuery({ queryKey: ["tags"], queryFn: api.catalog.tags });
  const products = useQuery({ queryKey: ["products"], queryFn: api.catalog.products, staleTime: 60_000 });

  const [form, setForm] = useState<Form>(emptyForm);
  const [loaded, setLoaded] = useState(!editing);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [removeImage, setRemoveImage] = useState(false);
  const [newCategory, setNewCategory] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [importedImage, setImportedImage] = useState<string | null>(null);
  const [importMode, setImportMode] = useState<"url" | "text" | "image">("url");
  const [importText, setImportText] = useState("");
  const [uploading, setUploading] = useState(0);
  // Скриншоты для распознавания — по порядку
  const [shots, setShots] = useState<{ key: string; file: File; url: string }[]>([]);
  const shotsRef = useRef(shots);
  shotsRef.current = shots;
  useEffect(() => () => shotsRef.current.forEach((x) => URL.revokeObjectURL(x.url)), []);
  const fileInput = useRef<HTMLInputElement>(null);
  const galleryInput = useRef<HTMLInputElement>(null);
  const screenshotInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (existing.data && !loaded) {
      setForm(fromRecipe(existing.data));
      setLoaded(true);
    }
  }, [existing.data, loaded]);

  useEffect(() => {
    if (!imageFile) return setImagePreview(null);
    const url = URL.createObjectURL(imageFile);
    setImagePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [imageFile]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }));

  const updateGroup = (gi: number, patch: Partial<Group>) =>
    setForm((f) => ({ ...f, groups: f.groups.map((g, i) => (i === gi ? { ...g, ...patch } : g)) }));
  const updateIng = (gi: number, ii: number, patch: Partial<IngRow>) =>
    setForm((f) => ({
      ...f,
      groups: f.groups.map((g, i) =>
        i === gi ? { ...g, items: g.items.map((it, j) => (j === ii ? { ...it, ...patch } : it)) } : g,
      ),
    }));
  const updateStep = (si: number, patch: Partial<StepRow>) =>
    setForm((f) => ({ ...f, steps: f.steps.map((s, i) => (i === si ? { ...s, ...patch } : s)) }));

  const currentImage = removeImage ? null : (imagePreview ?? importedImage ?? existing.data?.image_url ?? null);

  /** Загрузить фото сразу (временное на сервере); вернёт токен и адрес превью. */
  async function upload(file: File) {
    setUploading((n) => n + 1);
    try {
      return await api.recipes.uploadPhoto(file);
    } catch (e) {
      toast.error(`Фото не загрузилось: ${(e as Error).message}`);
      return null;
    } finally {
      setUploading((n) => n - 1);
    }
  }

  async function addGalleryPhotos(files: FileList) {
    for (const file of Array.from(files).slice(0, 30 - form.photos.length)) {
      const res = await upload(file);
      if (res) setForm((f) => ({ ...f, photos: [...f.photos, { key: key(), image: res.token, url: res.thumb_url ?? res.url }] }));
    }
  }

  async function setStepPhoto(stepKey: string, file: File) {
    const res = await upload(file);
    if (res)
      setForm((f) => ({
        ...f,
        steps: f.steps.map((s) => (s.key === stepKey ? { ...s, image: res.token, preview: res.thumb_url ?? res.url } : s)),
      }));
  }

  async function runImport() {
    const url = importUrl.trim();
    if (importMode === "url" && !url) return;
    if (importMode === "text" && !importText.trim()) return;
    setImporting(true);
    try {
      const draft =
        importMode === "url"
          ? await api.recipes.importFromUrl(url)
          : importMode === "text"
            ? await api.recipes.importFromText(importText)
            : await api.recipes.importFromImages(shots.map((x) => x.file));
      setForm(fromDraft(draft));
      setImportedImage(draft.image_url);
      setImageFile(null);
      setRemoveImage(false);
      // Категории с сайта нет у нас — предложим создать, но не создаём сами
      setNewCategory(draft.category_id ? null : draft.category_name || null);
      if (importMode === "image") setShots([]);
      const n = draft.ingredients.length;
      toast.success("Рецепт загружен — проверьте и сохраните", {
        description: `${n} ингредиент(ов), ${draft.steps.length} шаг(ов)${draft.image_url ? ", фото" : ""}`,
      });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setImporting(false);
    }
  }

  async function addCategory() {
    const name = (newCategory ?? "").trim();
    if (!name) return setNewCategory(null);
    try {
      const cat = await api.catalog.createCategory(name);
      await queryClient.invalidateQueries({ queryKey: ["categories"] });
      set("category_id", String(cat.id));
      setNewCategory(null);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }

  async function save() {
    const input = toInput(form);
    if (!input.title) return toast.error("Укажите название рецепта");
    setSaving(true);
    try {
      let recipe = editing ? await api.recipes.update(recipeId, input) : await api.recipes.create(input);
      try {
        if (imageFile) recipe = await api.recipes.uploadImage(recipe.id, imageFile);
        else if (removeImage && recipe.image_url) recipe = await api.recipes.removeImage(recipe.id);
      } catch (e) {
        toast.error(`Рецепт сохранён, но фото не загрузилось: ${(e as Error).message}`);
      }
      queryClient.setQueryData(["recipe", recipe.id], recipe);
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      queryClient.invalidateQueries({ queryKey: ["products"] });
      toast.success(editing ? "Изменения сохранены" : "Рецепт добавлен");
      // Правка открыта с рецепта — возвращаемся на него же, не плодя записи в истории
      if (editing) backToRecipe();
      else navigate(`/recipes/${recipe.id}`, { replace: true });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (editing && !loaded) {
    return (
      <div className="flex justify-center py-20">
        {existing.isError ? (
          <p className="text-muted-foreground">Не удалось загрузить рецепт</p>
        ) : (
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        )}
      </div>
    );
  }
  if (editing && existing.data && !existing.data.can_edit) {
    return <p className="py-20 text-center text-muted-foreground">Редактировать может только автор рецепта.</p>;
  }

  return (
    <form
      className="mx-auto grid max-w-3xl gap-6 pb-24"
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <div className="flex items-center gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={leave}>
          <ArrowLeft /> Назад
        </Button>
      </div>
      <h1 className="title-display text-3xl sm:text-4xl">{editing ? "Редактирование" : "Новый рецепт"}</h1>

      {!editing && (
        <section className="rounded-3xl bg-accent/60 p-5 sm:p-7">
          <h2 className="flex items-center gap-2 text-lg font-semibold">
              <Wand2 className="size-5 text-primary" /> Импорт
          </h2>
          <div className="mt-3 flex flex-wrap gap-1.5" role="tablist">
            {(
              [
                ["url", "По ссылке", Link2],
                ["text", "Из текста", ClipboardPaste],
                ["image", "Со скриншотов", ScanText],
              ] as const
            ).map(([mode, label, Icon]) => (
              <button
                key={mode}
                type="button"
                role="tab"
                aria-selected={importMode === mode}
                onClick={() => setImportMode(mode)}
                className={cn(
                  "flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors",
                  importMode === mode ? "bg-foreground text-background" : "bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                <Icon className="size-4" /> {label}
              </button>
            ))}
          </div>
          <p className="mt-3 text-sm text-muted-foreground">
            {importMode === "url" && "Ссылка на рецепт с кулинарного сайта — название, фото, ингредиенты и шаги заполнятся сами."}
            {importMode === "text" &&
              "Вставьте рецепт из Telegram, заметок или сообщения — разберём на название, ингредиенты и шаги."}
            {importMode === "image" &&
              "Скриншоты или фото рецепта, до 10 штук — распознаем текст по порядку и разберём его. Проверьте результат: распознавание бывает неточным."}
          </p>
          {importMode === "text" && (
            <div className="mt-4 grid gap-2">
              <Textarea
                rows={7}
                placeholder={"Блины на молоке\n\nИнгредиенты:\nМолоко — 500 мл\nЯйца — 3 шт\n\nПриготовление:\n1. Взбейте яйца…"}
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
              />
              <Button type="button" className="justify-self-start" onClick={() => runImport()} disabled={importing || !importText.trim()}>
                {importing ? <Loader2 className="animate-spin" /> : <Wand2 />} Разобрать
              </Button>
            </div>
          )}
          {importMode === "image" && (
            <div className="mt-4 grid gap-3">
              {shots.length > 0 && (
                <ol className="flex gap-2 overflow-x-auto pb-1 [scrollbar-width:none]">
                  {shots.map((x, i) => (
                    <li key={x.key} className="relative w-24 shrink-0 overflow-hidden rounded-xl border bg-muted">
                      <img src={x.url} alt="" className="aspect-[9/16] w-full object-cover object-top" />
                      <span className="absolute top-1 left-1 flex size-6 items-center justify-center rounded-full bg-foreground text-xs font-semibold text-background">
                        {i + 1}
                      </span>
                      <button
                        type="button"
                        aria-label="Убрать"
                        onClick={() => setShots((list) => list.filter((y) => y.key !== x.key))}
                        className="absolute top-1 right-1 flex size-6 items-center justify-center rounded-full bg-background/85 backdrop-blur-md hover:text-destructive"
                      >
                        <X className="size-3.5" />
                      </button>
                      <div className="absolute inset-x-1 bottom-1 flex justify-between">
                        <button
                          type="button"
                          aria-label="Раньше"
                          disabled={i === 0}
                          onClick={() => setShots((list) => move(list, i, i - 1))}
                          className="flex size-6 items-center justify-center rounded-full bg-background/85 backdrop-blur-md disabled:opacity-0"
                        >
                          <ArrowLeft className="size-3.5" />
                        </button>
                        <button
                          type="button"
                          aria-label="Позже"
                          disabled={i === shots.length - 1}
                          onClick={() => setShots((list) => move(list, i, i + 1))}
                          className="flex size-6 rotate-180 items-center justify-center rounded-full bg-background/85 backdrop-blur-md disabled:opacity-0"
                        >
                          <ArrowLeft className="size-3.5" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
              <div className="flex flex-wrap gap-2">
                {shots.length < 10 && (
                  <Button
                    type="button"
                    variant={shots.length ? "outline" : "default"}
                    onClick={() => screenshotInput.current?.click()}
                    disabled={importing}
                  >
                    <Camera /> {shots.length ? "Ещё картинки" : "Выбрать картинки"}
                  </Button>
                )}
                {shots.length > 0 && (
                  <Button type="button" onClick={() => runImport()} disabled={importing}>
                    {importing ? <Loader2 className="animate-spin" /> : <ScanText />}
                    {importing ? "Распознаём…" : shots.length > 1 ? `Распознать ${shots.length}` : "Распознать"}
                  </Button>
                )}
              </div>
              {shots.length > 1 && (
                <p className="text-xs text-muted-foreground">
                  Текст склеится в этом порядке, повтор на стыке скриншотов уберётся. Порядок меняется стрелками.
                </p>
              )}
              <input
                ref={screenshotInput}
                type="file"
                accept="image/*"
                multiple
                hidden
                onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []) as File[];
                  if (picked.length)
                    setShots((list) =>
                      [...list, ...picked.map((file) => ({ key: key(), file, url: URL.createObjectURL(file) }))].slice(0, 10),
                    );
                  e.target.value = "";
                }}
              />
            </div>
          )}
          {importMode === "url" && (
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Link2 className="absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="url"
                inputMode="url"
                placeholder="https://…"
                className="pl-10"
                value={importUrl}
                onChange={(e) => setImportUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    runImport();
                  }
                }}
              />
            </div>
            <Button type="button" onClick={() => runImport()} disabled={importing || !importUrl.trim()}>
              {importing ? <Loader2 className="animate-spin" /> : <Wand2 />} Загрузить
            </Button>
          </div>
          )}
        </section>
      )}

      {/* Основное */}
      <Section title="Основное">
        <div className="grid gap-5">
          <div className="grid gap-5 sm:grid-cols-[12rem_1fr]">
            <div className="grid content-start gap-2">
              <span className="text-sm font-semibold">Фото</span>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="group relative aspect-[4/3] overflow-hidden rounded-xl border-2 border-dashed border-input bg-muted/50 transition-colors hover:border-primary"
              >
                {currentImage ? (
                  <img src={currentImage} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="flex h-full flex-col items-center justify-center gap-1 text-sm text-muted-foreground">
                    <ImagePlus className="size-6" />
                    Добавить
                  </span>
                )}
              </button>
              {currentImage && (
                <button
                  type="button"
                  className="justify-self-start text-xs font-semibold text-muted-foreground hover:text-destructive"
                  onClick={() => {
                    setImageFile(null);
                    setImportedImage(null);
                    set("image_token", null);
                    setRemoveImage(true);
                  }}
                >
                  Убрать фото
                </button>
              )}
              <input
                ref={fileInput}
                type="file"
                accept="image/*"
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    setImageFile(file);
                    setImportedImage(null);
                    set("image_token", null);
                    setRemoveImage(false);
                  }
                  e.target.value = "";
                }}
              />
            </div>
            <div className="grid content-start gap-5">
              <Field id="title" label="Название">
                <Input
                  id="title"
                  required
                  maxLength={200}
                  placeholder="Борщ с говядиной"
                  value={form.title}
                  onChange={(e) => set("title", e.target.value)}
                />
              </Field>
              <Field id="description" label="Описание" hint="Пара слов о блюде — необязательно">
                <Textarea
                  id="description"
                  rows={3}
                  value={form.description}
                  onChange={(e) => set("description", e.target.value)}
                />
              </Field>
            </div>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <Field id="category" label="Категория">
              {newCategory === null ? (
                <Select
                  id="category"
                  value={form.category_id}
                  onChange={(e) => (e.target.value === "__new" ? setNewCategory("") : set("category_id", e.target.value))}
                >
                  <option value="">Без категории</option>
                  {categories.data?.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                  <option value="__new">+ Новая категория…</option>
                </Select>
              ) : (
                <div className="flex gap-2">
                  <Input
                    id="category"
                    autoFocus
                    placeholder="Например, Супы"
                    value={newCategory}
                    onChange={(e) => setNewCategory(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addCategory();
                      }
                      if (e.key === "Escape") setNewCategory(null);
                    }}
                  />
                  <Button type="button" variant="secondary" onClick={addCategory}>
                    OK
                  </Button>
                </div>
              )}
            </Field>
            <Field id="tags" label="Теги" hint="Enter или запятая — добавить">
              <TagsInput value={form.tags} onChange={(v) => set("tags", v)} suggestions={tags.data?.map((t) => t.name) ?? []} />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
            <Field id="servings" label="Порций">
              <Input
                id="servings"
                type="number"
                inputMode="numeric"
                min={1}
                max={100}
                value={form.servings}
                onChange={(e) => set("servings", Math.min(100, Math.max(1, Number(e.target.value) || 1)))}
              />
            </Field>
            <Field id="prep" label="Подготовка, мин">
              <Input id="prep" inputMode="numeric" value={form.prep} onChange={(e) => set("prep", e.target.value.replace(/\D/g, ""))} />
            </Field>
            <Field id="cook" label="Готовка, мин">
              <Input id="cook" inputMode="numeric" value={form.cook} onChange={(e) => set("cook", e.target.value.replace(/\D/g, ""))} />
            </Field>
            <Field id="difficulty" label="Сложность">
              <Select id="difficulty" value={form.difficulty} onChange={(e) => set("difficulty", e.target.value)}>
                <option value="">—</option>
                {[1, 2, 3].map((d) => (
                  <option key={d} value={d}>
                    {DIFFICULTY[d]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl bg-muted/60 p-4">
            <span>
              <span className="block font-semibold">Виден всем</span>
              <span className="text-sm text-muted-foreground">
                {form.is_public ? "Рецепт увидят все пользователи сервиса." : "Рецепт видите только вы."}
              </span>
            </span>
            <Switch checked={form.is_public} onCheckedChange={(v) => set("is_public", v)} />
          </label>

          <Field id="source_url" label="Источник" hint="Ссылка на оригинал рецепта — необязательно">
            <Input
              id="source_url"
              type="url"
              inputMode="url"
              placeholder="https://…"
              value={form.source_url}
              onChange={(e) => set("source_url", e.target.value)}
            />
          </Field>
        </div>
      </Section>

      {/* Галерея */}
      <Section title="Ещё фото" hint="Готовое блюдо с разных сторон, в разрезе, подача — до 30 фото">
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {form.photos.map((p, pi) => (
            <div key={p.key} className="group relative aspect-square overflow-hidden rounded-xl border bg-muted">
              <img src={p.url} alt="" className="h-full w-full object-cover" />
              <div className="absolute inset-x-1 top-1 flex justify-between">
                <button
                  type="button"
                  aria-label="Сдвинуть левее"
                  disabled={pi === 0}
                  onClick={() => set("photos", move(form.photos, pi, pi - 1))}
                  className="flex size-7 items-center justify-center rounded-full bg-background/85 backdrop-blur-md disabled:opacity-0"
                >
                  <ArrowLeft className="size-3.5" />
                </button>
                <button
                  type="button"
                  aria-label="Убрать фото"
                  onClick={() => set("photos", form.photos.filter((_, i) => i !== pi))}
                  className="flex size-7 items-center justify-center rounded-full bg-background/85 backdrop-blur-md hover:text-destructive"
                >
                  <X className="size-3.5" />
                </button>
              </div>
            </div>
          ))}
          {form.photos.length < 30 && (
            <button
              type="button"
              onClick={() => galleryInput.current?.click()}
              className="flex aspect-square flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed border-input bg-muted/50 text-sm text-muted-foreground transition-colors hover:border-primary"
            >
              {uploading ? <Loader2 className="size-6 animate-spin" /> : <ImagePlus className="size-6" />}
              Добавить
            </button>
          )}
        </div>
        <input
          ref={galleryInput}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(e) => {
            if (e.target.files?.length) addGalleryPhotos(e.target.files);
            e.target.value = "";
          }}
        />
      </Section>

      {/* Ингредиенты */}
      <Section
        title="Ингредиенты"
        hint={`На ${form.servings} порц. — при просмотре пересчитаются под нужное количество`}
      >
        <datalist id="product-suggestions">
          {products.data?.map((p) => (
            <option key={p} value={p} />
          ))}
        </datalist>

        <div className="grid gap-6">
          {form.groups.map((g, gi) => (
            <div key={g.key} className={cn("grid gap-2", form.groups.length > 1 && "rounded-xl border p-3 sm:p-4")}>
              {form.groups.length > 1 && (
                <div className="mb-1 flex items-center gap-2">
                  <Input
                    className="h-9 font-semibold"
                    placeholder="Название раздела, например «Для соуса»"
                    value={g.name}
                    onChange={(e) => updateGroup(gi, { name: e.target.value })}
                  />
                  <IconBtn
                    label="Удалить раздел"
                    danger
                    onClick={() => setForm((f) => ({ ...f, groups: f.groups.filter((_, i) => i !== gi) }))}
                  >
                    <Trash2 className="size-4" />
                  </IconBtn>
                </div>
              )}

              {g.items.map((it, ii) => (
                <div
                  key={it.key}
                  className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-center gap-2 border-b border-dashed pb-3 sm:grid-cols-[1fr_6rem_7rem_10rem_auto] sm:border-0 sm:pb-0"
                >
                  <Input
                    list="product-suggestions"
                    placeholder="Продукт"
                    className="col-span-2 h-10 sm:col-span-1"
                    value={it.product}
                    onChange={(e) => updateIng(gi, ii, { product: e.target.value })}
                  />
                  <Input
                    inputMode="decimal"
                    placeholder="Кол-во"
                    className="h-10"
                    disabled={it.unit === "по вкусу"}
                    value={it.unit === "по вкусу" ? "" : it.amount}
                    onChange={(e) => updateIng(gi, ii, { amount: e.target.value.replace(/[^\d.,]/g, "") })}
                  />
                  <Select className="h-10 pl-2.5" value={it.unit} onChange={(e) => updateIng(gi, ii, { unit: e.target.value })}>
                    {(UNITS.includes(it.unit) || !it.unit ? UNITS : [it.unit, ...UNITS]).map((u) => (
                      <option key={u} value={u}>
                        {u}
                      </option>
                    ))}
                    <option value="">—</option>
                  </Select>
                  <Input
                    placeholder="Примечание"
                    className="col-span-2 col-start-1 row-start-3 h-10 sm:col-span-1 sm:col-start-auto sm:row-start-auto"
                    value={it.note}
                    onChange={(e) => updateIng(gi, ii, { note: e.target.value })}
                  />
                  <div className="col-start-3 row-span-3 row-start-1 flex flex-col sm:col-start-auto sm:row-span-1 sm:row-start-auto sm:flex-row">
                    <IconBtn
                      label="Выше"
                      disabled={ii === 0}
                      onClick={() => updateGroup(gi, { items: move(g.items, ii, ii - 1) })}
                    >
                      <ArrowUp className="size-4" />
                    </IconBtn>
                    <IconBtn
                      label="Удалить"
                      danger
                      onClick={() => updateGroup(gi, { items: g.items.filter((_, j) => j !== ii) })}
                    >
                      <Trash2 className="size-4" />
                    </IconBtn>
                  </div>
                </div>
              ))}

              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="justify-self-start"
                onClick={() => updateGroup(gi, { items: [...g.items, emptyIng()] })}
              >
                <Plus /> Ингредиент
              </Button>
            </div>
          ))}

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="justify-self-start"
            onClick={() =>
              setForm((f) => ({ ...f, groups: [...f.groups, { key: key(), name: "", items: [emptyIng()] }] }))
            }
          >
            <Plus /> Раздел ингредиентов
          </Button>
        </div>
      </Section>

      {/* Шаги */}
      <Section title="Приготовление" hint="Один шаг — одно действие. Можно указать таймер.">
        <ol className="grid gap-4">
          {form.steps.map((s, si) => (
            <li key={s.key} className="flex gap-3">
              <span className="mt-2 flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-extrabold text-primary-foreground">
                {si + 1}
              </span>
              <div className="grid flex-1 gap-2">
                <Textarea
                  rows={3}
                  placeholder={si === 0 ? "Например: нарежьте лук мелкими кубиками…" : "Что делаем дальше?"}
                  value={s.text}
                  onChange={(e) => updateStep(si, { text: e.target.value })}
                />
                {s.preview && (
                  <div className="relative w-40 overflow-hidden rounded-xl border">
                    <img src={s.preview} alt="" className="aspect-[4/3] w-full object-cover" />
                    <button
                      type="button"
                      aria-label="Убрать фото шага"
                      onClick={() => updateStep(si, { image: null, preview: null })}
                      className="absolute top-1 right-1 flex size-7 items-center justify-center rounded-full bg-background/85 backdrop-blur-md hover:text-destructive"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>
                )}
                <div className="flex items-center gap-1 sm:gap-2">
                  <div className="relative w-28 shrink-0 sm:w-36">
                    <Timer className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      inputMode="numeric"
                      placeholder="Таймер"
                      className="h-9 pr-11 pl-9"
                      value={s.timer}
                      onChange={(e) => updateStep(si, { timer: e.target.value.replace(/\D/g, "") })}
                    />
                    <span className="absolute top-1/2 right-3 -translate-y-1/2 text-xs text-muted-foreground">мин</span>
                  </div>
                  <label
                    className="flex h-9 cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    title="Фото шага"
                  >
                    <ImagePlus className="size-4" />
                    <span className="hidden sm:inline">{s.preview ? "Заменить фото" : "Фото"}</span>
                    <input
                      type="file"
                      accept="image/*"
                      hidden
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) setStepPhoto(s.key, file);
                        e.target.value = "";
                      }}
                    />
                  </label>
                  <span className="flex-1" />
                  <IconBtn
                    label="Выше"
                    disabled={si === 0}
                    onClick={() => set("steps", move(form.steps, si, si - 1))}
                  >
                    <ArrowUp className="size-4" />
                  </IconBtn>
                  <IconBtn
                    label="Ниже"
                    disabled={si === form.steps.length - 1}
                    onClick={() => set("steps", move(form.steps, si, si + 1))}
                  >
                    <ArrowDown className="size-4" />
                  </IconBtn>
                  <IconBtn
                    label="Удалить шаг"
                    danger
                    disabled={form.steps.length === 1}
                    onClick={() => set("steps", form.steps.filter((_, i) => i !== si))}
                  >
                    <Trash2 className="size-4" />
                  </IconBtn>
                </div>
              </div>
            </li>
          ))}
        </ol>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mt-3"
          onClick={() => set("steps", [...form.steps, emptyStep()])}
        >
          <Plus /> Шаг
        </Button>
      </Section>

      {/* Панель сохранения */}
      <div className="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl items-center justify-end gap-3 px-4 py-3">
          <Button type="button" variant="ghost" onClick={leave}>
            Отмена
          </Button>
          <Button type="submit" size="lg" disabled={saving || uploading > 0}>
            {saving && <Loader2 className="animate-spin" />} {editing ? "Сохранить" : "Добавить рецепт"}
          </Button>
        </div>
      </div>
    </form>
  );
}
