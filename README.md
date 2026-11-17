<div align="center">

<img src="frontend/public/favicon.svg" width="72" alt="">

# Мои рецепты

**Self-hosted кулинарная книга для дома и семьи.**
Рецепты с ингредиентами в граммах, режим готовки, КБЖУ и себестоимость, меню на неделю и общие списки покупок. Один Docker-контейнер, без рекламы и облаков.

![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![SQLite | MySQL | MariaDB](https://img.shields.io/badge/DB-SQLite%20%7C%20MySQL%20%7C%20MariaDB-003B57)

<img src="docs/screenshot.png" alt="Главный экран «Мои рецепты»" width="900">

</div>

---

## Возможности

### 📖 Рецепты
- Ингредиенты в граммах, миллилитрах или штуках. Шаги приготовления с фотографиями.
- Главное фото, галерея и просмотр фото на весь экран.
- Категории, теги, поиск и фильтры.
- **Пересчёт порций**: количество каждого ингредиента меняется автоматически.
- **Режим готовки**: шаги по одному, крупный шрифт, таймеры на шагах. Пока он открыт, экран не гаснет.
- Печать рецепта в аккуратном виде, без интерфейса.
- **Публичная ссылка**: рецептом можно поделиться с человеком без аккаунта, а потом закрыть доступ.
- Избранное и журнал «Готовил»: когда и сколько раз готовили блюдо.

### ⚡ Импорт рецептов
- **По ссылке** с любого кулинарного сайта с разметкой schema.org/Recipe (её использует большинство крупных сайтов).
- **Из текста**: можно вставить рецепт из Telegram или заметок. Разбор понимает разделы «Ингредиенты» / «Приготовление», а если их нет, сам отделяет ингредиенты от шагов.
- **Со скриншота**: текст распознаётся через OCR (Tesseract, русский и английский).
- Результат импорта сначала открывается в редакторе, его можно поправить перед сохранением.

### 🥗 Справочник продуктов, КБЖУ и стоимость
- Общий справочник продуктов. Для частых продуктов КБЖУ уже заполнено встроенными данными, любое значение можно изменить.
- **КБЖУ рецепта**: на порцию и на 100 г. Учитываются вес одной штуки и плотность продукта (мл → г).
- **Себестоимость**: по цене упаковки считается стоимость рецепта и порции. Хранится история изменения стоимости. Если цена старше 120 дней, появляется напоминание её обновить.
- **Защита от дублей**: «Масло сливочное», «Сливочное масло» и «Размягчённое сливочное масло» считаются одним продуктом. Похожие продукты можно объединить, старое название останется синонимом.

### 🛒 Планирование и покупки
- **Несколько списков покупок с общим доступом**: например, общий семейный список. Отметки синхронизируются, а без сети список работает и отправляет изменения потом.
- Ингредиенты рецепта добавляются в список одной кнопкой, одинаковые продукты складываются.
- **Меню на неделю** по дням и приёмам пищи, общее для семьи. Список покупок на всю неделю собирается одной кнопкой.
- **«Что есть дома»**: продукты, которые уже есть. По ним подбираются рецепты, и эти продукты можно не добавлять в список покупок.
- **«Что приготовить?»**: случайный рецепт с учётом фильтров.

### 👥 Пользователи и администрирование
- Мастер первого запуска: выбор базы данных и создание администратора.
- Регистрация открыта или закрыта, администратор сам создаёт пользователей и сбрасывает им пароли.
- Профиль с аватаром (с кадрированием), смена пароля, выход со всех устройств.
- Защита входа от перебора паролей, пароли хранятся в argon2.
- **Резервная копия**: zip с рецептами (JSON) и фотографиями, восстанавливается на любом сервере.

### 📱 Интерфейс
- Адаптивный: на телефоне работает как приложение. Это PWA, его можно установить на главный экран и пользоваться без сети.
- 6 тем оформления: светлые «Крем», «Голубика», «Розмарин» и тёмные «Уголь», «Слива», «Базилик».
- REST API с документацией Swagger по адресу `/docs`.

---

## Установка через Docker

Готовый образ публикуется в GitHub Container Registry:

```
ghcr.io/kozhevyatov/myrecipes:latest
```

Образ собран для `linux/amd64`. Приложение слушает порт **1331**. Все данные хранятся в томе `/data`: конфиг, секретный ключ, фотографии, а при SQLite и сама база.

Выберите один из трёх вариантов, сохраните его как `docker-compose.yml` и запустите. Готовые файлы с комментариями лежат в папке [`examples/`](examples/):

```bash
docker compose up -d
```

Потом откройте `http://<сервер>:1331`. Если база не задана заранее, откроется мастер настройки.

### Вариант 1. SQLite (самый простой)

Файл: [`examples/docker-compose.sqlite.example.yml`](examples/docker-compose.sqlite.example.yml)

База хранится в файле `./data/recipes.db`, отдельный сервер БД не нужен. Подходит для дома и семьи.

```yaml
services:
  app:
    image: ghcr.io/kozhevyatov/myrecipes:latest
    container_name: myrecipes
    restart: unless-stopped
    ports:
      - "1331:1331"
    volumes:
      - ./data:/data
    environment:
      TZ: Europe/Moscow
      # Защита мастера первого запуска (рекомендуется, если сервер доступен из интернета)
      # SETUP_TOKEN: "придумайте-длинную-строку"
```

В мастере выберите **SQLite**, затем создайте администратора.

### Вариант 2. Уже существующая MySQL / MariaDB

Файл: [`examples/docker-compose.external-db.example.yml`](examples/docker-compose.external-db.example.yml)

Если сервер базы данных у вас уже есть, сначала создайте базу и пользователя:

```sql
CREATE DATABASE recipes CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'recipes'@'%' IDENTIFIED BY 'надёжный-пароль';
GRANT ALL PRIVILEGES ON recipes.* TO 'recipes'@'%';
FLUSH PRIVILEGES;
```

**a) База запущена в Docker на том же сервере.** Подключите приложение к её Docker-сети и обращайтесь к базе по имени контейнера:

```yaml
services:
  app:
    image: ghcr.io/kozhevyatov/myrecipes:latest
    container_name: myrecipes
    restart: unless-stopped
    ports:
      - "1331:1331"
    volumes:
      - ./data:/data
    networks:
      - db
    environment:
      TZ: Europe/Moscow
      DATABASE_URL: "mysql+pymysql://recipes:надёжный-пароль@db:3306/recipes?charset=utf8mb4"

networks:
  db:
    external: true
    name: db   # имя сети, в которой работает контейнер базы
```

**b) База на другом сервере.** Сеть не нужна, в `DATABASE_URL` укажите адрес сервера:

