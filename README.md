# messenger

A team messenger with group chats, built with **Django**, **Django REST Framework**, and **Django Channels**.

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository>
```

### 2. Configure environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

### 3. Start the project

If you previously ran this repository as a card game, drop the old Postgres volume first so the new migration chain can apply:

```bash
docker compose down -v
```

Run containers:

```bash
docker compose up --build
```

Available services:

- Django + Channels: http://localhost:8000
- PostgreSQL: localhost:5433

### 4. Apply migrations and create a superuser

```bash
docker compose exec web python manage.py migrate
```

Create a superuser (optional):

```bash
docker compose exec web python manage.py createsuperuser
```

### 5. Work with Django

Run migrations, tests, and management commands **inside the `web` container** (after `docker compose up`):

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py check
docker compose exec web pytest -v
```

If containers are not running yet, you can use a one-off container:

```bash
docker compose run --rm web python manage.py migrate
docker compose run --rm web pytest -v
```

Confirmation mail is printed in the `web` container logs (`EMAIL_BACKEND` defaults to the console backend).

### Design tokens

UI colors and spacing live in `accounts/static/ui/css/tokens.css`. Light is the default (`:root` / `html[data-theme="light"]`). Dark is `html[data-theme="dark"]`, or `prefers-color-scheme: dark` when `data-theme` is unset.

| Token | Light | Dark |
| --- | --- | --- |
| `--bg` | `#F7F7F8` | `#121214` |
| `--surface-1` | `#FFFFFF` | `#1C1C1F` |
| `--surface-2` | `#F0F0F2` | `#26262A` |
| `--text` | `#1A1A1E` | `#F2F2F4` |
| `--text-muted` | `#5C5C66` | `#A8A8B3` |
| `--accent` | `#5B5BD6` | `#7B7BE6` |
| `--accent-bg` | `#ECECFF` | `#2A2A4D` |
| `--danger` / `--success` | `#C62828` / `#2E7D32` | `#EF9A9A` / `#81C784` |
| `--radius` / `--radius-sm` | `12px` / `8px` | same |
| `--font` | `ui-sans-serif, system-ui, "Segoe UI", sans-serif` | same |

The profile page writes `light` or `dark` to `localStorage` key `messenger-theme`. An inline script in `base.html` applies that (or the system preference) before CSS loads.

Stylesheets, loaded in this order: `tokens.css`, `base.css`, `layout.css`, `chat.css`, `board.css`, `auth.css`. Cache-bust `asset_css_v` is the newest mtime in that folder.

### Chat: API and templates

REST (session auth as configured for DRF):

- `GET /api/chat/chats/` — list chats for the current user
- `POST /api/chat/chats/direct/` — JSON body `{ "other_user_id": "<uuid>" }` to open or reuse a 1:1 chat
- `GET|POST /api/chat/chats/<chat_uuid>/messages/` — list recent messages or `{ "content": "..." }` to post

Same behaviour in server-rendered UI (login required):

- `/chat/` — inbox
- `/chat/direct/new/` — start a direct chat by username
- `/chat/<chat_uuid>/` — history, HTTP post form, live WebSocket updates

Blocking uses `accounts.Block`: the blocked user cannot send **direct** messages to the blocker; group chats are unchanged.

Group boards open at `/boards/<uuid>/`. The page connects to `ws/boards/<uuid>/` so members share the drawing in real time (cursors, presence, and a server-side lock).

### Board editor JS tests

The editor modules are ES modules. From the repository root, with **Node 18+** on the host (the `web` container has no Node):

```bash
node --test boards/static/boards/js/serialize.test.js boards/static/boards/js/history.test.js boards/static/boards/js/store.test.js boards/static/boards/js/sync.test.js
```

That runs the `node:test` files next to the editor modules (no npm install).

### Board collaboration (manual)

Use two browsers, two accounts, same group board:

1. Draw a rectangle in A; it appears in B without a reload.
2. Drag the same object in both windows; the other client shows a live preview, then the committed position.
3. Lock the board as admin/owner; the member switches to read-only (tools hidden) without reload. Unlock restores editing.
4. DevTools → Network → Offline (or stop the `web` container briefly): the overlay shows «Переподключение…», pan/zoom still work, drawing does not. Back online, unconfirmed ops are resent.

### 6. Stop containers

```bash
docker compose down
```

---

## Documentation

Developer documentation is built with [Sphinx](https://www.sphinx-doc.org/) from the [`Docs/`](Docs/) directory.

Security limits, account rules, and chat access checks are kept in [Docs/engineering-decisions.md](Docs/engineering-decisions.md). Update that file in the same change that alters one of those decisions.

**Generate HTML** (from the repository root):

```bash
sphinx-build -b html Docs Docs/_build
```

Or with Docker:

```bash
docker compose exec web sphinx-build -b html Docs Docs/_build
```

---

## Stack

- Django, REST, Channels
- Redis
- PostgreSQL
- Docker
- Sphinx

## Origin

Part of this codebase comes from [Fools-Arena](https://github.com/uxabix/Fools-Arena): accounts (registration, email confirmation, rate limit, blocks), chat (models, WebSocket consumer, history, read marks, tests), Docker, and CI. The card game is removed.

## License

No license yet. **All rights reserved by the authors.**
