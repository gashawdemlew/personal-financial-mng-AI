# Postgres Migration Notes

This project now supports PostgreSQL as the primary backend for chat and finance persistence.

## Current backend

The app is configured to use PostgreSQL through:

- `/Users/user_name/Desktop/python_codes/personal-financial-mng-AI/app/config.py`
- `/Users/user_name/Desktop/python_codes/personal-financial-mng-AI/app/db.py`

Current default connection:

```text
postgresql+psycopg://db_user:db_password@localhost/personal_financial_man
```

## Schema management

Schema is managed with Alembic:

```bash
alembic upgrade head
alembic current
```

Run those commands from the project root:

```bash
cd /Users/user_name/Desktop/python_codes/personal-financial-mng-AI
alembic upgrade head
```

If you are already inside `/Users/user_name/Desktop/python_codes/personal-financial-mng-AI/alembic`, use:

```bash
alembic -c ../alembic.ini upgrade head
```

Initial migration file:

- `/Users/usen_name/Desktop/python_codes/personal-financial-mng-AI//alembic/versions/20260322_000001_initial_chat_and_finance_schema.py`

## Legacy SQLite sources

The migration script reads from:

- `/Users/usen_name/Desktop/python_codes/personal-financial-mng-AI//data/chat_history.db`
- `/Users/usen_name/Desktop/python_codes/personal-financial-mng-AI//data/finance.db`

## Data migration script

Use the migration script from the project root:

```bash
python scripts/migrate_sqlite_to_postgres.py --dry-run
python scripts/migrate_sqlite_to_postgres.py
```

## Post-migration health check

Use the Postgres health-check script from the project root:

```bash
python scripts/check_postgres_health.py
python scripts/check_postgres_health.py --json
```

This verifies:

- Postgres connectivity
- server time
- core table counts for chat and finance tables

What it migrates:

- `chat_messages`
- `chat_sessions`
- `finance_transactions`
- `finance_chat_messages`
- `finance_goals`
- `finance_nudges`
- `finance_monthly_budgets`

## Migration behavior

- Append-only tables use dedupe signatures to avoid duplicate inserts on rerun.
- Unique business-key tables use Postgres upsert.
- The script preserves business data and timestamps.
- The script does not preserve legacy SQLite numeric IDs. Postgres assigns its own IDs.

## Recommended migration flow

1. Run `alembic upgrade head`
2. Run `python scripts/migrate_sqlite_to_postgres.py --dry-run`
3. Review the reported source row counts
4. Run `python scripts/migrate_sqlite_to_postgres.py`
5. Verify table counts in Postgres
6. Run smoke tests against:
   - `/rag/chats`
   - `/rag/chat/history/{chat_id}`
   - `/finance/transactions`
   - `/finance/goals`
   - `/finance/budget/history`

## Rollback expectation

This script does not implement row-by-row rollback. If a rollback is needed, restore the PostgreSQL database from backup or truncate the migrated tables before re-running.

## Notes

- Redis remains a short-tail cache only. PostgreSQL is the source of truth for persistent chat and finance data.
- Chroma remains separate and is not part of this migration.