```yaml
    environment:
      DATABASE_URL: "mysql+pymysql://recipes:надёжный-пароль@192.168.1.10:3306/recipes?charset=utf8mb4"
```

Когда `DATABASE_URL` задан, шаг выбора базы в мастере пропускается и остаётся только создание администратора. Можно не задавать `DATABASE_URL` и указать параметры подключения в мастере. Таблицы создаются и обновляются автоматически при каждом запуске.

> Спецсимволы в пароле (`@`, `:`, `/`, `#`) в `DATABASE_URL` нужно экранировать: `@` → `%40`, `:` → `%3A` и т. д.

### Вариант 3. Всё в одном: приложение + MariaDB

Файлы: [`examples/docker-compose.mariadb.example.yml`](examples/docker-compose.mariadb.example.yml) и [`examples/.env.example`](examples/.env.example)

Один compose поднимает приложение и отдельный контейнер MariaDB. Подходит, если базы ещё нет, а SQLite не устраивает.

```yaml
services:
  app:
    image: ghcr.io/kozhevyatov/myrecipes:latest
    container_name: myrecipes
    restart: unless-stopped
    ports:
      - "1331:1331"
    volumes:
      - ./data:/data
    environment:
      TZ: Europe/Moscow
      DATABASE_URL: "mysql+pymysql://recipes:${DB_PASSWORD}@db:3306/recipes?charset=utf8mb4"
    depends_on:
      db:
        condition: service_healthy

  db:
    image: mariadb:11
    container_name: myrecipes-db
    restart: unless-stopped
    volumes:
      - ./mysql:/var/lib/mysql
    environment:
      MARIADB_DATABASE: recipes
      MARIADB_USER: recipes
      MARIADB_PASSWORD: ${DB_PASSWORD}
      MARIADB_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
      MARIADB_CHARACTER_SET_SERVER: utf8mb4
      MARIADB_COLLATION_SERVER: utf8mb4_unicode_ci
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 10
```

