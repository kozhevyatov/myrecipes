import { Loader2 } from "lucide-react";
import { Logo } from "./Logo";

export function FullScreenLoader({ error }: { error?: string }) {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <Logo className="size-12" />
      {error ? (
        <p className="max-w-sm text-sm text-muted-foreground">{error}</p>
      ) : (
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      )}
    </div>
  );
}
