PYTHON ?= python

.PHONY: alembic-upgrade alembic-current pg-migrate-dry-run pg-migrate pg-health test

alembic-upgrade:
	alembic upgrade head

alembic-current:
	alembic current

pg-migrate-dry-run:
	$(PYTHON) scripts/migrate_sqlite_to_postgres.py --dry-run

pg-migrate:
	$(PYTHON) scripts/migrate_sqlite_to_postgres.py

pg-health:
	$(PYTHON) scripts/check_postgres_health.py

test:
	$(PYTHON) -m unittest discover -s tests -v