Рядом с `docker-compose.yml` создайте файл `.env` с паролями:

```env
DB_PASSWORD=надёжный-пароль
DB_ROOT_PASSWORD=ещё-более-надёжный-пароль
```

Порт базы наружу не открыт, MariaDB доступна только приложению.

### Сборка из исходников

Вместо готового образа можно собрать свой:

```bash
git clone https://github.com/kozhevyatov/myrecipes.git
cd myrecipes
```

В любом из вариантов выше замените `image: ghcr.io/kozhevyatov/myrecipes:latest` на `build: .` и запустите `docker compose up -d --build`. Так образ соберётся и под ARM, например для Raspberry Pi или Apple Silicon.

### Обновление

```bash
docker compose pull && docker compose up -d
```

Миграции базы выполняются автоматически при запуске.

---

## HTTPS и обратный прокси

Приложение можно поставить за любой обратный прокси: Nginx, Nginx Proxy Manager, Traefik, Caddy или обратный прокси Synology DSM. Его нужно направить на `http://<сервер>:1331`. Заголовки `X-Forwarded-*` учитываются, поэтому за HTTPS cookie сессии автоматически получают флаг `Secure`.

Перед первым запуском на публичном домене задайте `SETUP_TOKEN`. Пока администратор не создан, мастер настройки откроет любой, кто знает адрес. С токеном мастер его запросит.

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DATABASE_URL` | — | Строка подключения к БД. Если задана, шаг выбора БД в мастере пропускается |
| `SETUP_TOKEN` | — | Токен для защиты мастера первого запуска |
| `SECRET_KEY` | генерируется | Ключ подписи JWT. Если не задан, генерируется и хранится в `/data/secret.key` |
| `ACCESS_TOKEN_MINUTES` | `15` | Время жизни access-токена |
| `REFRESH_TOKEN_DAYS` | `30` | Время жизни сессии |
| `COOKIE_SECURE` | `auto` | `auto` / `true` / `false`: флаг Secure для cookie |
| `PORT` | `1331` | Внутренний порт приложения |
| `TZ` | — | Часовой пояс контейнера |

Примеры `DATABASE_URL`:

```
sqlite:////data/recipes.db
mysql+pymysql://user:password@host:3306/recipes?charset=utf8mb4
```

## Резервное копирование

- Сохраняйте папку `./data`: в ней конфиг, ключ, фотографии, а при SQLite и сама база.
- Если используете MySQL/MariaDB, бэкапьте и её: при варианте 3 это папка `./mysql` или `mysqldump`.
- Administrators can export a ZIP with recipes and photos from **Управление → Резервная копия** and import it on another server. Users and settings are not included in the archive.

### Recipe search

Collection search (`GET /api/recipes?q=...`) matches recipe titles and tags only.
Descriptions, ingredients and preparation steps do not contribute matches.
Each of the first six query words must match a title or tag, regardless of case;
SQL wildcard characters are treated literally. Exact titles appear first, then
recipes with more query words in their title. Ties use the latest update and
recipe ID, so pagination has a stable order. Searching without a query retains
the usual latest-update order. Use **Что есть дома** for ingredient-based selection.

The collection search field stays below the header while scrolling. Typing at
least two characters shows up to eight matching tags, including cuisines, with
recipe counts. Selecting a suggestion adds the tag and clears the typed query;
free-text search remains available within the selected tags. Tags can be selected
together and removed individually: recipes must have **all** selected tags.
Suggestions and counts respect the user's recipe visibility and the selected
tags, category, source, personal-recipes and favorites filters. Counts describe
the result after selecting that tag, without the text being typed. Suggestions
are available while online.

`GET /api/recipes` accepts repeated `tags` query parameters for this intersection;
the existing single `tag` parameter remains supported and combines with them.
`GET /api/tags/suggestions` returns the existing `{name, recipe_count}` tag shape
and accepts `q`, repeated `tags`, legacy `tag`, `category_id`, `source_id`, `mine`,
`favorites` and `limit` (1–8, default 8). Queries shorter than two trimmed characters
return no suggestions. Tag names are matched literally without case sensitivity;
case and surrounding-space variants are grouped, counting each recipe once.
Both endpoints accept up to 20 selected tags of at most 64 characters each.

### Recipe sources and imports in the admin interface

Administrators can manage collection under **Управление → Источники рецептов**.
The service uses the same parser, verified TLS, adaptive request pacing and image
handling as the command-line collector. Imports run on the server without
requesting or storing another account password.

1. Food.ru, Rambler/eda and IamCook appear as initial source presets. Click
   **Проверить** before the first import. Verification reads a complete sample
   recipe and checks its cover; the source card shows ingredient, instruction
   and step-photo counts. A failed check displays its error and prevents new
   jobs for that source.
2. To connect another site, enter its HTTPS site or catalog URL and click
   **Определить и подключить**. Known sites use their existing parsing settings.
   For other sites, automatic detection makes a bounded search through links
   and sitemaps on the same site, finds a complete recipe, and derives source
   URL patterns. The service then verifies a sample recipe before saving the
   source. Detection may take some time; failures retain the entered URL and
   display the reason. Sites with blocked access, JavaScript-only recipes, or
   unsupported or incomplete recipe markup cannot be connected automatically.
   The optional **Ручные настройки — необязательно** section accepts a JSON
   definition to override detection; its fields match the collector
   configuration documented below. Sources can be disabled without deleting
   recipes or previous job reports.
   Every source, including the initial presets, can be renamed or removed.
   Removing a source hides its external catalog, disables scheduled refreshes
   and stops its active work; recipes and photos already imported into user
   collections are preserved. Removed presets stay removed after reloading the
   page or restarting the service. Adding that site's URL again reconnects it
   after verification.
3. Use **Обновить каталог** to save the site's recipe index and categories.
   The index retains source URLs, recipe metadata and preparation instructions
   separately from recipes in personal collections. Source cards show the
   number found, the number imported, the last update and whether the scan
   completed. A partial scan is identified explicitly; its count is not an
   assertion of the site's global recipe total. Categories come from the
   source's available catalog links and recipe metadata.
4. Choose **Добавить рецепты** and select the whole source, a category from
   the source's dropdown, or up to 100 individual recipe links. A limit of
   **0** processes recipes until discovery is exhausted or the job is stopped.
   A positive limit stops after that many new recipes; duplicates do not
   consume it. Choose visibility and optionally disable step photos. Discovery
   follows the source's available links and sitemaps; it does not guarantee
   that every recipe on an arbitrary site can be enumerated.
   Administrative imports also populate the source catalog as they run:
   discovered categories and normalized recipe URLs are upserted, and recipe
   metadata is saved from the page already parsed for import. An existing
   catalog payload is reused without fetching its recipe page again; photos
   are downloaded as required for the personal recipe. Importing a subset
   does not mark the whole source as scanned or remove other catalog entries.
   Old personal recipes whose original source payload was never cached add
   URL references when encountered again, without fetching duplicate pages
   or publishing personal edits. A catalog refresh can read those missing
   source payloads. This synchronization applies to service-admin import
   jobs; the standalone CLI and photo-repair jobs retain their existing scope.
5. Choose **Дополнить фотографии** to add missing covers and step photos to
   recipes owned by the administrator who starts the job. Existing images and
   recipe text are preserved. Step photos require the current text and order
   to match the source. This mode does not create recipes.
6. **Последние задания** shows progress, current source URL, counts, errors and
   warnings. A JSON report can be downloaded. Closing the browser does not
   stop collection. **Остановить** requests a cooperative stop between network
   operations and writes; completed recipe/image updates remain saved.

Enable **Делать видимыми на сайте** to expose a source's indexed recipes in
**Рецепты сайтов**. Authenticated users can filter that catalog, open a recipe
and read its ingredients and steps without creating a personal recipe. Source
images remain external until import. **Импортировать рецепт** explicitly saves
the recipe and available photos into the current user's collection, privately
by default. Repeating that action opens the already imported recipe. Disabled,
unverified or hidden sources are not accessible through the external catalog.

Optional automatic catalog refresh runs inside the server worker. It is
disabled by default; its initial interval is 24 hours and can be changed in
the admin interface. Refresh discovers new source recipes without importing
them into personal collections. It shares the import queue and does not
start a concurrent second administrative job. The service must be running for
scheduled refreshes to execute.

Only one administrative import job can be active at a time. Job ownership,
progress and source definitions are persisted in the database. Continuing or
repeating a finished job creates a new run with the same parameters: existing
recipes are skipped and photo repair fills only missing images. After an
interrupted server process, an expired 90-second worker lease marks its job as
stopped, preserving the last report so it can be continued explicitly.

Connected, enabled and verified sites appear in the catalog's **Источник
рецептов** filter. It also recognizes recipes previously imported by the CLI
through their source URLs. The existing **Новый рецепт → По ссылке** flow remains
available for manual imports.

Deployment includes migration **0013**, which adds `import_sources` and
`import_jobs`, and **0014**, which adds the durable external catalog, source
categories and refresh settings. The standard application startup runs these
migrations. Update the
backend and frontend/container together to expose the new admin controls. No
external queue service or new package dependency is required. The CLI remains
available and keeps its JSON configuration independent of connected sources
stored in the service database.

### Bulk collection from configured recipe sites

`backend/collect_recipes.py` collects recipes from Food.ru, Rambler/eda and
IamCook by default, and either saves them directly to a running service through
its API or prepares a ZIP for the backup importer. It requires Python 3.10
or newer and uses only the standard library; installing the backend dependencies
is not necessary. Run these commands from the repository root:

```bash
# Save up to 100 recipes from all configured sites directly to the local service.
# The password is requested in the terminal without displaying it.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin --limit 100

