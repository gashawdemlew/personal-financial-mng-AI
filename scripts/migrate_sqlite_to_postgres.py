#!/usr/bin/env python3
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.chat_repository import ChatMessage, ChatSession
from app.config import CHAT_DB_PATH, DATABASE_URL, FINANCE_DB_PATH
from app.finance.repository import (
    FinanceChatMessage,
    FinanceGoal,
    FinanceMonthlyBudget,
    FinanceNudge,
    FinanceTransaction,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate legacy SQLite chat/finance data into PostgreSQL.",
    )
    parser.add_argument(
        "--chat-db",
        default=CHAT_DB_PATH,
        help="Path to legacy chat SQLite database.",
    )
    parser.add_argument(
        "--finance-db",
        default=FINANCE_DB_PATH,
        help="Path to legacy finance SQLite database.",
    )
    parser.add_argument(
        "--target-url",
        default=DATABASE_URL,
        help="Target PostgreSQL SQLAlchemy URL.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for inserts/upserts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect source data and report planned inserts without writing to PostgreSQL.",
    )
    return parser.parse_args()


def parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return datetime.utcnow()
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported datetime value: {value!r}")


def sqlite_connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_sqlite_rows(conn: sqlite3.Connection, table_name: str) -> List[Dict]:
    rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
    return [dict(row) for row in rows]


def chunked(items: Sequence[Dict], size: int) -> Iterable[Sequence[Dict]]:
    for index in range(0, len(items), size):
        yield items[index:index + size]


def row_signature(row: Dict, columns: Sequence[str]) -> Tuple:
    values = []
    for col in columns:
        value = row.get(col)
        if isinstance(value, datetime):
            value = value.isoformat(sep=" ")
        values.append(value)
    return tuple(values)


def normalize_chat_messages(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "chat_id": str(row["chat_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "created_at": parse_dt(row["created_at"]),
        }
        for row in rows
    ]


def normalize_chat_sessions(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "chat_id": str(row["chat_id"]),
            "user_id": str(row.get("user_id") or ""),
            "title": str(row.get("title") or "New chat"),
            "last_message_preview": str(row.get("last_message_preview") or ""),
            "message_count": int(row.get("message_count") or 0),
            "created_at": parse_dt(row["created_at"]),
            "updated_at": parse_dt(row["updated_at"]),
        }
        for row in rows
    ]


def normalize_finance_transactions(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "user_id": str(row["user_id"]),
            "txn_type": str(row["txn_type"]),
            "amount": float(row["amount"]),
            "balance": float(row["balance"]),
            "txn_date": str(row["txn_date"]),
            "narration": str(row["narration"]),
            "created_at": parse_dt(row["created_at"]),
            "raw_json": str(row["raw_json"]),
        }
        for row in rows
    ]


def normalize_finance_chat_messages(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "user_id": str(row["user_id"]),
            "chat_id": str(row["chat_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "created_at": parse_dt(row["created_at"]),
        }
        for row in rows
    ]


def normalize_finance_goals(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "user_id": str(row["user_id"]),
            "goal_name": str(row["goal_name"]),
            "goal_amount": float(row["goal_amount"]),
            "target_months": int(row["target_months"]),
            "start_date": str(row["start_date"]),
            "status": str(row["status"]),
            "created_at": parse_dt(row["created_at"]),
            "updated_at": parse_dt(row["updated_at"]),
        }
        for row in rows
    ]


def normalize_finance_nudges(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "user_id": str(row["user_id"]),
            "nudge_type": str(row["nudge_type"]),
            "priority": str(row["priority"]),
            "title": str(row["title"]),
            "message": str(row["message"]),
            "payload_json": str(row["payload_json"]),
            "dedupe_key": str(row["dedupe_key"]),
            "acknowledged": int(row.get("acknowledged") or 0),
            "created_at": parse_dt(row["created_at"]),
        }
        for row in rows
    ]


def normalize_finance_budgets(rows: List[Dict]) -> List[Dict]:
    return [
        {
            "usecase_id": str(row["usecase_id"]),
            "user_id": str(row["user_id"]),
            "budget_month": str(row["budget_month"]),
            "total_budget": float(row["total_budget"]),
            "currency": str(row["currency"]),
            "category_allocations_json": str(row["category_allocations_json"]),
            "created_at": parse_dt(row["created_at"]),
            "updated_at": parse_dt(row["updated_at"]),
        }
        for row in rows
    ]


def migrate_append_only(
    session: Session,
    model,
    rows: List[Dict],
    signature_columns: Sequence[str],
    batch_size: int,
    dry_run: bool,
) -> Dict:
    existing_rows = session.execute(
        select(*[getattr(model, column) for column in signature_columns])
    ).all()
    existing_signatures = {tuple(row) for row in existing_rows}

    to_insert: List[Dict] = []
    seen_source = set()
    for row in rows:
        signature = row_signature(row, signature_columns)
        if signature in seen_source or signature in existing_signatures:
            continue
        seen_source.add(signature)
        to_insert.append(row)

    if not dry_run:
        for batch in chunked(to_insert, batch_size):
            session.execute(pg_insert(model.__table__).values(list(batch)))

    return {
        "source_rows": len(rows),
        "planned_inserts": len(to_insert),
        "skipped_existing": len(rows) - len(to_insert),
    }


