import { useState } from "react";
import { Link } from "react-router";
import { Check, Globe, UtensilsCrossed } from "lucide-react";
import type { SiteRecipe } from "@/lib/api";

export function SiteRecipeImage({ src, alt, className = "" }: { src: string | null; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (src && !failed) return <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} className={`h-full w-full object-cover ${className}`} />;
  return <div className={`flex h-full w-full items-center justify-center bg-accent ${className}`}><UtensilsCrossed className="size-10 text-primary/35" strokeWidth={1.5} /></div>;
}

export function SiteRecipeCard({ recipe }: { recipe: SiteRecipe }) {
  return (
    <Link to={`/site-recipes/${recipe.id}`} className="group flex flex-col overflow-hidden rounded-2xl border bg-card transition-[box-shadow,border-color] outline-none hover:border-foreground/15 hover:shadow-[0_8px_24px_-12px_rgb(0_0_0/0.18)] focus-visible:ring-4 focus-visible:ring-ring">
      <div className="relative aspect-[4/3] overflow-hidden bg-muted">
        <SiteRecipeImage key={recipe.image_url} src={recipe.image_url} alt={recipe.title} className="transition-transform duration-700 ease-out group-hover:scale-[1.04]" />
        {recipe.category && <span className="absolute top-3 left-3 max-w-[85%] truncate rounded-full bg-background/85 px-2.5 py-1 text-xs font-medium backdrop-blur-md">{recipe.category.title}</span>}
        {recipe.imported_recipe_id && <span className="absolute right-3 bottom-3 inline-flex items-center gap-1 rounded-full bg-background/90 px-2.5 py-1 text-xs font-medium"><Check className="size-3" /> В коллекции</span>}
      </div>
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="line-clamp-2 text-base leading-snug font-semibold group-hover:text-primary">{recipe.title}</h3>
        {recipe.description && <p className="line-clamp-2 text-sm text-muted-foreground">{recipe.description}</p>}
        <p className="mt-auto flex items-center gap-1.5 pt-1 text-xs text-muted-foreground"><Globe className="size-3.5 shrink-0" /><span className="truncate">{recipe.source_name}</span></p>
      </div>
    </Link>
  );
}