# Direct import with shared visibility and an explicit JSON report path.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin --site rambler \
  --limit 20 --public --report rambler-import-report.json

# Collect from IamCook only.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin --site iamcook --limit 20 --public

# Continue until all discoverable recipes have been processed; stop with Ctrl+C.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin --site food --limit 0 --public

# Add missing covers and step photos without creating new recipes.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin \
  --fill-missing-images --limit 100

# Repair photos for Food.ru recipes only.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin \
  --fill-missing-images --site food --report food-covers-report.json

# Keep a fixed pause instead of adapting it to source response times.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin --fixed-delay --delay 2 --limit 20

# Import covers and text without downloading step photos.
python3 backend/collect_recipes.py \
  --server http://localhost:1331 --login admin --no-step-images --limit 20

# Prepare a ZIP instead; the service does not need to be running.
python3 backend/collect_recipes.py --output recipes.zip

# One site and a smaller collection for reviewing the result.
python3 backend/collect_recipes.py --site food --limit 10 --output food-sample.zip
python3 backend/collect_recipes.py --site rambler --limit 10 --output rambler-sample.zip

# Select both sites explicitly and omit all image downloads.
python3 backend/collect_recipes.py \
  --site food --site rambler --limit 50 --no-images --output recipes-text.zip

# Collect a specific recipe instead of discovering URLs from sitemaps.
python3 backend/collect_recipes.py \
  --url https://eda.rambler.ru/recepty/pasta-picca/spagetti-karbonara-s-krasnym-lukom-17614 \
  --output carbonara.zip