def migrate_upsert(
    session: Session,
    model,
    rows: List[Dict],
    conflict_columns: Sequence[str],
    update_columns: Sequence[str],
    batch_size: int,
    dry_run: bool,
) -> Dict:
    if dry_run:
        return {
            "source_rows": len(rows),
            "planned_upserts": len(rows),
        }

    table = model.__table__
    for batch in chunked(rows, batch_size):
        stmt = pg_insert(table).values(list(batch))
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_columns),
            set_={column: getattr(stmt.excluded, column) for column in update_columns},
        )
        session.execute(stmt)

    return {
        "source_rows": len(rows),
        "planned_upserts": len(rows),
    }


def validate_paths(chat_db: str, finance_db: str):
    missing = [path for path in (chat_db, finance_db) if not Path(path).exists()]
    if missing:
        raise FileNotFoundError(f"Missing SQLite database file(s): {', '.join(missing)}")


def main():
    args = parse_args()
    if "postgresql" not in args.target_url:
        raise ValueError("Target URL must be a PostgreSQL SQLAlchemy URL.")

    validate_paths(args.chat_db, args.finance_db)

    chat_conn = sqlite_connect(args.chat_db)
    finance_conn = sqlite_connect(args.finance_db)
    engine = create_engine(args.target_url, future=True, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    report = {}

    try:
        chat_messages = normalize_chat_messages(fetch_sqlite_rows(chat_conn, "chat_messages"))
        chat_sessions = normalize_chat_sessions(fetch_sqlite_rows(chat_conn, "chat_sessions"))
        finance_transactions = normalize_finance_transactions(fetch_sqlite_rows(finance_conn, "finance_transactions"))
        finance_chat_messages = normalize_finance_chat_messages(fetch_sqlite_rows(finance_conn, "finance_chat_messages"))
        finance_goals = normalize_finance_goals(fetch_sqlite_rows(finance_conn, "finance_goals"))
        finance_nudges = normalize_finance_nudges(fetch_sqlite_rows(finance_conn, "finance_nudges"))
        finance_budgets = normalize_finance_budgets(fetch_sqlite_rows(finance_conn, "finance_monthly_budgets"))

        with session_factory() as session:
            report["chat_messages"] = migrate_append_only(
                session=session,
                model=ChatMessage,
                rows=chat_messages,
                signature_columns=["usecase_id", "chat_id", "role", "content", "created_at"],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            report["chat_sessions"] = migrate_upsert(
                session=session,
                model=ChatSession,
                rows=chat_sessions,
                conflict_columns=["usecase_id", "chat_id"],
                update_columns=[
                    "user_id",
                    "title",
                    "last_message_preview",
                    "message_count",
                    "created_at",
                    "updated_at",
                ],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            report["finance_transactions"] = migrate_append_only(
                session=session,
                model=FinanceTransaction,
                rows=finance_transactions,
                signature_columns=[
                    "usecase_id",
                    "user_id",
                    "txn_type",
                    "amount",
                    "balance",
                    "txn_date",
                    "narration",
                    "created_at",
                    "raw_json",
                ],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            report["finance_chat_messages"] = migrate_append_only(
                session=session,
                model=FinanceChatMessage,
                rows=finance_chat_messages,
                signature_columns=[
                    "usecase_id",
                    "user_id",
                    "chat_id",
                    "role",
                    "content",
                    "created_at",
                ],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            report["finance_goals"] = migrate_upsert(
                session=session,
                model=FinanceGoal,
                rows=finance_goals,
                conflict_columns=["usecase_id", "user_id", "goal_name"],
                update_columns=[
                    "goal_amount",
                    "target_months",
                    "start_date",
                    "status",
                    "created_at",
                    "updated_at",
                ],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            report["finance_nudges"] = migrate_upsert(
                session=session,
                model=FinanceNudge,
                rows=finance_nudges,
                conflict_columns=["usecase_id", "user_id", "dedupe_key"],
                update_columns=[
                    "nudge_type",
                    "priority",
                    "title",
                    "message",
                    "payload_json",
                    "acknowledged",
                    "created_at",
                ],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            report["finance_monthly_budgets"] = migrate_upsert(
                session=session,
                model=FinanceMonthlyBudget,
                rows=finance_budgets,
                conflict_columns=["usecase_id", "user_id", "budget_month"],
                update_columns=[
                    "total_budget",
                    "currency",
                    "category_allocations_json",
                    "created_at",
                    "updated_at",
                ],
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
    finally:
        chat_conn.close()
        finance_conn.close()

    mode = "DRY RUN" if args.dry_run else "MIGRATION COMPLETE"
    print(f"\n{mode}")
    print(f"Target: {args.target_url}")
    for table_name, stats in report.items():
        print(f"- {table_name}")
        for key, value in stats.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
