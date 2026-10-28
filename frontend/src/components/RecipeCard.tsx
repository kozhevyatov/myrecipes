import { Link } from "react-router";
import { CalendarCheck, Clock, Lock, Users, UtensilsCrossed } from "lucide-react";
import { FavoriteButton } from "@/components/FavoriteButton";
import { Tag } from "@/components/ui/chip";
import type { RecipeListItem } from "@/lib/api";
import { formatMinutes } from "@/lib/format";

export function RecipeImage({ src, alt, className = "" }: { src: string | null; alt: string; className?: string }) {
  if (src) return <img src={src} alt={alt} loading="lazy" className={`h-full w-full object-cover ${className}`} />;
  return (
    <div className={`flex h-full w-full items-center justify-center bg-accent ${className}`}>
      <UtensilsCrossed className="size-9 text-primary/35" strokeWidth={1.5} />
    </div>
  );
}

export function RecipeCard({ recipe }: { recipe: RecipeListItem }) {
  const time = formatMinutes(recipe.total_minutes);
  return (
    <Link
      to={`/recipes/${recipe.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border bg-card transition-[box-shadow,border-color] outline-none hover:border-foreground/15 hover:shadow-[0_8px_24px_-12px_rgb(0_0_0/0.18)] focus-visible:ring-4 focus-visible:ring-ring"
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-muted">
        <RecipeImage
          src={recipe.thumb_url ?? recipe.image_url}
          alt={recipe.title}
          className="transition-transform duration-700 ease-out group-hover:scale-[1.04]"
        />
        {recipe.category && (
          <span className="absolute top-3 left-3 rounded-full bg-background/85 px-2.5 py-1 text-xs font-medium backdrop-blur-md">
            {recipe.category.name}
          </span>
        )}
        <div className="absolute top-3 right-3 flex items-center gap-1.5">
          {!recipe.is_public && (
            <span className="rounded-full bg-background/85 p-2 backdrop-blur-md" title="Только для вас">
              <Lock className="size-3.5" />
            </span>
          )}
          <FavoriteButton key={`${recipe.id}-${recipe.is_favorite}`} recipeId={recipe.id} initial={recipe.is_favorite} size="sm" />
        </div>
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <h3 className="line-clamp-2 text-[16px] leading-snug font-semibold group-hover:text-primary">{recipe.title}</h3>
        {recipe.description && <p className="line-clamp-2 text-sm text-muted-foreground">{recipe.description}</p>}
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-0.5 text-xs text-muted-foreground">
          {time && (
            <span className="flex items-center gap-1">
              <Clock className="size-3.5" /> {time}
            </span>
          )}
          <span className="flex items-center gap-1">
            <Users className="size-3.5" /> {recipe.servings}
          </span>
          {recipe.cooked_count > 0 && (
            <span className="flex items-center gap-1" title="Сколько раз готовили">
              <CalendarCheck className="size-3.5" /> {recipe.cooked_count}
            </span>
          )}
          {recipe.tags.slice(0, 2).map((t) => (
            <Tag key={t}>{t}</Tag>
          ))}
        </div>
      </div>
    </Link>
  );
}
