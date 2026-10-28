/**
 * Тонкий клиент API.
 * access-токен живёт в памяти, refresh — в httpOnly-cookie (веб).
 * При 401 клиент один раз пробует обновить токен и повторяет запрос.
 */

export type User = {
  id: number;
  username: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: string;
  avatar_url: string | null;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
};

export type SetupStatus = {
  database_configured: boolean;
  database_from_env: boolean;
  setup_complete: boolean;
  setup_token_required: boolean;
};

export type RegistrationMode = "open" | "closed";

export type PublicSettings = {
  site_name: string;
  registration_mode: RegistrationMode;
};

export type DatabaseConfig = {
  type: "sqlite" | "mysql";
  host?: string;
  port?: number;
  user?: string;
  password?: string;
  database?: string;
};

export type CategoryRef = { id: number; name: string };
export type Category = CategoryRef & { sort_order: number; recipe_count: number };
export type TagInfo = { name: string; recipe_count: number };

export type Ingredient = {
  id?: number;
  product: string;
  amount: number | null;
  unit: string;
  note: string;
  group: string;
};

export type Step = { id?: number; position?: number; text: string; timer_minutes: number | null };

export type RecipeListItem = {
  id: number;
  title: string;
  description: string;
  image_url: string | null;
  thumb_url: string | null;
  category: CategoryRef | null;
  tags: string[];
  servings: number;
  total_minutes: number | null;
  difficulty: number | null;
  is_public: boolean;
  author: { id: number; name: string; avatar_url: string | null };
  updated_at: string;
  is_favorite: boolean;
  cooked_count: number;
};

export type CookLogEntry = {
  id: number;
  cooked_on: string;
  note: string;
  author: { id: number; name: string; avatar_url: string | null };
  can_delete: boolean;
};

export type NutritionValues = { kcal: number; protein: number; fat: number; carbs: number };
export type Nutrition = {
  per_serving: NutritionValues;
  total: NutritionValues;
  weight_g: number;
  counted: number;
  missing: string[];
};

export type Product = {
  id: number;
  name: string;
  kcal: number | null;
  protein: number | null;
  fat: number | null;
  carbs: number | null;
  piece_grams: number | null;
  density: number | null;
  nutrition_source: "auto" | "user" | null;
  recipe_count: number;
};

export type ProductPatch = Partial<Omit<Product, "id" | "nutrition_source" | "recipe_count">>;

export type Recipe = RecipeListItem & {
  source_url: string | null;
  nutrition: Nutrition | null;
  prep_minutes: number | null;
  cook_minutes: number | null;
  ingredients: Ingredient[];
  steps: Step[];
  can_edit: boolean;
  created_at: string;
  cook_log: CookLogEntry[];
};

export type RecipeInput = {
  title: string;
  description: string;
  category_id: number | null;
  servings: number;
  prep_minutes: number | null;
  cook_minutes: number | null;
  difficulty: number | null;
  is_public: boolean;
  source_url?: string | null;
  image_token?: string | null;
  tags: string[];
  ingredients: Omit<Ingredient, "id">[];
  steps: Omit<Step, "id" | "position">[];
};

export type RecipeDraft = {
  title: string;
  description: string;
  servings: number | null;
  prep_minutes: number | null;
  cook_minutes: number | null;
  category_id: number | null;
  category_name: string;
  tags: string[];
  ingredients: Omit<Ingredient, "id">[];
  steps: { text: string; timer_minutes: number | null }[];
  image_token: string | null;
  image_url: string | null;
  source_url: string;
};

export type RecipeQuery = {
  q?: string;
  category_id?: number;
  tag?: string;
  mine?: boolean;
  favorites?: boolean;
  limit?: number;
  offset?: number;
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let accessToken: string | null = null;
let refreshPromise: Promise<TokenResponse | null> | null = null;
const listeners = new Set<(user: User | null) => void>();

export function onAuthChange(fn: (user: User | null) => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setSession(data: TokenResponse | null) {
  accessToken = data?.access_token ?? null;
  listeners.forEach((fn) => fn(data?.user ?? null));
}

/** Обновить данные текущего пользователя (имя, аватар) без перевыпуска токенов. */
export function updateCurrentUser(user: User) {
  listeners.forEach((fn) => fn(user));
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      const first = detail[0] as { msg?: string; loc?: unknown[] };
      const field = first.loc?.[first.loc.length - 1];
      return field ? `${String(field)}: ${first.msg}` : first.msg ?? fallback;
    }
  }
  return fallback;
}

