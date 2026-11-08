# messenger architecture overview

```
        ┌────────────────┐
        │   Browser / JS │
        └───────┬────────┘
                │
┌───────────────┴───────────────┐
│        Django Templates       │
│   - /accounts/...             │
│   - /chat/                    │
└───────────────┬───────────────┘
                │
                ▼
┌────────────────────────────────┐
│        JavaScript              │
│ - REST for history and search  │
│ - WebSocket for live messages  │
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│     Django REST API            │
│  /api/accounts/  /api/chat/    │
└───────────────┬────────────────┘
                │
                ▼
┌────────────────────────────────┐
│  Django Channels (ASGI)        │
│  ws/chat/<id>/                 │
└───────────────┬────────────────┘
                │
        ┌───────┴────────┐
        ▼                ▼
┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │    Redis     │
└──────────────┘  └──────────────┘
```

The server is the authority for membership, blocks, and stored messages. The browser is not trusted to decide who may read or post.
