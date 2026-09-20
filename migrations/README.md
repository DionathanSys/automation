# Database migrations

Run migrations from the project root after configuring `.env`:

```bash
alembic upgrade head
```

The operational tables are managed here. Legacy report tables are not part of
this migration history.
