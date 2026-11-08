# Project structure: messenger

Django project with accounts, group and direct chat, and real-time delivery over Channels.

Applications:

- `accounts` — registration, email confirmation, rate limit, blocks, profiles, avatars
- `chat` — models, HTTP API, server-rendered inbox, WebSocket consumer
- `config` — Django project settings, URLs, ASGI/WSGI

Stack: Django 5.2, DRF, Channels, PostgreSQL, Redis, Docker.