# Read selected recipe URLs from a UTF-8 text file.
python3 backend/collect_recipes.py --urls-file recipe-urls.txt --output selected-recipes.zip
```

Choose exactly one destination: `--server` for direct import or `--output` for a
ZIP. All source selection, recipe limit, visibility and image options work in
both modes. Direct import requires `--login`, which accepts the service username
or email. The collector requests the password interactively; it has no password
argument or password environment variable. Access and refresh tokens remain in
memory, and authentication responses are not included in reports.

Direct step-photo uploads require this version of the running backend. Rebuild
or redeploy the backend/container before importing step photos: the new endpoint
is `POST /api/recipes/{recipe_id}/steps/{step_id}/image?only_if_missing=true`.
The collector checks `/openapi.json` before downloading or changing recipes in
step-photo mode. An older backend is rejected with an actionable update message;
HTTP 404 or 405 during an unchecked step upload also stops collection immediately.
Use `--no-step-images` temporarily if only covers and text are needed. No database
schema migration is required. The existing interface already displays stored
step photos; this change does not add step-photo downloading to the interface's
separate import-by-URL action.

Direct import checks the signed-in user's existing recipes by title and source
URL before writing, then creates categories and recipes through the API. A
sequential rerun skips recipes already saved by that account. Run one collector
at a time for an account: concurrent independent runs have no server-side
uniqueness guarantee. Each recipe is saved before its cover is uploaded. A cover
failure leaves the saved recipe in place and adds a warning. Step photos are
uploaded to their matching saved step IDs. New recipes appear
in the service as collection progresses; no ZIP is created in this mode.

Use `--fill-missing-images` to add covers and step photos to recipes already owned by the
signed-in account. This mode scans stored recipes with supported source URLs;
it does not discover new recipes through sitemaps or create recipes or
categories. Existing covers and step photos are retained. The collector matches
the normalized source URL and checks for a cover again before uploading.
Step-photo repair requires source and saved step texts to match in order;
edited, reordered or mismatched steps are skipped with a warning. The collector
updates image fields on existing recipe and step IDs. Other recipe fields and visibility are
preserved. Unsupported source URLs count as skipped; ambiguous matches with
multiple recipes sharing one source URL are skipped and recorded in the report.

Without filters, image repair considers all configured sites. Use `--site`,
`--url` or `--urls-file` to select sources or specific recipes. `--limit` bounds
recipe repair attempts, and `--max-pages` also bounds source page attempts. The
mode requires `--server` and cannot be combined with `--output` or `--no-images`.
The JSON report includes `updated_images` for covers, `updated_step_images`, saved recipe IDs, skips, errors and
warnings, and preserves partial progress on interruption. A normal import rerun
continues to skip existing recipes; use the repair flag when images are
missing. Repeating image repair skips images that have already been added.
Use `--no-step-images` for cover-only repair; `--no-images` cannot be combined
with the repair flag.

`--report` selects the JSON report path for direct import. Without it, the
collector chooses a new timestamped report filename. The report records saved
recipe IDs, sources, duplicates, errors and warnings, including partial progress
when collection stops. Existing reports are not overwritten. Authenticated API
requests reject redirects, and an expired access token is refreshed once. A
network error or HTTP 5xx during a write stops collection because the write may
already have succeeded. Start a new run to check existing recipes before
retrying; writes are not automatically retried after an uncertain result.

The URL file contains one recipe URL per line. Blank lines and lines starting
with `#` are ignored. `--url` and `--site` can be repeated. Supplying recipe URLs
disables automatic discovery unless `--site` is also specified. Catalog pages
such as `/recipes` or `/recepty` are not valid values for `--url`.

