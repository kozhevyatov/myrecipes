import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, ExternalLink, Globe, Loader2, Pencil, Play, Plus, RefreshCw, Square, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, type RecipeImportJob, type RecipeImportSource, type RecipeImportStatus, type RecipeSourceDefinition, type RecipeSourceUpdate } from "@/lib/api";
import { cn } from "@/lib/utils";

const activeStatuses: RecipeImportStatus[] = ["queued", "running", "stopping"];
const statusNames: Record<RecipeImportStatus, string> = {
  queued: "В очереди", running: "Выполняется", stopping: "Останавливается",
  completed: "Завершено", failed: "Ошибка", stopped: "Остановлено",
};

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function downloadReport(job: RecipeImportJob) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(job, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `recipe-import-${job.id}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function SourceRow({ source, busy, canIndex, onCheck, onUpdate, onIndex, onDelete }: {
  source: RecipeImportSource;
  busy: boolean;
  canIndex: boolean;
  onCheck: () => void;
  onUpdate: (data: RecipeSourceUpdate) => void;
  onIndex: () => void;
  onDelete: () => void;
}) {
  const [hours, setHours] = useState(String(source.refresh_interval_hours ?? 24));
  const [editingName, setEditingName] = useState(false);
  const [draftName, setDraftName] = useState(source.name);
  useEffect(() => setHours(String(source.refresh_interval_hours ?? 24)), [source.refresh_interval_hours]);
  useEffect(() => { setDraftName(source.name); setEditingName(false); }, [source.name]);
  function rename(event: FormEvent) {
    event.preventDefault();
    const name = draftName.trim();
    if (!name) { toast.error("Введите название источника."); return; }
    if (name === source.name) { setEditingName(false); return; }
    onUpdate({ name });
  }
  function saveInterval() {
    const value = Number(hours);
    if (!Number.isInteger(value) || value < 1 || value > 720) {
      toast.error("Период обновления должен быть от 1 до 720 часов.");
      setHours(String(source.refresh_interval_hours ?? 24));
      return;
    }
    if (value !== source.refresh_interval_hours) onUpdate({ refresh_interval_hours: value });
  }
  const indexDisabledReason = !source.enabled
    ? "Источник выключен. Включите его переключателем выше."
    : !source.verified
      ? "Сначала нажмите «Проверить» для этого источника."
      : busy
        ? "Дождитесь завершения проверки или сохранения настроек источника."
        : !canIndex
          ? "Отправляем задание на сервер…"
          : null;
  return (
    <div className="grid content-start gap-4 rounded-2xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {editingName ? <form onSubmit={rename} className="flex w-full items-center gap-1"><Input autoFocus aria-label={`Название источника ${source.name}`} value={draftName} maxLength={120} required disabled={busy} onChange={(event) => setDraftName(event.target.value)} /><Button type="submit" size="icon" variant="ghost" disabled={busy} aria-label="Сохранить название"><Check /></Button><Button type="button" size="icon" variant="ghost" disabled={busy} aria-label="Отменить переименование" onClick={() => { setDraftName(source.name); setEditingName(false); }}><X /></Button></form> : <><span className="font-semibold">{source.name}</span><Button type="button" size="icon" variant="ghost" className="size-7" disabled={busy} aria-label={`Переименовать источник ${source.name}`} onClick={() => setEditingName(true)}><Pencil className="size-3.5" /></Button></>}
            <span className={cn("rounded-full px-2 py-0.5 text-xs", source.verified ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground")}>
              {source.verified ? "Проверен" : "Нужна проверка"}
            </span>
          </div>
          <a href={source.catalog_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex max-w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <span className="truncate">{source.catalog_url}</span><ExternalLink className="size-3 shrink-0" />
          </a>
        </div>
        <label className="flex items-center gap-2 text-sm">Включён<Switch aria-label={`Источник ${source.name} включён`} checked={source.enabled} disabled={busy} onCheckedChange={(enabled) => onUpdate({ enabled })} /></label>
      </div>
      {source.last_error && <p role="alert" className="break-words text-sm text-destructive">{source.last_error}</p>}
      <div className="grid grid-cols-2 gap-3 rounded-xl bg-muted/60 p-3 text-sm">
        <div><p className="text-xs text-muted-foreground">Найдено в каталоге</p><p className="mt-1 font-semibold">{source.total_recipes == null ? source.indexed_recipes > 0 ? `Не менее ${source.indexed_recipes.toLocaleString("ru-RU")}` : "Ещё не загружен" : source.total_recipes.toLocaleString("ru-RU")}</p></div>
        <div><p className="text-xs text-muted-foreground">В коллекциях пользователей</p><p className="mt-1 font-semibold">{(source.imported_recipes ?? 0).toLocaleString("ru-RU")}</p></div>
        <p className="col-span-2 text-xs text-muted-foreground">В каталоге: {source.indexed_recipes ?? 0} · Категорий: {source.categories_count ?? 0}<br />{source.last_indexed_at ? `${source.index_complete ? "Обход завершён" : "Каталог заполнен частично"} · ${formatDate(source.last_indexed_at)}` : (source.total_recipes ?? 0) > 0 ? "Каталог пополнен при импорте; полный обход ещё не выполнялся." : "Обновите каталог, чтобы узнать состав сайта."}</p>
      </div>
      {source.index_error && <p role="alert" className="break-words text-xs text-destructive">{source.index_error}</p>}
      <div className="grid gap-3 border-t pt-3">
        <label className="flex items-center justify-between gap-3 text-sm"><span>Показывать в «Базе рецептов»</span><Switch aria-label={`Показывать рецепты ${source.name} в базе рецептов`} checked={source.visible_in_catalog ?? false} disabled={busy || !source.verified} onCheckedChange={(visible_in_catalog) => onUpdate({ visible_in_catalog })} /></label>
        <p className="-mt-1 text-xs text-muted-foreground">Рецепты появятся на вкладке «База рецептов» на главной. В коллекцию пользователя рецепт попадает, только когда он сам его добавит.</p>
        <label className="flex items-center justify-between gap-3 text-sm"><span>Обновлять каталог автоматически</span><Switch aria-label={`Автоматически обновлять ${source.name}`} checked={source.auto_refresh ?? false} disabled={busy || !source.verified} onCheckedChange={(auto_refresh) => onUpdate({ auto_refresh })} /></label>
        {source.auto_refresh && <div className="grid gap-2"><label htmlFor={`source-refresh-${source.id}`} className="text-xs text-muted-foreground">Период обновления, часов</label><div className="flex gap-2"><Input id={`source-refresh-${source.id}`} type="number" min={1} max={720} value={hours} disabled={busy} onChange={(event) => setHours(event.target.value)} /><Button type="button" size="sm" variant="outline" disabled={busy || hours === String(source.refresh_interval_hours)} onClick={saveInterval}>Сохранить</Button></div>{source.next_refresh_at && <p className="text-xs text-muted-foreground">Следующее обновление: {formatDate(source.next_refresh_at)}</p>}</div>}
      </div>
      {source.sample.title && <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Проверочный рецепт</summary><div className="mt-2 rounded-xl bg-muted/60 p-3 text-sm">{source.sample.source_url ? <a href={source.sample.source_url} target="_blank" rel="noopener noreferrer" className="font-medium underline-offset-4 hover:underline">{source.sample.title}</a> : <p className="font-medium">{source.sample.title}</p>}<p className="mt-1 text-xs">Ингредиентов: {source.sample.ingredients ?? 0} · Шагов: {source.sample.steps ?? 0} · Фото шагов: {source.sample.step_images ?? 0}{source.sample.has_cover ? " · Обложка есть" : " · Без обложки"}</p></div></details>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onCheck}><RefreshCw /> Проверить</Button>
        <Button type="button" size="sm" variant="outline" disabled={Boolean(indexDisabledReason)} title={indexDisabledReason ?? undefined} aria-describedby={indexDisabledReason ? `source-index-reason-${source.id}` : undefined} onClick={onIndex}><Globe /> Обновить каталог</Button>
        <Button type="button" size="sm" variant="ghost" className="text-destructive hover:text-destructive" disabled={busy} onClick={() => { if (confirm(`Удалить источник «${source.name}»?\n\nОн исчезнет из подключённых сайтов и из «Базы рецептов». Уже добавленные пользователями рецепты и их фотографии останутся в коллекциях пользователей.`)) onDelete(); }}><Trash2 /> Удалить</Button>
      </div>
      {indexDisabledReason && <p id={`source-index-reason-${source.id}`} role="status" className="text-xs text-muted-foreground">{indexDisabledReason}</p>}
      {source.checked_at && <p className="text-xs text-muted-foreground">Проверка: {formatDate(source.checked_at)}</p>}
    </div>
  );
}

function JobRow({ job, canStart, stopping, resuming, onStop, onResume }: {
  job: RecipeImportJob;
  canStart: boolean;
  stopping: boolean;
  resuming: boolean;
  onStop: () => void;
  onResume: () => void;
}) {
  const active = activeStatuses.includes(job.status);
  const report = job.report;
  const errors = report.errors ?? [];
  const warnings = report.warnings ?? [];
  const attempted = report.attempted ?? 0;
  const processed = report.processed ?? attempted + (report.duplicates ?? 0);
  const jobName = job.mode === "index" ? (job.parameters.urls?.length || job.parameters.category_id || job.parameters.catalog_url ? "Добавление в базу" : "Обновление базы") : job.mode === "images" ? "Дополнение фото" : "Импорт рецептов (старый режим)";
  const stopReasons: Record<string, string> = { exhausted: "Все доступные ссылки обработаны", limit: "Достигнут лимит рецептов", attempt_limit: "Достигнут предел попыток", catalog_limit: "Обход каталога завершён частично", catalog_page_limit: "Достигнут предел страниц; каталог заполнен частично", discovery_partial: "Каталог обработан частично; подробности в отчёте", catalog_error: "Не удалось прочитать часть каталога", stopped: "Остановлено", failed: "Обработка завершилась с ошибкой", fatal: "Обработка остановлена из-за ошибки" };
  const detail = job.mode === "index" ? `Найдено: ${report.discovered ?? 0} · Добавлено в базу: ${report.indexed ?? 0} · Уже в базе: ${report.cached ?? 0} · Страниц каталога: ${report.catalog_pages ?? 0}` : job.mode === "images"
    ? `Обложек: ${report.updated_images ?? 0} · Фото шагов: ${report.updated_step_images ?? 0}`
    : `Добавлено: ${report.created ?? 0} · Повторов: ${report.duplicates ?? 0} · Фото шагов: ${report.step_images ?? 0}`;
  return (
    <article className="grid gap-3 rounded-2xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{job.source_name} · {jobName}</p>
          <p className="mt-1 text-xs text-muted-foreground">№{job.id} · {formatDate(job.created_at)}</p>
        </div>
        <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium", job.status === "failed" ? "bg-destructive/10 text-destructive" : active ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground")}>
          {active && <Loader2 className="size-3 animate-spin" />}{job.status === "completed" && <Check className="size-3" />}{statusNames[job.status]}
        </span>
      </div>
      <div className="text-sm">
        <p>{detail}</p>
        {job.mode === "import" && Boolean(report.cache_hits) && <p className="mt-1 text-muted-foreground">Использовано рецептов из каталога: {report.cache_hits}</p>}
        <p className="mt-1 text-muted-foreground">Обработано: {processed} · Лимит: {job.parameters.limit === 0 ? "без лимита" : job.parameters.limit}{report.skipped ? ` · Пропущено: ${report.skipped}` : ""}</p>
      </div>
      {report.stop_reason && <p className="text-xs text-muted-foreground">{stopReasons[report.stop_reason] ?? report.stop_reason}</p>}
      {active && job.parameters.limit > 0 && (
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${Math.min(100, Math.max(0, (job.mode === "import" ? (report.created ?? 0) : attempted) / job.parameters.limit * 100))}%` }} />
        </div>
      )}
      {report.current_url && <p className="truncate text-xs text-muted-foreground" title={report.current_url}>{report.current_url}</p>}
      {(errors.length > 0 || warnings.length > 0) && (
        <details className="rounded-xl bg-muted/60 p-3 text-sm">
          <summary className="cursor-pointer font-medium">Ошибок: {report.error_count ?? errors.length} · Предупреждений: {report.warning_count ?? warnings.length}</summary>
          <ul className="mt-2 grid gap-2 text-xs">
            {errors.slice(-5).map((item, index) => <li key={`e-${index}`} className="break-words text-destructive">{item.error ?? "Ошибка импорта"}{item.url && <span className="block text-muted-foreground">{item.url}</span>}</li>)}
            {warnings.slice(-5).map((item, index) => <li key={`w-${index}`} className="break-words">{item.warning ?? "Предупреждение"}{item.url && <span className="block text-muted-foreground">{item.url}</span>}</li>)}
          </ul>
          {(errors.length > 5 || warnings.length > 5) && <p className="mt-2 text-xs text-muted-foreground">Больше подробностей — в отчёте.</p>}
          {report.details_truncated && <p className="mt-2 text-xs text-muted-foreground">Подробности старых записей сокращены; итоговые счётчики учитывают весь запуск.</p>}
        </details>
      )}
      <div className="flex flex-wrap gap-2">
        {active ? (
          <Button type="button" variant="outline" size="sm" disabled={stopping || job.cancel_requested} onClick={onStop}>
            {stopping ? <Loader2 className="animate-spin" /> : <Square />} {job.cancel_requested ? "Остановка запрошена" : "Остановить"}
          </Button>
        ) : (
          <Button type="button" variant="outline" size="sm" disabled={!canStart || resuming} onClick={onResume}>
            {resuming ? <Loader2 className="animate-spin" /> : <Play />} {job.status === "completed" ? "Повторить" : "Продолжить"}
          </Button>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={() => downloadReport(job)}><Download /> Отчёт</Button>
      </div>
    </article>
  );
}

