import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Link2, Link2Off, Loader2, Share2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { api, type Recipe } from "@/lib/api";

/** Публичная ссылка на рецепт: открывается без входа, её можно выключить. */
export function ShareSheet({ recipe, onClose }: { recipe: Recipe; onClose: () => void }) {
  const queryClient = useQueryClient();
  const url = recipe.share_url ? `${location.origin}${recipe.share_url}` : null;

  const toggle = useMutation({
    mutationFn: (on: boolean) => api.recipes.share(recipe.id, on),
    onSuccess: (r) => {
      queryClient.setQueryData<Recipe>(["recipe", recipe.id], (old) => (old ? { ...old, share_url: r.share_url } : old));
      if (!r.share_url) toast.success("Ссылка выключена", { description: "Тот, у кого она есть, больше не откроет рецепт" });
    },
    onError: (e) => toast.error(e.message),
  });

  async function copy() {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Ссылка скопирована");
    } catch {
      toast.error("Не получилось скопировать — выделите ссылку вручную");
    }
  }

  async function share() {
    if (!url) return;
    try {
      await navigator.share({ title: recipe.title, url });
    } catch {
      /* закрыли окно «Поделиться» */
    }
  }

  return (
    <Sheet title="Поделиться рецептом" onClose={onClose}>
      {url ? (
        <div className="grid gap-4">
          <p className="text-sm text-muted-foreground">
            Рецепт откроется у любого, у кого есть ссылка, — без входа в аккаунт. Отметки «готовил» и избранное никто не
            увидит.
          </p>
          <Input readOnly value={url} onFocus={(e) => e.target.select()} className="text-sm" />
          <div className="flex flex-wrap gap-2">
            {"share" in navigator && (
              <Button onClick={share}>
                <Share2 /> Отправить
              </Button>
            )}
            <Button variant={"share" in navigator ? "outline" : "default"} onClick={copy}>
              <Copy /> Скопировать
            </Button>
            <Button
              variant="ghost"
              className="ml-auto text-destructive hover:text-destructive"
              disabled={toggle.isPending}
              onClick={() => toggle.mutate(false)}
            >
              {toggle.isPending ? <Loader2 className="animate-spin" /> : <Link2Off />} Выключить
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-4">
          <p className="text-sm text-muted-foreground">
            Создайте ссылку, чтобы отправить рецепт тем, у кого нет аккаунта: друзьям, в чат, в соцсети. Ссылку можно
            выключить в любой момент.
          </p>
          <Button className="justify-self-start" disabled={toggle.isPending} onClick={() => toggle.mutate(true)}>
            {toggle.isPending ? <Loader2 className="animate-spin" /> : <Link2 />} Создать ссылку
          </Button>
        </div>
      )}
    </Sheet>
  );
}