Automatic discovery detects XML sitemaps, gzip-compressed sitemaps and HTML
catalogs. It stays on the source's configured hosts, follows category and
pagination links and checks same-site sitemaps to avoid repeatedly scanning
only the homepage's recent recipes. A category scan remains scoped to the
selected section. Traversal no longer ends silently after ten catalog pages.
The default total recipe limit is 100; `--limit` accepts 0–5000, with **0**
continuing until discovery is exhausted or stopped. `--max-pages` independently
bounds recipe page attempts (default: 500, or unlimited when `--limit 0` is
used; maximum positive value: 50000). An explicit `--max-pages 0` also removes
that attempt limit. Sitemap, robots.txt and image requests do not count toward
it. Recipes with the same normalized URL or case-insensitive title are skipped.
Reports distinguish processed candidates from fetched recipe pages and record
the stopping reason, including exhaustion, limits, partial discovery and a
manual stop. Long-running imports retain bounded report details and indicate
when details have been truncated; aggregate counters continue increasing.

Source settings are stored in `backend/recipe_sources.json`. The bundled source
IDs are `food`, `rambler` and `iamcook`; `amcook` remains an alias for `iamcook`.
Repeat `--site` to select sources. Without `--site` or explicit recipe URLs, the
collector alternates all configured sources. Use `--sources-file PATH` to load
a different JSON source mapping instead of the bundled mapping. The same
settings control direct import, ZIP collection, URL normalization and cover
repair.

