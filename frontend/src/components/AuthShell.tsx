import type { ReactNode } from "react";
import { Brand } from "./Logo";

/** Обёртка для страниц входа/регистрации/настройки: форма слева, тёплая панель справа. */
export function AuthShell({
  siteName = "Мои рецепты",
  title,
  subtitle,
  children,
  aside,
}: {
  siteName?: string;
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="grid min-h-svh lg:grid-cols-[1fr_minmax(0,0.9fr)]">
      <div className="flex flex-col px-5 py-8 sm:px-10">
        <Brand name={siteName} />
        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10">
          <h1 className="text-3xl font-extrabold">{title}</h1>
          {subtitle && <p className="mt-2 text-muted-foreground">{subtitle}</p>}
          <div className="mt-8">{children}</div>
        </div>
      </div>

      <aside className="relative hidden overflow-hidden bg-primary lg:block">
        <div
          className="absolute inset-0 opacity-25"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, white 0 2px, transparent 3px), radial-gradient(circle at 70% 60%, white 0 1.5px, transparent 2.5px)",
            backgroundSize: "48px 48px, 36px 36px",
          }}
        />
        <div className="absolute -right-24 -bottom-24 size-[28rem] rounded-full bg-white/10" />
        <div className="absolute -top-16 -left-16 size-72 rounded-full bg-black/10" />
        <div className="relative flex h-full flex-col justify-end p-12 text-primary-foreground">
          {aside ?? (
            <>
              <p className="text-4xl leading-tight font-extrabold">
                Все любимые рецепты —<br />в одной тетрадке.
              </p>
              <p className="mt-4 max-w-sm text-primary-foreground/80">
                Ингредиенты в граммах, пошаговое приготовление, теги и категории. Без рекламы и лишнего шума.
              </p>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
