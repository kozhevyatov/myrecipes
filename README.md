# Мои рецепты

Self-hosted сервис для хранения рецептов: ингредиенты в граммах, пошаговое приготовление, теги и категории.

**Стек:** FastAPI + SQLAlchemy 2 + Alembic (SQLite или MySQL/MariaDB) · React 19 + Vite + Tailwind CSS 4 + shadcn/ui · один Docker-контейнер на порту **1331**.

Репозиторий: https://git.nskarl.ru/nskarl/myreciept

## Быстрый старт

```bash
docker compose up -d --build
```

Откройте `http://<сервер>:1331`. При первом запуске откроется мастер:

1. **База данных** — SQLite (файл в `./data`) или MySQL/MariaDB.
2. **Администратор** — логин, пароль, название сервиса, открыта ли регистрация.

### С MariaDB из этого же compose

```bash
docker compose --profile mysql up -d --build
```

В мастере укажите: хост `mysql`, порт `3306`, база `recipes`, пользователь `recipes`, пароль `recipes-pass` (поменяйте в `docker-compose.yml`).

## Synology: установка и автодеплой из Gitea

Схема та же, что у остальных проектов:

- код — git-клон в `/volume1/docker/myreciept`;
- скрипт деплоя и лог лежат отдельно от репозитория: `/volume1/docker/deploy/myreciept-deploy.sh` и `myreciept-deploy.log`;
- Планировщик задач DSM запускает скрипт по расписанию.

Отличие от статических сайтов: при новых коммитах скрипт ещё и пересобирает контейнер (`docker compose up -d --build`). Папки `data/` и `mysql/` в `.gitignore`, обновление их не трогает. Если сборка упала, продолжает работать предыдущая версия, ошибка остаётся в логе.

### 1. Клонирование (один раз, по SSH под root)

```bash
git clone https://git.nskarl.ru/nskarl/myreciept.git /volume1/docker/myreciept
```

Авторизуйтесь так же, как в клонах других проектов.

### 2. Скрипт деплоя

Положите `myreciept-deploy.sh` в `/volume1/docker/deploy/`. Первый запуск соберёт и поднимет контейнер:

```bash
sh /volume1/docker/deploy/myreciept-deploy.sh --force
```

Проект `myreciept` появится в Container Manager.

### 3. Планировщик задач

Создайте задачу по аналогии с другими проектами (пользователь root):

```
sh /volume1/docker/deploy/myreciept-deploy.sh
```

Без новых коммитов скрипт сразу выходит. Ручная пересборка: `sh /volume1/docker/deploy/myreciept-deploy.sh --force`.

Если нужна MariaDB из compose, создайте в `/volume1/docker/myreciept` файл `.env` со строкой `COMPOSE_PROFILES=mysql`. Он в `.gitignore`.

### 4. Домен и HTTPS

**Панель управления → Портал входа → Дополнительно → Обратный прокси → Создать**:

- источник: `HTTPS`, ваш домен, порт `443`;
- назначение: `HTTP`, `localhost`, порт `1331`.

Перед первым запуском на публичном домене задайте `SETUP_TOKEN` в `docker-compose.yml`, чтобы мастер настройки не прошёл кто-то чужой.

**Бэкап:** `/volume1/docker/myreciept/data` (для SQLite это всё) и `mysql/`, если используете MariaDB.

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `DATABASE_URL` | Задать БД заранее и пропустить шаг мастера |
| `SETUP_TOKEN` | Токен для мастера первого запуска |
| `SECRET_KEY` | Ключ JWT (иначе генерируется в `/data/secret.key`) |
| `ACCESS_TOKEN_MINUTES` | Жизнь access-токена, по умолчанию 15 |
| `REFRESH_TOKEN_DAYS` | Жизнь сессии, по умолчанию 30 |
| `COOKIE_SECURE` | `auto` / `true` / `false` для refresh-cookie |
| `PORT` | Внутренний порт, по умолчанию 1331 |

## Разработка

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

Новая миграция после изменения моделей:

```bash
cd backend && DATA_DIR=../data alembic revision --autogenerate -m "описание"
```

Документация API: `http://localhost:1331/docs`.

## Структура

```
backend/
  app/
    main.py          — приложение, отдача SPA
    config.py        — настройки, /data/config.json
    db.py            — динамическое подключение к БД, миграции
    models.py        — модели SQLAlchemy
    security.py      — пароли (argon2), JWT
    routers/         — setup, auth, admin
  migrations/        — Alembic
frontend/
  src/
    pages/           — Setup, Login, Register, Home, Admin
    components/ui/   — компоненты в стиле shadcn/ui
    lib/api.ts       — клиент API (переиспользуем в мобильном приложении)
```

## API и авторизация

- `POST /api/auth/login` → `access_token` + `refresh_token`; в вебе refresh дополнительно кладётся в httpOnly-cookie.
- Запросы: `Authorization: Bearer <access_token>`.
- `POST /api/auth/refresh` — по cookie (веб) или `{"refresh_token": "..."}` (мобильное приложение).

## Дорожная карта

- [x] Этап 1 — каркас, мастер настройки, авторизация, управление регистрацией
- [ ] Этап 2 — рецепты: ингредиенты, шаги, фото, категории, теги
- [ ] Этап 3 — поиск и фильтры, пересчёт порций, режим готовки
- [ ] Этап 4 — справочник продуктов, КБЖУ, админка
- [ ] PWA → мобильное приложение (Expo)