Each source entry defines a canonical host, accepted host aliases, a starting
catalog URL and full regular-expression matches for recipe and catalog URL
paths. For example, a separate `my-sources.json` can contain:

```json
{
  "example": {
    "canonical_host": "recipes.example.org",
    "hosts": ["recipes.example.org", "www.recipes.example.org"],
    "catalog_url": "https://recipes.example.org/sitemap.xml",
    "recipe_pattern": "/recipe/\\d+",
    "catalog_pattern": "/(?:sitemap(?:-\\d+)?\\.xml(?:\\.gz)?|recipes(?:/page/\\d+)?)",
    "aliases": ["example-recipes"]
  }
}
```

```bash
python3 backend/collect_recipes.py \
  --sources-file my-sources.json --site example --limit 20 --output example-recipes.zip
```

`hosts` explicitly lists the domains that belong to the source; recipe links
are normalized to `canonical_host`, and tracking parameters are removed.
`catalog_pattern` limits which nested maps or HTML catalog links may be followed.
Set `recipe_trailing_slash` to `true` when recipe pages require a final `/`;
automatic detection preserves this from its verified sample. Existing source
definitions default to URLs without the final slash.
Adding a compatible source therefore requires editing configuration rather than
the Python collector. The shared parser reads JSON-LD `schema.org/Recipe`
data and HTML microdata with `itemscope`/`itemprop`, including ingredients and
ordered preparation steps. IamCook also has a built-in adapter because its structured data provides
metadata while ingredients and instructions are stored in the page HTML.
Other sites with incomplete structured data may need their own adapter;
configuration does not add support for arbitrary page layouts,
JavaScript-only content or CAPTCHAs. Review a small collection to check
ingredient quantities, portions and covers for each new source.

Requests are sequential and use adaptive pauses by default. `--delay` sets the
initial pause (default: 2 seconds); `--min-delay` and `--max-delay` bound normal
adaptation (defaults: 0.25 and 10 seconds). Each host is tracked separately.
Successful responses gradually reduce the pause, response-time averages keep it
appropriate for the host's speed, and failures increase it. Robots.txt
crawl-delay or request-rate rules remain a lower bound even when they exceed
`--max-delay`. Use `--fixed-delay --delay 2` to keep a constant requested pause.

`--retries` controls bounded retries for source network errors and HTTP 5xx
responses (default: 2, maximum: 5). Adaptive mode also retries HTTP 429 responses:
a rate-limited response increases the pause, and a valid `Retry-After` cooldown
is honored up to 60 seconds. Longer requested cooldowns stop that host rather
than retrying early. Fixed-delay mode stops a host on HTTP 429; HTTP 401 or 403
also stops requests to that host. Recipe pages and
sitemaps respect robots.txt. If robots.txt cannot be checked, page requests to
that origin fail; HTTP 404 is treated as an absent robots.txt. Page and sitemap
downloads follow at most three HTTPS redirects that only add or remove a final
slash on the same host, with robots rules checked again for each target. Other
redirects are refused; supply the final URL directly when available. Automatic
source detection can additionally establish a bare-domain/`www` alias through
the entered site's initial HTTPS redirect before learning its source settings.

Cover and step-photo downloads use the same downloader and User-Agent as importing a recipe
through the service interface. They do not check the image host's robots.txt and
can follow public HTTP redirects. This applies to both new recipes and missing
image repair. TLS verification, public-host validation, image size limits,
adaptive request pauses and bounded retries still apply. The collector does not
solve CAPTCHAs. Authenticated
service API requests continue to reject redirects.

TLS trust is configured before the password prompt. The collector preserves
Python's default trust store and explicit `SSL_CERT_FILE` / `SSL_CERT_DIR`
settings. When Python has no default CA store, it detects a public system CA
bundle (including `/etc/ssl/cert.pem` on macOS) and prints the selected source.
No additional package is required. The same verified SSL context is used for
source downloads and service API requests; certificate and hostname verification
remain enabled. This does not change global Python settings or the web importer.
To select a trusted PEM bundle explicitly, use
`--ca-bundle /path/to/trusted-ca-bundle.pem`, or configure `SSL_CERT_FILE`.
If a configured store fails verification, the collector reports the error without
switching to another trust store.

