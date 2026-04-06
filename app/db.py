import os
from typing import Dict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import CHAT_DB_PATH, DATABASE_URL, DB_BACKEND, FINANCE_DATABASE_URL, FINANCE_DB_PATH


Base = declarative_base()

_ENGINES: Dict[str, object] = {}
_SESSION_FACTORIES: Dict[str, sessionmaker] = {}


def _sqlite_url(path: str) -> str:
    return f"sqlite:///{path}"


def _database_url(scope: str) -> str:
    if DB_BACKEND == "postgres":
        if scope == "finance":
            return FINANCE_DATABASE_URL
        return DATABASE_URL
    if scope == "finance":
        os.makedirs(os.path.dirname(FINANCE_DB_PATH), exist_ok=True)
        return _sqlite_url(FINANCE_DB_PATH)
    os.makedirs(os.path.dirname(CHAT_DB_PATH), exist_ok=True)
    return _sqlite_url(CHAT_DB_PATH)


def get_engine(scope: str = "chat"):
    if scope not in _ENGINES:
        url = _database_url(scope)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite:///") else {}
        _ENGINES[scope] = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
    return _ENGINES[scope]


def get_session_factory(scope: str = "chat") -> sessionmaker:
    if scope not in _SESSION_FACTORIES:
        _SESSION_FACTORIES[scope] = sessionmaker(bind=get_engine(scope), autoflush=False, autocommit=False, future=True)
    return _SESSION_FACTORIES[scope]


def run_migrations():
    if DB_BACKEND != "postgres":
        return
    try:
        from alembic import command
        from alembic.config import Config
    except Exception as e:
        raise RuntimeError("Alembic is not installed. Run: pip install alembic") from e

    project_root = Path(__file__).resolve().parent.parent
    alembic_ini = project_root / "alembic.ini"
    alembic_dir = project_root / "alembic"

    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    alembic_cfg.set_main_option("script_location", str(alembic_dir))
    command.upgrade(alembic_cfg, "head")