async function raw<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const res = await fetch(path, { ...init, headers, credentials: "include" });
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null; // например, HTML-страница ошибки от reverse proxy
  }
  if (!res.ok) throw new ApiError(res.status, errorMessage(body, `Ошибка ${res.status}`));
  return body as T;
}

export async function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshPromise) {
    refreshPromise = raw<TokenResponse>("/api/auth/refresh", { method: "POST", body: "{}" })
      .then((data) => {
        setSession(data);
        return data;
      })
      .catch(() => {
        setSession(null);
        return null;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await raw<T>(path, init);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401 && !path.startsWith("/api/auth/")) {
      const refreshed = await refreshSession();
      if (refreshed) return raw<T>(path, init);
    }
    throw err;
  }
}

/** Скачивание файла с авторизацией (обычная ссылка не передаёт Bearer-токен). */
async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const attempt = () =>
    fetch(path, {
      credentials: "include",
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    });
  let res = await attempt();
  if (res.status === 401 && (await refreshSession())) res = await attempt();
  if (!res.ok) throw new ApiError(res.status, `Ошибка ${res.status}`);
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  const name = match ? decodeURIComponent(match[1]) : fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

export type ShoppingItem = { id: number; name: string; amount: number | null; unit: string; note: string; checked: boolean };

export type RestoreResult = { created: number; skipped: number; failed: number; errors: string[] };

const json = (data: unknown) => JSON.stringify(data);

function setupHeaders(token?: string): HeadersInit {
  return token ? { "X-Setup-Token": token } : {};
}

