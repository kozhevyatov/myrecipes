import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, Clock, Download, ExternalLink, Globe, Loader2, Users } from "lucide-react";
import { toast } from "sonner";
import { SiteRecipeImage } from "@/components/SiteRecipeCard";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/chip";
import { api } from "@/lib/api";
import { formatAmount, formatMinutes, formatServings } from "@/lib/format";

export default function SiteRecipePage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const recipe = useQuery({ queryKey: ["site-recipes", "detail", id], queryFn: () => api.siteRecipes.get(id), enabled: Number.isInteger(id) && id > 0 });
  const save = useMutation({
    mutationFn: () => api.siteRecipes.import(id),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["site-recipes"] });
      queryClient.invalidateQueries({ queryKey: ["import-sources"] });
      toast.success(result.already_imported ? "Рецепт уже есть в вашей коллекции" : "Рецепт импортирован в вашу коллекцию");
      if (result.warnings?.length) toast.warning(result.warnings.join(" "));
      navigate(`/recipes/${result.recipe_id}`);
    },
    onError: (error) => toast.error(error.message),
  });
  if (!Number.isInteger(id) || id < 1) return <p role="alert" className="text-destructive">Некорректная ссылка на рецепт.</p>;
  if (recipe.isLoading) return <div className="flex justify-center py-20"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>;
  if (recipe.isError || !recipe.data) return <div className="grid justify-items-start gap-4"><Button asChild variant="ghost"><Link to="/?view=sites"><ArrowLeft /> К рецептам сайтов</Link></Button><p role="alert" className="text-destructive">{recipe.error?.message ?? "Рецепт недоступен"}</p><Button variant="outline" onClick={() => recipe.refetch()}>Повторить</Button></div>;
  const item = recipe.data;
  const totalMinutes = item.prep_minutes != null || item.cook_minutes != null ? (item.prep_minutes ?? 0) + (item.cook_minutes ?? 0) : null;
  return (
    <article className="grid gap-8">
      <div className="flex flex-wrap items-center justify-between gap-3"><Button asChild variant="ghost"><Link to="/?view=sites"><ArrowLeft /> К рецептам сайтов</Link></Button><a href={item.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><Globe className="size-4" /> {item.source_name}<ExternalLink className="size-3.5" /></a></div>
      <div className="grid items-start gap-6 lg:grid-cols-2"><div className="aspect-[4/3] overflow-hidden rounded-3xl bg-muted"><SiteRecipeImage key={item.image_url} src={item.image_url} alt={item.title} /></div><div className="grid gap-5"><div><p className="mb-3 text-sm text-muted-foreground">Рецепт с подключённого сайта</p><h1 className="title-display text-3xl leading-tight sm:text-4xl">{item.title}</h1></div>{item.description && <p className="whitespace-pre-line leading-relaxed text-muted-foreground">{item.description}</p>}<div className="flex flex-wrap gap-4 text-sm text-muted-foreground">{formatMinutes(totalMinutes) && <span className="inline-flex items-center gap-1.5"><Clock className="size-4" />{formatMinutes(totalMinutes)}</span>}{item.servings != null && <span className="inline-flex items-center gap-1.5"><Users className="size-4" />{formatServings(item.servings)}</span>}</div>{item.tags.length > 0 && <div className="flex flex-wrap gap-2">{item.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</div>}<div className="rounded-2xl border bg-card p-4">{item.imported_recipe_id ? <><p className="mb-3 text-sm text-muted-foreground">Этот рецепт уже сохранён в вашей коллекции.</p><Button asChild><Link to={`/recipes/${item.imported_recipe_id}`}><Check /> Открыть в коллекции</Link></Button></> : <><p className="mb-3 text-sm text-muted-foreground">Пока вы просматриваете рецепт источника. Импорт сохранит его в вашу личную коллекцию с доступными фотографиями.</p><Button disabled={save.isPending} onClick={() => save.mutate()}>{save.isPending ? <Loader2 className="animate-spin" /> : <Download />} {save.isPending ? "Импортируем…" : "Импортировать рецепт"}</Button></>}</div></div></div>
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.5fr)]"><section className="rounded-2xl border bg-card p-5"><h2 className="text-xl font-semibold">Ингредиенты</h2><ul className="mt-5 grid gap-3">{item.ingredients.map((ingredient, index) => <li key={index} className="flex items-baseline justify-between gap-4 border-b border-dashed pb-3 last:border-0 last:pb-0"><div><span>{ingredient.product}</span>{ingredient.group && <p className="text-xs text-muted-foreground">{ingredient.group}</p>}{ingredient.note && <p className="mt-1 text-xs text-muted-foreground">{ingredient.note}</p>}</div><span className="shrink-0 text-sm text-muted-foreground">{[formatAmount(ingredient.amount, ingredient.unit), ingredient.unit].filter(Boolean).join(" ")}</span></li>)}</ul></section><section><h2 className="mb-5 text-xl font-semibold">Приготовление</h2><ol className="grid gap-7">{item.steps.map((step, index) => <li key={index} className="grid gap-3"><div className="flex items-start gap-3"><span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{index + 1}</span><p className="pt-1 whitespace-pre-line leading-relaxed">{step.text}</p></div>{step.image_url && <div className="ml-11 aspect-[4/3] max-w-xl overflow-hidden rounded-2xl bg-muted"><SiteRecipeImage key={step.image_url} src={step.image_url} alt={`Шаг ${index + 1}`} /></div>}</li>)}</ol></section></div>
    </article>
  );
}
