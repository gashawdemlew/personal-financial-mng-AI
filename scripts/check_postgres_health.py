#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import DATABASE_URL


TABLES = [
    "alembic_version",
    "chat_messages",
    "chat_sessions",
    "finance_transactions",
    "finance_transactions_archive",
    "finance_chat_messages",
    "finance_goals",
    "finance_nudges",
    "finance_monthly_budgets",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Postgres connectivity and core table counts.")
    parser.add_argument(
        "--target-url",
        default=DATABASE_URL,
        help="Target PostgreSQL SQLAlchemy URL.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the result as JSON.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if "postgresql" not in args.target_url:
        raise ValueError("Target URL must be a PostgreSQL SQLAlchemy URL.")

    engine = create_engine(args.target_url, future=True, pool_pre_ping=True)
    result = {
        "status": "ok",
        "target": args.target_url,
        "server_time": None,
        "tables": {},
    }

    with engine.connect() as conn:
        result["server_time"] = str(conn.execute(text("select now()")).scalar_one())
        for table_name in TABLES:
            count = conn.execute(text(f"select count(*) from {table_name}")).scalar_one()
            result["tables"][table_name] = int(count)

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("POSTGRES HEALTH OK")
    print(f"Target: {result['target']}")
    print(f"Server time: {result['server_time']}")
    for table_name, count in result["tables"].items():
        print(f"- {table_name}: {count}")


if __name__ == "__main__":
    main()
