import { useState, type MouseEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Heart } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { saveRecipeOffline } from "@/lib/offline";
import { cn } from "@/lib/utils";

/** Сердечко «в избранное». Переключается сразу, сервер — в фоне. */
export function FavoriteButton({
  recipeId,
  initial,
  className,
  size = "md",
}: {
  recipeId: number;
  initial: boolean;
  className?: string;
  size?: "sm" | "md";
}) {
  const queryClient = useQueryClient();
  const [on, setOn] = useState(initial);

  const toggle = async (e: MouseEvent) => {
    e.preventDefault(); // кнопка внутри карточки-ссылки
    e.stopPropagation();
    const next = !on;
    setOn(next);
    try {
      await api.recipes.setFavorite(recipeId, next);
      if (next) {
        saveRecipeOffline(recipeId);
        toast.success("В избранном", { description: "Рецепт сохранён на устройство и откроется без интернета" });
      }
      queryClient.invalidateQueries({ queryKey: ["recipes"] });
      queryClient.invalidateQueries({ queryKey: ["recipe", recipeId] });
    } catch (err) {
      setOn(!next);
      toast.error((err as Error).message);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? "Убрать из избранного" : "В избранное"}
      title={on ? "Убрать из избранного" : "В избранное"}
      className={cn(
        "flex items-center justify-center rounded-full transition-[transform,background-color] active:scale-90",
        size === "sm" ? "size-8 bg-background/85 backdrop-blur-md" : "size-10 border bg-card hover:bg-muted",
        className,
      )}
    >
      <Heart
        className={cn(size === "sm" ? "size-4" : "size-[18px]", on ? "fill-primary text-primary" : "text-foreground/70")}
        strokeWidth={2}
      />
    </button>
  );
}
