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
ghcr.io/nskarl/myrecipes:latest
```

Образ собран для `linux/amd64`. Приложение слушает порт **1331**. Все данные хранятся в томе `/data`: конфиг, секретный ключ, фотографии, а при SQLite и сама база.

Выберите один из трёх вариантов, сохраните его как `docker-compose.yml` и запустите:

```bash
docker compose up -d
```

Потом откройте `http://<сервер>:1331`. Если база не задана заранее, откроется мастер настройки.

### Вариант 1. SQLite (самый простой)

База хранится в файле `./data/recipes.db`, отдельный сервер БД не нужен. Подходит для дома и семьи.

```yaml
services:
  app:
    image: ghcr.io/nskarl/myrecipes:latest
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
    image: ghcr.io/nskarl/myrecipes:latest
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

Один compose поднимает приложение и отдельный контейнер MariaDB. Подходит, если базы ещё нет, а SQLite не устраивает.

```yaml
services:
  app:
    image: ghcr.io/nskarl/myrecipes:latest
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
git clone https://github.com/nskarl/myrecipes.git
cd myrecipes
```

В любом из вариантов выше замените `image: ghcr.io/nskarl/myrecipes:latest` на `build: .` и запустите `docker compose up -d --build`. Так образ соберётся и под ARM, например для Raspberry Pi или Apple Silicon.

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
- Есть встроенный экспорт рецептов. **Профиль → Резервная копия** скачивает zip с рецептами и фото, его можно импортировать на другом сервере. Пользователи и настройки в архив не входят.

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
