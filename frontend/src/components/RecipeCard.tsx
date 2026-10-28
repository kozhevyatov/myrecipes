import { Link } from "react-router";
import { Clock, Lock, Users, UtensilsCrossed } from "lucide-react";
import { Tag } from "@/components/ui/chip";
import type { RecipeListItem } from "@/lib/api";
import { formatMinutes } from "@/lib/format";

export function RecipeImage({ src, alt, className = "" }: { src: string | null; alt: string; className?: string }) {
  if (src) return <img src={src} alt={alt} loading="lazy" className={`h-full w-full object-cover ${className}`} />;
  return (
    <div className={`flex h-full w-full items-center justify-center bg-accent ${className}`}>
      <UtensilsCrossed className="size-10 text-primary/40" />
    </div>
  );
}

export function RecipeCard({ recipe }: { recipe: RecipeListItem }) {
  const time = formatMinutes(recipe.total_minutes);
  return (
    <Link
      to={`/recipes/${recipe.id}`}
      className="group flex flex-col overflow-hidden rounded-2xl border bg-card shadow-sm transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="relative aspect-[4/3] overflow-hidden">
        <RecipeImage
          src={recipe.image_url}
          alt={recipe.title}
          className="transition-transform duration-500 group-hover:scale-[1.03]"
        />
        {recipe.category && (
          <span className="absolute top-3 left-3 rounded-full bg-background/90 px-2.5 py-1 text-xs font-bold backdrop-blur">
            {recipe.category.name}
          </span>
        )}
        {!recipe.is_public && (
          <span className="absolute top-3 right-3 rounded-full bg-background/90 p-1.5 backdrop-blur" title="Только для вас">
            <Lock className="size-3.5" />
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="line-clamp-2 text-base leading-snug font-bold">{recipe.title}</h3>
        {recipe.description && <p className="line-clamp-2 text-sm text-muted-foreground">{recipe.description}</p>}
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-1 text-xs font-semibold text-muted-foreground">
          {time && (
            <span className="flex items-center gap-1">
              <Clock className="size-3.5" /> {time}
            </span>
          )}
          <span className="flex items-center gap-1">
            <Users className="size-3.5" /> {recipe.servings}
          </span>
          {recipe.tags.slice(0, 3).map((t) => (
            <Tag key={t}>#{t}</Tag>
          ))}
        </div>
      </div>
    </Link>
  );
}
