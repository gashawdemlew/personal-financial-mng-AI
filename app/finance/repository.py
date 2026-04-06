import json
import calendar
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import DB_BACKEND
from app.db import Base, get_engine, get_session_factory


class FinanceTransaction(Base):
    __tablename__ = "finance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    linked_account_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    txn_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    balance: Mapped[float] = mapped_column(Float)
    txn_date: Mapped[str] = mapped_column(String(32), index=True)
    narration: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_json: Mapped[str] = mapped_column(Text)


class FinanceTransactionArchive(Base):
    __tablename__ = "finance_transactions_archive"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    linked_account_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    txn_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    balance: Mapped[float] = mapped_column(Float)
    txn_date: Mapped[str] = mapped_column(String(32), index=True)
    narration: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_json: Mapped[str] = mapped_column(Text)


class FinanceChatMessage(Base):
    __tablename__ = "finance_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    chat_id: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinanceGoal(Base):
    __tablename__ = "finance_goals"
    __table_args__ = (UniqueConstraint("usecase_id", "user_id", "linked_account_id", "goal_name", name="uq_finance_goals_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    linked_account_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    goal_name: Mapped[str] = mapped_column(String(255))
    goal_amount: Mapped[float] = mapped_column(Float)
    target_months: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinanceNudge(Base):
    __tablename__ = "finance_nudges"
    __table_args__ = (UniqueConstraint("usecase_id", "user_id", "linked_account_id", "dedupe_key", name="uq_finance_nudges_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    linked_account_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    nudge_type: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(255))
    acknowledged: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinanceMonthlyBudget(Base):
    __tablename__ = "finance_monthly_budgets"
    __table_args__ = (UniqueConstraint("usecase_id", "user_id", "linked_account_id", "budget_month", name="uq_finance_budgets_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    linked_account_id: Mapped[Optional[str]] = mapped_column(String(255), index=True, nullable=True)
    budget_month: Mapped[str] = mapped_column(String(16), index=True)
    total_budget: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(32))
    category_allocations_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def _session() -> Session:
    return get_session_factory("finance")()


def init_finance_db():
    if DB_BACKEND == "postgres":
        return
    Base.metadata.create_all(
        get_engine("finance"),
        tables=[
            FinanceTransaction.__table__,
            FinanceTransactionArchive.__table__,
            FinanceChatMessage.__table__,
            FinanceGoal.__table__,
            FinanceNudge.__table__,
            FinanceMonthlyBudget.__table__,
        ],
    )


def _read_any(d: Dict, keys: List[str], default=None):
    for k in keys:
        if k in d:
            return d[k]
    return default


def _normalize_type(v) -> str:
    value = str(v or "").strip().lower()
    if value in {"debit", "dr"}:
        return "debit"
    if value in {"credit", "cr"}:
        return "credit"
    raise ValueError("transaction type must be debit or credit")


def _to_float(v, field_name: str) -> float:
    try:
        return float(v)
    except Exception as e:
        raise ValueError(f"{field_name} must be numeric") from e


def _normalize_date(v) -> str:
    s = str(v or "").strip()
    if not s:
        raise ValueError("transaction date required")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except Exception as e:
        raise ValueError("transaction date must be parseable") from e


def normalize_transaction(item: Dict) -> Dict:
    txn_type = _read_any(item, ["transaction_type", "Transaction type", "type", "txn_type"])
    amount = _read_any(item, ["transaction_amount", "Transaction amount", "amount"])
    balance = _read_any(item, ["balance", "Balance"])
    txn_date = _read_any(item, ["transaction_date", "transaction date", "date"])
    narration = _read_any(item, ["transaction_narration", "transaction narration", "narration", "category"], "other")
    linked_account_id = _read_any(
        item,
        ["linked_account_id", "linked account id", "account_id", "accountId"],
        None,
    )
    return {
        "txn_type": _normalize_type(txn_type),
        "amount": _to_float(amount, "amount"),
        "balance": _to_float(balance, "balance"),
        "txn_date": _normalize_date(txn_date),
        "narration": str(narration or "other").strip().lower(),
        "linked_account_id": str(linked_account_id).strip() if linked_account_id is not None and str(linked_account_id).strip() else None,
    }


def _subtract_months(value: date, months: int) -> date:
    year = value.year
    month = value.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _retention_cutoff_date(today: Optional[date] = None, keep_months: int = 6) -> str:
    current = today or datetime.utcnow().date()
    return _subtract_months(current, keep_months).isoformat()


def archive_and_prune_old_transactions(
    usecase_id: str,
    user_id: str,
    keep_months: int = 6,
    today: Optional[date] = None,
    session: Optional[Session] = None,
) -> Dict:
    init_finance_db()
    cutoff_date = _retention_cutoff_date(today=today, keep_months=keep_months)

    def _prune(active_session: Session) -> Dict:
        rows = active_session.execute(
            select(FinanceTransaction).where(
                FinanceTransaction.usecase_id == usecase_id,
                FinanceTransaction.user_id == user_id,
                FinanceTransaction.txn_date < cutoff_date,
            )
        ).scalars().all()

        if not rows:
            return {
                "active_retention_months": keep_months,
                "cutoff_date": cutoff_date,
                "archived_count": 0,
                "deleted_count": 0,
            }

        for row in rows:
            active_session.add(
                FinanceTransactionArchive(
                    usecase_id=row.usecase_id,
                    user_id=row.user_id,
                    linked_account_id=row.linked_account_id,
                    txn_type=row.txn_type,
                    amount=row.amount,
                    balance=row.balance,
                    txn_date=row.txn_date,
                    narration=row.narration,
                    created_at=row.created_at,
                    raw_json=row.raw_json,
                )
            )
        for row in rows:
            active_session.delete(row)

        return {
            "active_retention_months": keep_months,
            "cutoff_date": cutoff_date,
            "archived_count": len(rows),
            "deleted_count": len(rows),
        }

    if session is not None:
        return _prune(session)

    with _session() as managed_session:
        result = _prune(managed_session)
        managed_session.commit()
        return result


def ingest_transactions(
    usecase_id: str,
    user_id: str,
    transactions: List[Dict],
    today: Optional[date] = None,
) -> Tuple[int, List[Dict], Dict]:
    init_finance_db()
    inserted = 0
    failed = []
    now = datetime.utcnow()
    retention = {
        "active_retention_months": 6,
        "cutoff_date": _retention_cutoff_date(today=today, keep_months=6),
        "archived_count": 0,
        "deleted_count": 0,
    }
    with _session() as session:
        for idx, t in enumerate(transactions):
            try:
                n = normalize_transaction(t)
                session.add(
                    FinanceTransaction(
                        usecase_id=usecase_id,
                        user_id=user_id,
                        linked_account_id=n.get("linked_account_id"),
                        txn_type=n["txn_type"],
                        amount=n["amount"],
                        balance=n["balance"],
                        txn_date=n["txn_date"],
                        narration=n["narration"],
                        created_at=now,
                        raw_json=json.dumps(t),
                    )
                )
                inserted += 1
            except Exception as e:
                failed.append({"index": idx, "error": str(e), "item": t})
        if inserted > 0:
            session.flush()
            retention = archive_and_prune_old_transactions(
                usecase_id=usecase_id,
                user_id=user_id,
                keep_months=6,
                today=today,
                session=session,
            )
        session.commit()
    return inserted, failed, retention


def list_transactions(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 200,
) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        stmt = select(FinanceTransaction).where(
            FinanceTransaction.usecase_id == usecase_id,
            FinanceTransaction.user_id == user_id,
        )
        if linked_account_id:
            stmt = stmt.where(FinanceTransaction.linked_account_id == linked_account_id)
        if start_date:
            stmt = stmt.where(FinanceTransaction.txn_date >= start_date)
        if end_date:
            stmt = stmt.where(FinanceTransaction.txn_date <= end_date)
        rows = session.execute(
            stmt.order_by(FinanceTransaction.txn_date.desc(), FinanceTransaction.id.desc()).limit(int(limit))
        ).scalars().all()
        return [
            _transaction_row_to_dict(row)
            for row in rows
        ]


def _transaction_row_to_dict(row) -> Dict:
    return {
        "id": row.id,
        "usecase_id": row.usecase_id,
        "user_id": row.user_id,
        "linked_account_id": row.linked_account_id,
        "txn_type": row.txn_type,
        "amount": row.amount,
        "balance": row.balance,
        "txn_date": row.txn_date,
        "narration": row.narration,
    }


def list_all_transactions(usecase_id: str, user_id: str, linked_account_id: Optional[str] = None) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        stmt = (
            select(FinanceTransaction)
            .where(FinanceTransaction.usecase_id == usecase_id, FinanceTransaction.user_id == user_id)
            .order_by(FinanceTransaction.txn_date.asc(), FinanceTransaction.id.asc())
        )
        if linked_account_id:
            stmt = stmt.where(FinanceTransaction.linked_account_id == linked_account_id)
        rows = session.execute(stmt).scalars().all()
        return [_transaction_row_to_dict(row) for row in rows]


def list_all_transactions_extended(
    usecase_id: str,
    user_id: str,
    include_archive: bool = False,
    linked_account_id: Optional[str] = None,
) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        active_stmt = (
            select(FinanceTransaction)
            .where(FinanceTransaction.usecase_id == usecase_id, FinanceTransaction.user_id == user_id)
            .order_by(FinanceTransaction.txn_date.asc(), FinanceTransaction.id.asc())
        )
        if linked_account_id:
            active_stmt = active_stmt.where(FinanceTransaction.linked_account_id == linked_account_id)
        active_rows = session.execute(active_stmt).scalars().all()
        items = [_transaction_row_to_dict(row) for row in active_rows]
        if include_archive:
            archive_stmt = (
                select(FinanceTransactionArchive)
                .where(FinanceTransactionArchive.usecase_id == usecase_id, FinanceTransactionArchive.user_id == user_id)
                .order_by(FinanceTransactionArchive.txn_date.asc(), FinanceTransactionArchive.id.asc())
            )
            if linked_account_id:
                archive_stmt = archive_stmt.where(FinanceTransactionArchive.linked_account_id == linked_account_id)
            archived_rows = session.execute(archive_stmt).scalars().all()
            items.extend(_transaction_row_to_dict(row) for row in archived_rows)
        items.sort(key=lambda row: (row["txn_date"], row["id"]))
        return items


def distinct_categories(
    usecase_id: str,
    user_id: str,
    include_archive: bool = False,
    linked_account_id: Optional[str] = None,
) -> List[str]:
    init_finance_db()
    with _session() as session:
        stmt = (
            select(FinanceTransaction.narration)
            .where(FinanceTransaction.usecase_id == usecase_id, FinanceTransaction.user_id == user_id)
            .distinct()
            .order_by(FinanceTransaction.narration.asc())
        )
        if linked_account_id:
            stmt = stmt.where(FinanceTransaction.linked_account_id == linked_account_id)
        rows = session.execute(stmt).all()
        categories = {row[0] for row in rows}
        if include_archive:
            archive_stmt = (
                select(FinanceTransactionArchive.narration)
                .where(
                    FinanceTransactionArchive.usecase_id == usecase_id,
                    FinanceTransactionArchive.user_id == user_id,
                )
                .distinct()
                .order_by(FinanceTransactionArchive.narration.asc())
            )
            if linked_account_id:
                archive_stmt = archive_stmt.where(FinanceTransactionArchive.linked_account_id == linked_account_id)
            archive_rows = session.execute(archive_stmt).all()
            categories.update(row[0] for row in archive_rows)
        return sorted(categories)


def transaction_storage_stats(
    usecase_id: str,
    user_id: Optional[str] = None,
    linked_account_id: Optional[str] = None,
) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        active_stmt = (
            select(FinanceTransaction.user_id, func.count(FinanceTransaction.id))
            .where(FinanceTransaction.usecase_id == usecase_id)
            .group_by(FinanceTransaction.user_id)
        )
        archive_stmt = (
            select(FinanceTransactionArchive.user_id, func.count(FinanceTransactionArchive.id))
            .where(FinanceTransactionArchive.usecase_id == usecase_id)
            .group_by(FinanceTransactionArchive.user_id)
        )
        if user_id:
            active_stmt = active_stmt.where(FinanceTransaction.user_id == user_id)
            archive_stmt = archive_stmt.where(FinanceTransactionArchive.user_id == user_id)
        if linked_account_id:
            active_stmt = active_stmt.where(FinanceTransaction.linked_account_id == linked_account_id)
            archive_stmt = archive_stmt.where(FinanceTransactionArchive.linked_account_id == linked_account_id)

        stats: Dict[str, Dict] = {}
        for uid, count in session.execute(active_stmt).all():
            stats[str(uid)] = {
                "usecase_id": usecase_id,
                "user_id": str(uid),
                "linked_account_id": linked_account_id or "",
                "active_count": int(count or 0),
                "archived_count": 0,
            }
        for uid, count in session.execute(archive_stmt).all():
            key = str(uid)
            if key not in stats:
                stats[key] = {
                    "usecase_id": usecase_id,
                    "user_id": key,
                    "linked_account_id": linked_account_id or "",
                    "active_count": 0,
                    "archived_count": 0,
                }
            stats[key]["archived_count"] = int(count or 0)

        items = list(stats.values())
        items.sort(key=lambda item: (item["user_id"]))
        return items


def append_chat_messages(usecase_id: str, user_id: str, chat_id: str, messages: List[Dict]):
    init_finance_db()
    now = datetime.utcnow()
    with _session() as session:
        for m in messages:
            role = str(m.get("role", "")).strip().lower()
            content = str(m.get("content", ""))
            if role not in {"user", "assistant"}:
                continue
            session.add(
                FinanceChatMessage(
                    usecase_id=usecase_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    role=role,
                    content=content,
                    created_at=now,
                )
            )
        session.commit()


def get_chat_messages(usecase_id: str, chat_id: str) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        rows = session.execute(
            select(FinanceChatMessage)
            .where(FinanceChatMessage.usecase_id == usecase_id, FinanceChatMessage.chat_id == chat_id)
            .order_by(FinanceChatMessage.id.asc())
        ).scalars().all()
        return [{"role": row.role, "content": row.content} for row in rows]


def delete_chat_messages(usecase_id: str, chat_id: str):
    init_finance_db()
    with _session() as session:
        session.query(FinanceChatMessage).filter(
            FinanceChatMessage.usecase_id == usecase_id,
            FinanceChatMessage.chat_id == chat_id,
        ).delete()
        session.commit()


def find_usecases_by_chat_id(chat_id: str) -> List[str]:
    init_finance_db()
    with _session() as session:
        rows = session.execute(
            select(FinanceChatMessage.usecase_id)
            .where(FinanceChatMessage.chat_id == chat_id)
            .distinct()
            .order_by(FinanceChatMessage.usecase_id.asc())
        ).all()
        return [row[0] for row in rows]


def find_chat_ids_by_prefix(usecase_id: str, chat_id_prefix: str) -> List[str]:
    init_finance_db()
    with _session() as session:
        rows = session.execute(
            select(FinanceChatMessage.chat_id)
            .where(FinanceChatMessage.usecase_id == usecase_id, FinanceChatMessage.chat_id.like(f"{chat_id_prefix}%"))
            .distinct()
            .order_by(FinanceChatMessage.chat_id.asc())
        ).all()
        return [row[0] for row in rows]


def _goal_to_dict(row: FinanceGoal) -> Dict:
    return {
        "id": row.id,
        "usecase_id": row.usecase_id,
        "user_id": row.user_id,
        "linked_account_id": row.linked_account_id,
        "goal_name": row.goal_name,
        "goal_amount": row.goal_amount,
        "target_months": row.target_months,
        "start_date": row.start_date,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def upsert_goal(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str],
    goal_name: str,
    goal_amount: float,
    target_months: int,
    start_date: Optional[str] = None,
    status: str = "active",
) -> Dict:
    init_finance_db()
    now = datetime.utcnow()
    normalized_goal_name = str(goal_name or "primary").strip().lower()
    start_date = str(start_date or date.today().isoformat())
    with _session() as session:
        row = session.execute(
            select(FinanceGoal).where(
                FinanceGoal.usecase_id == usecase_id,
                FinanceGoal.user_id == user_id,
                FinanceGoal.linked_account_id == linked_account_id,
                FinanceGoal.goal_name == normalized_goal_name,
            )
        ).scalar_one_or_none()
        if row is None:
            row = FinanceGoal(
                usecase_id=usecase_id,
                user_id=user_id,
                linked_account_id=linked_account_id,
                goal_name=normalized_goal_name,
                goal_amount=float(goal_amount),
                target_months=int(target_months),
                start_date=start_date,
                status=str(status),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.goal_amount = float(goal_amount)
            row.target_months = int(target_months)
            row.start_date = start_date
            row.status = str(status)
            row.updated_at = now
        session.commit()
        session.refresh(row)
        return _goal_to_dict(row)


def list_goals(usecase_id: str, user_id: str, status: Optional[str] = None) -> List[Dict]:
    return list_goals_for_scope(usecase_id=usecase_id, user_id=user_id, linked_account_id=None, status=status)


def list_goals_for_scope(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        stmt = select(FinanceGoal).where(FinanceGoal.usecase_id == usecase_id, FinanceGoal.user_id == user_id)
        if linked_account_id:
            stmt = stmt.where(FinanceGoal.linked_account_id == linked_account_id)
        elif linked_account_id is None:
            stmt = stmt.where(FinanceGoal.linked_account_id.is_(None))
        if status:
            stmt = stmt.where(FinanceGoal.status == status)
        rows = session.execute(stmt.order_by(FinanceGoal.id.desc())).scalars().all()
        return [_goal_to_dict(row) for row in rows]


def _nudge_to_dict(row: FinanceNudge) -> Dict:
    item = {
        "id": row.id,
        "usecase_id": row.usecase_id,
        "user_id": row.user_id,
        "linked_account_id": row.linked_account_id,
        "nudge_type": row.nudge_type,
        "priority": row.priority,
        "title": row.title,
        "message": row.message,
        "dedupe_key": row.dedupe_key,
        "acknowledged": bool(row.acknowledged),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
    try:
        item["payload"] = json.loads(row.payload_json)
    except Exception:
        item["payload"] = {}
    return item


def insert_nudge(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str],
    nudge_type: str,
    priority: str,
    title: str,
    message: str,
    payload: Optional[Dict] = None,
    dedupe_key: str = "",
) -> Dict:
    init_finance_db()
    now = datetime.utcnow()
    dedupe = dedupe_key or f"{nudge_type}:{now.isoformat()}"
    payload_json = json.dumps(payload or {})
    with _session() as session:
        row = session.execute(
            select(FinanceNudge).where(
                FinanceNudge.usecase_id == usecase_id,
                FinanceNudge.user_id == user_id,
                FinanceNudge.linked_account_id == linked_account_id,
                FinanceNudge.dedupe_key == dedupe,
            )
        ).scalar_one_or_none()
        if row is None:
            row = FinanceNudge(
                usecase_id=usecase_id,
                user_id=user_id,
                linked_account_id=linked_account_id,
                nudge_type=str(nudge_type),
                priority=str(priority),
                title=str(title),
                message=str(message),
                payload_json=payload_json,
                dedupe_key=str(dedupe),
                acknowledged=0,
                created_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _nudge_to_dict(row)


def list_nudges(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    include_acknowledged: bool = False,
    limit: int = 50,
) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        stmt = select(FinanceNudge).where(FinanceNudge.usecase_id == usecase_id, FinanceNudge.user_id == user_id)
        if linked_account_id:
            stmt = stmt.where(FinanceNudge.linked_account_id == linked_account_id)
        elif linked_account_id is None:
            stmt = stmt.where(FinanceNudge.linked_account_id.is_(None))
        if not include_acknowledged:
            stmt = stmt.where(FinanceNudge.acknowledged == 0)
        rows = session.execute(stmt.order_by(FinanceNudge.id.desc()).limit(int(limit))).scalars().all()
        return [_nudge_to_dict(row) for row in rows]


def acknowledge_nudge(usecase_id: str, user_id: str, nudge_id: int, linked_account_id: Optional[str] = None) -> bool:
    init_finance_db()
    with _session() as session:
        stmt = select(FinanceNudge).where(
                FinanceNudge.usecase_id == usecase_id,
                FinanceNudge.user_id == user_id,
                FinanceNudge.id == int(nudge_id),
        )
        if linked_account_id:
            stmt = stmt.where(FinanceNudge.linked_account_id == linked_account_id)
        elif linked_account_id is None:
            stmt = stmt.where(FinanceNudge.linked_account_id.is_(None))
        row = session.execute(stmt).scalar_one_or_none()
        if row is None:
            return False
        row.acknowledged = 1
        session.commit()
        return True


def _budget_to_dict(row: FinanceMonthlyBudget) -> Dict:
    item = {
        "id": row.id,
        "usecase_id": row.usecase_id,
        "user_id": row.user_id,
        "linked_account_id": row.linked_account_id,
        "budget_month": row.budget_month,
        "total_budget": row.total_budget,
        "currency": row.currency,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
    try:
        item["category_allocations"] = json.loads(row.category_allocations_json)
    except Exception:
        item["category_allocations"] = {}
    return item


def upsert_monthly_budget(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str],
    budget_month: str,
    total_budget: float,
    currency: str = "ETB",
    category_allocations: Optional[Dict] = None,
) -> Dict:
    init_finance_db()
    now = datetime.utcnow()
    allocations_json = json.dumps(category_allocations or {})
    with _session() as session:
        row = session.execute(
            select(FinanceMonthlyBudget).where(
                FinanceMonthlyBudget.usecase_id == usecase_id,
                FinanceMonthlyBudget.user_id == user_id,
                FinanceMonthlyBudget.linked_account_id == linked_account_id,
                FinanceMonthlyBudget.budget_month == budget_month,
            )
        ).scalar_one_or_none()
        if row is None:
            row = FinanceMonthlyBudget(
                usecase_id=usecase_id,
                user_id=user_id,
                linked_account_id=linked_account_id,
                budget_month=budget_month,
                total_budget=float(total_budget),
                currency=str(currency or "ETB"),
                category_allocations_json=allocations_json,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.total_budget = float(total_budget)
            row.currency = str(currency or "ETB")
            row.category_allocations_json = allocations_json
            row.updated_at = now
        session.commit()
        session.refresh(row)
        return _budget_to_dict(row)


def list_monthly_budgets(
    usecase_id: str,
    user_id: str,
    linked_account_id: Optional[str] = None,
    limit: int = 12,
    up_to_month: Optional[str] = None,
) -> List[Dict]:
    init_finance_db()
    with _session() as session:
        stmt = select(FinanceMonthlyBudget).where(
            FinanceMonthlyBudget.usecase_id == usecase_id,
            FinanceMonthlyBudget.user_id == user_id,
        )
        if linked_account_id:
            stmt = stmt.where(FinanceMonthlyBudget.linked_account_id == linked_account_id)
        elif linked_account_id is None:
            stmt = stmt.where(FinanceMonthlyBudget.linked_account_id.is_(None))
        if up_to_month:
            stmt = stmt.where(FinanceMonthlyBudget.budget_month <= up_to_month)
        rows = session.execute(
            stmt.order_by(FinanceMonthlyBudget.budget_month.desc(), FinanceMonthlyBudget.id.desc()).limit(int(limit))
        ).scalars().all()
        return [_budget_to_dict(row) for row in rows]


def list_linked_accounts(usecase_id: str, user_id: str, include_archive: bool = True) -> List[str]:
    init_finance_db()
    with _session() as session:
        active_rows = session.execute(
            select(FinanceTransaction.linked_account_id)
            .where(
                FinanceTransaction.usecase_id == usecase_id,
                FinanceTransaction.user_id == user_id,
                FinanceTransaction.linked_account_id.is_not(None),
            )
            .distinct()
            .order_by(FinanceTransaction.linked_account_id.asc())
        ).all()
        account_ids = {row[0] for row in active_rows if row[0]}
        if include_archive:
            archive_rows = session.execute(
                select(FinanceTransactionArchive.linked_account_id)
                .where(
                    FinanceTransactionArchive.usecase_id == usecase_id,
                    FinanceTransactionArchive.user_id == user_id,
                    FinanceTransactionArchive.linked_account_id.is_not(None),
                )
                .distinct()
                .order_by(FinanceTransactionArchive.linked_account_id.asc())
            ).all()
            account_ids.update(row[0] for row in archive_rows if row[0])
        return sorted(account_ids)
