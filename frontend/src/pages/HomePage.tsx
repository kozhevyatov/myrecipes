import { ChefHat, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user } = useAuth();
  const name = user?.display_name || user?.username;

  return (
    <div className="grid gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-primary">Привет, {name}!</p>
          <h1 className="mt-1 text-3xl font-extrabold sm:text-4xl">Рецепты</h1>
        </div>
        <Button size="lg" disabled title="Появится на следующем этапе">
          <Plus /> Новый рецепт
        </Button>
      </div>

      <div className="relative">
        <Search className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input className="h-12 rounded-xl pl-11" placeholder="Поиск по названию, тегу или ингредиенту" disabled />
      </div>

      <div className="flex flex-col items-center rounded-3xl border border-dashed bg-card/50 px-6 py-20 text-center">
        <div className="rounded-2xl bg-accent p-4">
          <ChefHat className="size-8 text-primary" />
        </div>
        <h2 className="mt-5 text-xl font-bold">Здесь пока пусто</h2>
        <p className="mt-2 max-w-sm text-sm text-muted-foreground">
          Скоро тут появятся ваши рецепты: с фото, ингредиентами в граммах и пошаговым приготовлением.
        </p>
      </div>
    </div>
  );
}