In ZIP mode, the archive contains `recipes.json`, downloaded covers and step photos under `images/`, and
`collection-report.json` with collected sources, duplicate counts, errors and
warnings. Source URLs and available source author names are preserved. Recipes
without a title, ingredients or instructions are skipped. Missing quantities and
servings are reported for review; when servings are missing, the service default
of two is used. A cover download failure keeps the recipe and adds a warning.
Step photographs are collected by default when the source provides them and are
kept aligned with instruction text. Food.ru and Rambler expose them in structured
data; IamCook's adapter reads them from the instruction blocks. Extra result or
unrelated photos are not assigned to steps. A step without a source photo keeps
its instruction text; failed downloads or uploads add warnings. Videos are not collected.
`--no-step-images` skips step-photo downloads while retaining covers;
`--no-images` skips all image downloads. Reports for new collection include
`step_images`, while repair reports count successful step uploads in
`updated_step_images`.
The collector enforces the service's 100 MiB `recipes.json` limit and 2 GiB ZIP
limit. If a size limit is exceeded, collect fewer recipes or use `--no-images`.

The script never accesses the service database directly. In ZIP mode, open the
archive report and review a small collection, then sign in as an administrator
and use **Управление → Резервная копия → Восстановить из архива**. In direct mode,
the signed-in API account owns the saved recipes; administrator privileges are
not required. Recipes are private by default in both modes; pass `--public` when
collecting to make them visible to other service users. The service's archive
importer skips an existing recipe with the same title and owner by default.

Existing ZIP output files are never overwritten. Choose a new `--output` path for
each run. Collection does not resume a previous archive; if interrupted, the
ZIP may be incomplete. In ZIP mode, a completed run exits with status 0 when at least one
recipe was collected, or status 1 when none were collected. Partial failures are
listed in the archive report.

Use collected content according to each source's terms. Food.ru states that
using its content requires written permission; retaining a source link does not
replace that permission.

Run the collector tests without network requests:

```bash
PYTHONPATH=backend python3 -B -m unittest discover -s backend/tests -v
```

---

## Разработка

**Стек:** FastAPI · SQLAlchemy 2 · Alembic · React 19 · Vite · Tailwind CSS 4 · shadcn/ui.

```bash
# бэкенд
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=../data uvicorn app.main:app --reload --port 1331

# фронтенд (в другом терминале)
cd frontend
npm install
npm run dev        # http://localhost:5173, /api проксируется на :1331
```

Для импорта со скриншотов локально нужен Tesseract: `brew install tesseract tesseract-lang` или `apt install tesseract-ocr tesseract-ocr-rus`.

Новая миграция после изменения моделей:

```bash
cd backend && DATA_DIR=../data alembic revision --autogenerate -m "описание"
```

### Структура

```
backend/
  app/
    main.py           — приложение, отдача SPA
    config.py         — настройки, /data/config.json
    db.py             — подключение к БД, миграции
    models.py         — модели SQLAlchemy
    importer.py       — импорт по ссылке (schema.org/Recipe)
    textimport.py     — импорт из текста и OCR
    nutrition.py      — КБЖУ и встроенный справочник
    costing.py        — себестоимость и её история
    productmatch.py   — сопоставление продуктов, защита от дублей
    routers/          — API: auth, recipes, catalog, shopping, plan, pantry, backup…
  migrations/         — Alembic
frontend/
  src/
    pages/            — экраны приложения
    components/       — компоненты (ui/ — в стиле shadcn/ui)
    lib/api.ts        — клиент API
```

### API и авторизация

- `POST /api/auth/login` возвращает `access_token` и `refresh_token`. В вебе refresh-токен дополнительно кладётся в httpOnly-cookie.
- Запросы отправляются с заголовком `Authorization: Bearer <access_token>`.
- `POST /api/auth/refresh` работает по cookie (веб) или по телу `{"refresh_token": "..."}` (мобильные клиенты).
- Полная документация доступна по адресу `http://<сервер>:1331/docs`.

## Планы

- [ ] Мобильное приложение (Expo)