export function RecipeImportsCard() {
  const queryClient = useQueryClient();
  const jobs = useQuery({
    queryKey: ["import-jobs"], queryFn: api.imports.jobs,
    refetchInterval: (query) => query.state.data?.some((job) => activeStatuses.includes(job.status)) ? 2000 : false,
  });
  const sources = useQuery({ queryKey: ["import-sources"], queryFn: api.imports.sources, refetchInterval: jobs.data?.some((job) => activeStatuses.includes(job.status)) ? 5000 : false });
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [catalogUrl, setCatalogUrl] = useState("");
  const [definition, setDefinition] = useState("");
  const [formError, setFormError] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [scope, setScope] = useState<"site" | "category" | "urls">("site");
  const [categoryId, setCategoryId] = useState("");
  const [manualUrls, setManualUrls] = useState("");
  const [limit, setLimit] = useState("50");

  const activeJob = jobs.data?.find((job) => activeStatuses.includes(job.status));
  const ready = sources.data?.filter((source) => source.enabled && source.verified) ?? [];
  const chosen = ready.find((source) => String(source.id) === sourceId);
  const categories = useQuery({ queryKey: ["import-categories", sourceId], queryFn: () => api.imports.categories(Number(sourceId)), enabled: Boolean(sourceId) });
  useEffect(() => setCategoryId(""), [sourceId]);
  useEffect(() => {
    if (!sourceId && ready.length) setSourceId(String(ready[0].id));
  }, [sourceId, ready]);
  useEffect(() => {
    if (jobs.data?.some((job) => !activeStatuses.includes(job.status))) {
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["import-sources"] });
      queryClient.invalidateQueries({ queryKey: ["import-categories"] });
      queryClient.invalidateQueries({ queryKey: ["site-recipes"] });
    }
  }, [jobs.data, queryClient]);

  const refreshSources = () => {
    queryClient.invalidateQueries({ queryKey: ["import-sources"] });
    queryClient.invalidateQueries({ queryKey: ["recipe-sources"] });
    queryClient.invalidateQueries({ queryKey: ["site-recipes"] });
  };
  const refreshJobs = () => queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
  const rememberJob = (job: RecipeImportJob) => {
    queryClient.setQueryData<RecipeImportJob[]>(["import-jobs"], (current) =>
      [job, ...(current ?? []).filter((item) => item.id !== job.id)].sort((a, b) => b.id - a.id).slice(0, 20));
  };
  const add = useMutation({
    mutationFn: api.imports.addSource,
    onSuccess: () => { setShowAdd(false); setName(""); setCatalogUrl(""); setDefinition(""); setFormError(""); refreshSources(); toast.success("Источник проверен и подключён"); },
    onError: (error) => setFormError(error.message),
  });
  const check = useMutation({ mutationFn: api.imports.checkSource, onSuccess: () => { refreshSources(); toast.success("Проверка завершена"); }, onError: (error) => { refreshSources(); toast.error(error.message); } });
  const update = useMutation({ mutationFn: ({ id, data }: { id: number; data: RecipeSourceUpdate }) => api.imports.updateSource(id, data), onSuccess: () => { refreshSources(); refreshJobs(); }, onError: (error) => toast.error(error.message) });
  const remove = useMutation({
    mutationFn: api.imports.removeSource,
    onSuccess: (_, id) => {
      queryClient.setQueryData<RecipeImportSource[]>(["import-sources"], (current) => current?.filter((source) => source.id !== id));
      setSourceId((current) => current === String(id) ? "" : current);
      refreshSources();
      refreshJobs();
      queryClient.invalidateQueries({ queryKey: ["import-categories"] });
      toast.success("Источник удалён. Импортированные рецепты сохранены.");
    },
    onError: (error) => toast.error(error.message),
  });
  const start = useMutation({ mutationFn: api.imports.start, onSuccess: (job) => { rememberJob(job); refreshJobs(); toast.success("Задание запущено"); }, onError: (error) => { refreshJobs(); toast.error(error.message); } });
  const stop = useMutation({ mutationFn: api.imports.stop, onSuccess: (job) => { rememberJob(job); refreshJobs(); }, onError: (error) => toast.error(error.message) });
  const clearBase = useMutation({
    mutationFn: api.imports.clearBase,
    onSuccess: (result) => {
      queryClient.setQueryData<RecipeImportJob[]>(["import-jobs"], []);
      refreshSources();
      refreshJobs();
      queryClient.invalidateQueries({ queryKey: ["import-categories"] });
      toast.success(`База рецептов очищена: удалено ${result.recipes.toLocaleString("ru-RU")} рецептов`);
    },
    onError: (error) => toast.error(error.message),
  });
  function confirmClearBase() {
    if (!confirm("Очистить «Базу рецептов» полностью?\n\nБудут удалены все рецепты и категории сайтов, история заданий и их отчёты. Подключённые сайты и их настройки останутся. Рецепты, которые пользователи уже добавили в свои коллекции, не пострадают.\n\nОтменить это действие нельзя.")) return;
    clearBase.mutate();
  }
  const resume = useMutation({ mutationFn: api.imports.resume, onSuccess: (job) => { rememberJob(job); refreshJobs(); toast.success("Создано новое задание; сохранённые рецепты будут пропущены"); }, onError: (error) => toast.error(error.message) });

  function addSource(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    let parsed: RecipeSourceDefinition | undefined;
    if (definition.trim()) {
      try {
        const value: unknown = JSON.parse(definition);
        if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
        parsed = value as RecipeSourceDefinition;
      } catch {
        setFormError("Настройки источника должны быть JSON-объектом.");
        return;
      }
    }
    add.mutate({ name: name.trim() || undefined, catalog_url: catalogUrl.trim(), definition: parsed });
  }

  function startJob(event: FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    const urls = scope === "urls" ? manualUrls.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !line.startsWith("#")) : [];
    if (scope === "urls" && (urls.length === 0 || urls.length > 100)) { toast.error("Укажите от 1 до 100 ссылок, по одной на строку."); return; }
    const requestedLimit = Number(limit);
    if (!Number.isInteger(requestedLimit) || requestedLimit < 0 || requestedLimit > 1000) { toast.error("Укажите 0 без лимита или число от 1 до 1000."); return; }
    if (scope === "category" && !categoryId) { toast.error("Выберите категорию сайта."); return; }
    start.mutate({ source_id: chosen.id, mode: "index", limit: requestedLimit, is_public: false, urls, category_id: scope === "category" ? Number(categoryId) : undefined, no_step_images: true });
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><CardTitle className="flex items-center gap-2"><Globe className="size-5" /> Источники рецептов</CardTitle><CardDescription className="mt-2">Проверка сайтов и наполнение «Базы рецептов». Задания выполняются на сервере.</CardDescription></div>
          <Button type="button" variant="outline" size="sm" disabled={add.isPending} onClick={() => setShowAdd(!showAdd)}><Plus /> Подключить сайт</Button>
        </div>
      </CardHeader>
      <CardContent className="grid gap-6">
        {showAdd && (
          <form onSubmit={addSource} className="grid gap-4 rounded-2xl bg-muted/50 p-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="import-source-url" label="Сайт или каталог" hint="Достаточно адреса сайта. Сервис сам найдёт каталог и проверит рецепт."><Input id="import-source-url" type="url" required disabled={add.isPending} placeholder="https://example.org" value={catalogUrl} onChange={(event) => setCatalogUrl(event.target.value)} /></Field>
              <Field id="import-source-name" label="Название" hint="Необязательно: можно оставить имя сайта."><Input id="import-source-name" disabled={add.isPending} value={name} onChange={(event) => setName(event.target.value)} placeholder="Название источника" maxLength={120} /></Field>
            </div>
            <details className="text-sm"><summary className="cursor-pointer text-muted-foreground">Ручные настройки — необязательно</summary><div className="mt-3"><Field id="import-source-definition" label="Настройки источника в JSON" hint="Оставьте пустым для автоматического определения. Если знаете структуру сайта, здесь можно вручную задать домены, каталог и шаблоны ссылок."><Textarea id="import-source-definition" disabled={add.isPending} className="min-h-40 font-mono text-xs" value={definition} onChange={(event) => setDefinition(event.target.value)} placeholder={'{"canonical_host":"example.org","hosts":["example.org"],"catalog_url":"https://example.org/recipes","recipe_pattern":"/recipe/.+","catalog_pattern":"/recipes"}'} /></Field></div></details>
            {formError && <p role="alert" className="text-sm text-destructive">{formError}</p>}
            {add.isPending ? (
              <p role="status" className="flex items-start gap-2 rounded-xl bg-primary/10 p-3 text-sm"><Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" /><span>{definition.trim() ? "Проверяем настройки и рецепт на сайте." : "Ищем каталог и страницы рецептов, подбираем настройки и проверяем рецепт."} Это может занять некоторое время.</span></p>
            ) : (
              <p className="text-xs text-muted-foreground">Подключение проверит ингредиенты, шаги и доступные фотографии. Если сайт закрыт или формат рецептов не поддерживается, сервис покажет причину.</p>
            )}
            <div className="flex flex-wrap gap-2"><Button type="submit" disabled={add.isPending}>{add.isPending ? <Loader2 className="animate-spin" /> : <Check />} {add.isPending ? "Проверяем сайт…" : definition.trim() ? "Проверить и подключить" : "Определить и подключить"}</Button><Button type="button" variant="ghost" onClick={() => setShowAdd(false)} disabled={add.isPending}>Отмена</Button></div>
          </form>
        )}
        {jobs.isError && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-destructive/10 p-3 text-sm"><p>Не удалось загрузить историю заданий: {jobs.error.message}</p><Button type="button" size="sm" variant="outline" disabled={jobs.isFetching} onClick={() => jobs.refetch()}>Обновить список заданий</Button></div>}
        {activeJob && <p role="status" className="rounded-xl bg-primary/10 p-3 text-sm">Выполняется задание №{activeJob.id}. Дождитесь завершения или остановите его. <a className="font-medium underline underline-offset-4" href="#recipe-import-jobs">Перейти к заданию</a></p>}
        {sources.isLoading ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Загрузка источников…</p> : sources.isError ? <div role="alert" className="rounded-xl bg-destructive/10 p-4 text-sm text-destructive"><p>{sources.error.message}</p><Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => sources.refetch()}>Повторить</Button></div> : (
          <div className="grid gap-3 sm:grid-cols-2">{sources.data?.map((source) => <SourceRow key={source.id} source={source} busy={(check.isPending && check.variables === source.id) || (update.isPending && update.variables.id === source.id) || (remove.isPending && remove.variables === source.id)} onCheck={() => check.mutate(source.id)} canIndex={!start.isPending} onUpdate={(data) => update.mutate({ id: source.id, data })} onIndex={() => start.mutate({ source_id: source.id, mode: "index", limit: 0, is_public: false })} onDelete={() => remove.mutate(source.id)} />)}</div>
        )}
        <form onSubmit={startJob} className="grid gap-4 border-t pt-6">
          <div><h3 className="font-semibold">Добавить рецепты в базу</h3><p className="mt-1 text-sm text-muted-foreground">Рецепты попадают только в «Базу рецептов», без повторов, и не смешиваются с рецептами пользователей.</p></div>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="import-job-source" label="Источник"><Select id="import-job-source" value={sourceId} onChange={(event) => setSourceId(event.target.value)} required><option value="">Выберите проверенный сайт</option>{ready.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</Select></Field>
            <Field id="import-job-scope" label="Что обработать"><Select id="import-job-scope" value={scope} onChange={(event) => setScope(event.target.value as typeof scope)}><option value="site">Весь источник</option><option value="category">Категорию или раздел</option><option value="urls">Отдельные рецепты</option></Select></Field>
            <Field id="import-job-limit" label="Лимит рецептов" hint="0 — без лимита"><Input id="import-job-limit" type="number" min={0} max={1000} required value={limit} onChange={(event) => setLimit(event.target.value)} /></Field>
          </div>
          {scope === "category" && <div className="grid gap-2"><Field id="import-job-category" label="Категория сайта" hint="Категории сохраняются при обновлении каталога."><Select id="import-job-category" required value={categoryId} disabled={categories.isLoading || categories.isError} onChange={(event) => setCategoryId(event.target.value)}><option value="">{categories.isLoading ? "Загрузка категорий…" : "Выберите категорию"}</option>{categories.data?.map((category) => <option key={category.id} value={category.id}>{category.title}{category.recipes_count ? ` (${category.recipes_count})` : ""}</option>)}</Select></Field>{categories.isError && <p role="alert" className="text-sm text-destructive">{categories.error.message}</p>}{!categories.isLoading && !categories.isError && !categories.data?.length && <div className="flex flex-wrap items-center gap-3"><p className="text-sm text-muted-foreground">Категории ещё не загружены. Сначала обновите каталог сайта.</p><Button type="button" size="sm" variant="outline" disabled={!chosen || start.isPending} onClick={() => chosen && start.mutate({ source_id: chosen.id, mode: "index", limit: 0, is_public: false })}>Обновить каталог</Button></div>}</div>}
          {scope === "urls" && <Field id="import-job-urls" label="Ссылки на рецепты" hint="До 100 ссылок выбранного источника, по одной на строку."><Textarea id="import-job-urls" required value={manualUrls} onChange={(event) => setManualUrls(event.target.value)} placeholder="https://…" /></Field>}
          {!ready.length && !sources.isLoading && <p className="text-sm text-muted-foreground">Сначала проверьте и включите хотя бы один источник.</p>}
          <div><Button type="submit" disabled={!chosen || start.isPending || Boolean(activeJob) || jobs.isLoading || jobs.isError}>{start.isPending ? <Loader2 className="animate-spin" /> : <Play />} Добавить в базу</Button></div>
        </form>
        <div id="recipe-import-jobs" className="grid scroll-mt-24 gap-3 border-t pt-6">
          <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">Последние задания</h3><Button type="button" size="sm" variant="ghost" disabled={jobs.isFetching} onClick={() => jobs.refetch()}><RefreshCw className={jobs.isFetching ? "animate-spin" : ""} /> Обновить</Button></div>
          {jobs.isLoading ? <p className="text-sm text-muted-foreground">Загрузка заданий…</p> : jobs.isError && !jobs.data?.length ? <p role="alert" className="text-sm text-destructive">{jobs.error.message}</p> : jobs.data?.length === 0 ? <p className="text-sm text-muted-foreground">Заданий пока нет. Результаты первого запуска появятся здесь.</p> : jobs.data?.map((job) => <JobRow key={job.id} job={job} canStart={!activeJob && !resume.isPending && Boolean(sources.data?.some((source) => source.id === job.source_id && source.enabled && source.verified))} stopping={stop.isPending && stop.variables === job.id} resuming={resume.isPending && resume.variables === job.id} onStop={() => stop.mutate(job.id)} onResume={() => resume.mutate(job.id)} />)}
        </div>
        <div className="grid gap-3 rounded-2xl border border-destructive/40 p-4">
          <div><h3 className="font-semibold text-destructive">Очистить базу рецептов</h3><p className="mt-1 text-sm text-muted-foreground">Удаляет все рецепты и категории сайтов, историю заданий и отчёты. Подключённые сайты остаются, рецепты в коллекциях пользователей не затрагиваются.</p></div>
          <div><Button type="button" variant="destructive" disabled={clearBase.isPending || Boolean(activeJob)} onClick={confirmClearBase}>{clearBase.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />} Очистить БАЗУ РЕЦЕПТОВ</Button></div>
          {activeJob && <p className="text-xs text-muted-foreground">Сначала дождитесь окончания или остановите текущее задание.</p>}
        </div>
      </CardContent>
    </Card>
  );
}
