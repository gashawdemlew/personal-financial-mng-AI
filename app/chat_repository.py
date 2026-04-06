from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import DB_BACKEND
from app.db import Base, get_engine, get_session_factory


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    chat_id: Mapped[str] = mapped_column(String(255), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (UniqueConstraint("usecase_id", "chat_id", name="uq_chat_sessions_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    chat_id: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(255), default="New chat")
    last_message_preview: Mapped[str] = mapped_column(Text, default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatQuotaConfig(Base):
    __tablename__ = "chat_quota_config"
    __table_args__ = (UniqueConstraint("usecase_id", name="uq_chat_quota_usecase"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usecase_id: Mapped[str] = mapped_column(String(255), index=True)
    daily_limit: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def _session() -> Session:
    return get_session_factory("chat")()


def _session_to_dict(item: ChatSession) -> Dict:
    return {
        "usecase_id": item.usecase_id,
        "chat_id": item.chat_id,
        "user_id": item.user_id,
        "title": item.title,
        "last_message_preview": item.last_message_preview,
        "message_count": item.message_count,
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }


def init_chat_db():
    if DB_BACKEND == "postgres":
        return
    Base.metadata.create_all(
        get_engine("chat"),
        tables=[ChatMessage.__table__, ChatSession.__table__, ChatQuotaConfig.__table__],
    )


def create_chat_session(usecase_id: str, chat_id: str, user_id: str = "", title: str = "") -> Dict:
    init_chat_db()
    now = datetime.utcnow()
    with _session() as session:
        existing = session.execute(
            select(ChatSession).where(ChatSession.usecase_id == usecase_id, ChatSession.chat_id == chat_id)
        ).scalar_one_or_none()
        if existing is None:
            existing = ChatSession(
                usecase_id=usecase_id,
                chat_id=chat_id,
                user_id=str(user_id or ""),
                title=(title or "").strip() or "New chat",
                last_message_preview="",
                message_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return _session_to_dict(existing)


def append_chat_messages(usecase_id: str, chat_id: str, messages: List[Dict], user_id: str = ""):
    init_chat_db()
    now = datetime.utcnow()
    with _session() as session:
        inserted_count = 0
        last_preview = ""
        first_user = ""
        for m in messages:
            role = str(m.get("role", "")).strip().lower()
            content = str(m.get("content", ""))
            if role not in {"user", "assistant"}:
                continue
            session.add(
                ChatMessage(
                    usecase_id=usecase_id,
                    chat_id=chat_id,
                    role=role,
                    content=content,
                    created_at=now,
                )
            )
            inserted_count += 1
            if content.strip():
                last_preview = content.strip()[:200]
            if not first_user and role == "user" and content.strip():
                first_user = content.strip()[:80]

        chat_session = session.execute(
            select(ChatSession).where(ChatSession.usecase_id == usecase_id, ChatSession.chat_id == chat_id)
        ).scalar_one_or_none()
        if chat_session is None:
            chat_session = ChatSession(
                usecase_id=usecase_id,
                chat_id=chat_id,
                user_id=str(user_id or ""),
                title=first_user or "New chat",
                last_message_preview=last_preview,
                message_count=inserted_count,
                created_at=now,
                updated_at=now,
            )
            session.add(chat_session)
        else:
            if not chat_session.user_id and user_id:
                chat_session.user_id = str(user_id)
            if chat_session.title == "New chat" and first_user:
                chat_session.title = first_user
            chat_session.last_message_preview = last_preview
            chat_session.message_count = int(chat_session.message_count or 0) + inserted_count
            chat_session.updated_at = now

        session.commit()


def get_chat_messages(usecase_id: str, chat_id: str) -> List[Dict]:
    init_chat_db()
    with _session() as session:
        rows = session.execute(
            select(ChatMessage).where(
                ChatMessage.usecase_id == usecase_id,
                ChatMessage.chat_id == chat_id,
            ).order_by(ChatMessage.id.asc())
        ).scalars().all()
        return [{"role": row.role, "content": row.content} for row in rows]


def get_chat_messages_page(
    usecase_id: str,
    chat_id: str,
    limit: int = 20,
    before_id: Optional[int] = None,
) -> Dict:
    init_chat_db()
    with _session() as session:
        stmt = select(ChatMessage).where(
            ChatMessage.usecase_id == usecase_id,
            ChatMessage.chat_id == chat_id,
        )
        if before_id is not None:
            stmt = stmt.where(ChatMessage.id < int(before_id))
        rows = session.execute(stmt.order_by(ChatMessage.id.desc()).limit(int(limit) + 1)).scalars().all()
        has_more = len(rows) > int(limit)
        rows = rows[: int(limit)]
        rows.reverse()
        items = [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            }
            for row in rows
        ]
        next_before_id = items[0]["id"] if items and has_more else None
        return {"messages": items, "has_more": has_more, "next_before_id": next_before_id}


def get_recent_chat_messages(usecase_id: str, chat_id: str, limit: int = 12) -> List[Dict]:
    page = get_chat_messages_page(usecase_id=usecase_id, chat_id=chat_id, limit=limit, before_id=None)
    return [{"role": m["role"], "content": m["content"]} for m in page["messages"]]


def find_chat_ids_by_prefix(usecase_id: str, chat_id_prefix: str) -> List[str]:
    init_chat_db()
    with _session() as session:
        rows = session.execute(
            select(ChatMessage.chat_id)
            .where(ChatMessage.usecase_id == usecase_id, ChatMessage.chat_id.like(f"{chat_id_prefix}%"))
            .distinct()
            .order_by(ChatMessage.chat_id.asc())
        ).all()
        return [row[0] for row in rows]


def list_chat_sessions(
    usecase_id: str,
    user_id: str = "",
    limit: int = 20,
    offset: int = 0,
) -> List[Dict]:
    init_chat_db()
    with _session() as session:
        stmt = select(ChatSession).where(ChatSession.usecase_id == usecase_id)
        if user_id:
            stmt = stmt.where(ChatSession.user_id == user_id)
        rows = session.execute(
            stmt.order_by(ChatSession.updated_at.desc(), ChatSession.chat_id.desc()).limit(int(limit)).offset(int(offset))
        ).scalars().all()
        return [_session_to_dict(row) for row in rows]


def get_chat_session(usecase_id: str, chat_id: str) -> Optional[Dict]:
    init_chat_db()
    with _session() as session:
        row = session.execute(
            select(ChatSession).where(ChatSession.usecase_id == usecase_id, ChatSession.chat_id == chat_id)
        ).scalar_one_or_none()
        return _session_to_dict(row) if row else None


def update_chat_session_title(usecase_id: str, chat_id: str, title: str):
    init_chat_db()
    with _session() as session:
        row = session.execute(
            select(ChatSession).where(ChatSession.usecase_id == usecase_id, ChatSession.chat_id == chat_id)
        ).scalar_one_or_none()
        if row is None:
            return
        row.title = (str(title or "").strip() or "New chat")[:255]
        row.updated_at = datetime.utcnow()
        session.commit()


def delete_chat_messages(usecase_id: str, chat_id: str):
    init_chat_db()
    with _session() as session:
        session.query(ChatMessage).filter(
            ChatMessage.usecase_id == usecase_id,
            ChatMessage.chat_id == chat_id,
        ).delete()
        session.query(ChatSession).filter(
            ChatSession.usecase_id == usecase_id,
            ChatSession.chat_id == chat_id,
        ).delete()
        session.commit()


def get_chat_quota_config(usecase_id: str) -> Optional[Dict]:
    init_chat_db()
    with _session() as session:
        row = session.execute(
            select(ChatQuotaConfig).where(ChatQuotaConfig.usecase_id == usecase_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {
            "usecase_id": row.usecase_id,
            "daily_limit": int(row.daily_limit),
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }


def list_chat_quota_configs() -> List[Dict]:
    init_chat_db()
    with _session() as session:
        rows = session.execute(
            select(ChatQuotaConfig).order_by(ChatQuotaConfig.usecase_id.asc())
        ).scalars().all()
        return [
            {
                "usecase_id": row.usecase_id,
                "daily_limit": int(row.daily_limit),
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
            for row in rows
        ]


def upsert_chat_quota_config(usecase_id: str, daily_limit: int) -> Dict:
    init_chat_db()
    now = datetime.utcnow()
    with _session() as session:
        row = session.execute(
            select(ChatQuotaConfig).where(ChatQuotaConfig.usecase_id == usecase_id)
        ).scalar_one_or_none()
        if row is None:
            row = ChatQuotaConfig(
                usecase_id=usecase_id,
                daily_limit=int(daily_limit),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.daily_limit = int(daily_limit)
            row.updated_at = now
        session.commit()
        session.refresh(row)
        return {
            "usecase_id": row.usecase_id,
            "daily_limit": int(row.daily_limit),
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        }