export const api = {
  health: () => request<{ status: string; version: string }>("/api/health"),

  setup: {
    status: () => request<SetupStatus>("/api/setup/status"),
    testDb: (cfg: DatabaseConfig, token?: string) =>
      request<{ ok: true }>("/api/setup/test-db", { method: "POST", body: json(cfg), headers: setupHeaders(token) }),
    database: (cfg: DatabaseConfig, token?: string) =>
      request<{ ok: true }>("/api/setup/database", { method: "POST", body: json(cfg), headers: setupHeaders(token) }),
    admin: (
      data: {
        username: string;
        email: string;
        display_name: string;
        password: string;
        site_name: string;
        registration_mode: RegistrationMode;
      },
      token?: string,
    ) => request<TokenResponse>("/api/setup/admin", { method: "POST", body: json(data), headers: setupHeaders(token) }),
  },

  auth: {
    login: (login: string, password: string, remember = true) =>
      request<TokenResponse>("/api/auth/login", { method: "POST", body: json({ login, password, remember }) }),
    register: (data: { username: string; email: string; display_name: string; password: string }) =>
      request<TokenResponse>("/api/auth/register", { method: "POST", body: json(data) }),
    logout: () => request<{ ok: true }>("/api/auth/logout", { method: "POST" }),
    me: () => request<User>("/api/auth/me"),
  },

  settings: {
    get: () => request<PublicSettings>("/api/settings"),
    update: (data: Partial<PublicSettings>) =>
      request<PublicSettings>("/api/admin/settings", { method: "PATCH", body: json(data) }),
  },

  recipes: {
    list: (params: RecipeQuery = {}) => {
      const qs = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "" && v !== false) qs.set(k, String(v));
      });
      const query = qs.toString();
      return request<{ items: RecipeListItem[]; total: number }>(`/api/recipes${query ? `?${query}` : ""}`);
    },
    get: (id: number) => request<Recipe>(`/api/recipes/${id}`),
    create: (data: RecipeInput) => request<Recipe>("/api/recipes", { method: "POST", body: json(data) }),
    update: (id: number, data: RecipeInput) =>
      request<Recipe>(`/api/recipes/${id}`, { method: "PUT", body: json(data) }),
    remove: (id: number) => request<{ ok: true }>(`/api/recipes/${id}`, { method: "DELETE" }),
    uploadImage: (id: number, file: File) => {
      const form = new FormData();
      form.append("file", file);
      return request<Recipe>(`/api/recipes/${id}/image`, { method: "POST", body: form });
    },
    removeImage: (id: number) => request<Recipe>(`/api/recipes/${id}/image`, { method: "DELETE" }),
    setFavorite: (id: number, on: boolean) =>
      request<{ is_favorite: boolean }>(`/api/recipes/${id}/favorite`, { method: on ? "PUT" : "DELETE" }),
    markCooked: (id: number, data: { cooked_on: string; note: string }) =>
      request<Recipe>(`/api/recipes/${id}/cooked`, { method: "POST", body: json(data) }),
    deleteCooked: (id: number, logId: number) =>
      request<Recipe>(`/api/recipes/${id}/cooked/${logId}`, { method: "DELETE" }),
    importFromUrl: (url: string) =>
      request<RecipeDraft>("/api/recipes/import", { method: "POST", body: json({ url }) }),
  },

  catalog: {
    categories: () => request<Category[]>("/api/categories"),
    createCategory: (name: string) =>
      request<Category>("/api/categories", { method: "POST", body: json({ name }) }),
    updateCategory: (id: number, data: { name: string; sort_order: number }) =>
      request<Category>(`/api/categories/${id}`, { method: "PATCH", body: json(data) }),
    deleteCategory: (id: number) => request<{ ok: true }>(`/api/categories/${id}`, { method: "DELETE" }),
    tags: () => request<TagInfo[]>("/api/tags"),
    products: () => request<string[]>("/api/products"),
    productCatalog: () => request<Product[]>("/api/products/catalog"),
    updateProduct: (id: number, data: ProductPatch) =>
      request<Product>(`/api/products/${id}`, { method: "PATCH", body: json(data) }),
    mergeProduct: (id: number, intoId: number) =>
      request<Product>(`/api/products/${id}/merge`, { method: "POST", body: json({ into_id: intoId }) }),
    deleteProduct: (id: number) => request<{ ok: true }>(`/api/products/${id}`, { method: "DELETE" }),
  },

  me: {
    update: (data: { display_name?: string; email?: string }) =>
      request<User>("/api/me", { method: "PATCH", body: json(data) }),
    changePassword: (current_password: string, new_password: string) =>
      request<TokenResponse>("/api/me/password", { method: "POST", body: json({ current_password, new_password }) }),
    uploadAvatar: (blob: Blob) => {
      const form = new FormData();
      form.append("file", blob, "avatar.jpg");
      return request<User>("/api/me/avatar", { method: "POST", body: form });
    },
    removeAvatar: () => request<User>("/api/me/avatar", { method: "DELETE" }),
  },

  shopping: {
    list: () => request<ShoppingItem[]>("/api/shopping"),
    fromRecipe: (recipe_id: number, servings: number, ingredient_ids?: number[]) =>
      request<{ added: number; merged: number; items: ShoppingItem[] }>("/api/shopping/from-recipe", {
        method: "POST",
        body: json({ recipe_id, servings, ingredient_ids }),
      }),
    addText: (text: string) => request<ShoppingItem[]>("/api/shopping/items", { method: "POST", body: json({ text }) }),
    update: (id: number, data: Partial<Omit<ShoppingItem, "id" | "note">>) =>
      request<ShoppingItem>(`/api/shopping/items/${id}`, { method: "PATCH", body: json(data) }),
    remove: (id: number) => request<{ ok: true }>(`/api/shopping/items/${id}`, { method: "DELETE" }),
    clear: (checkedOnly: boolean) =>
      request<ShoppingItem[]>(`/api/shopping/clear?checked_only=${checkedOnly}`, { method: "POST" }),
  },

  backup: {
    download: () => downloadFile("/api/backup/export", "recipes.zip"),
    restore: (file: File, skipDuplicates = true) => {
      const form = new FormData();
      form.append("file", file);
      return request<RestoreResult>(`/api/backup/import?skip_duplicates=${skipDuplicates}`, {
        method: "POST",
        body: form,
      });
    },
  },

  admin: {
    users: () => request<User[]>("/api/admin/users"),
    createUser: (data: { username: string; email: string; display_name: string; password: string; is_admin: boolean }) =>
      request<User>("/api/admin/users", { method: "POST", body: json(data) }),
    resetPassword: (id: number, password: string) =>
      request<{ ok: true }>(`/api/admin/users/${id}/password`, { method: "POST", body: json({ password }) }),
    updateUser: (id: number, data: { is_admin?: boolean; is_active?: boolean }) =>
      request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: json(data) }),
  },
};
