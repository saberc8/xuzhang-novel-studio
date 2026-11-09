"""PostgreSQL repository with per-project transactional row locking."""
import re
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

_owner = ContextVar("record_owner", default=None)


def current_owner() -> str:
    owner = _owner.get()
    if not owner:
        raise PermissionError("读取或写入作品前必须指定已认证用户")
    return owner


@contextmanager
def user_scope(user_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", user_id):
        raise ValueError("用户标识不合法")
    token = _owner.set(user_id)
    try:
        yield
    finally:
        _owner.reset(token)


class Store:
    def __init__(self, directory: Path, database_url: str, schema: str = "public"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", schema):
            raise ValueError("数据库 schema 名称不合法")
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self._connection = ContextVar("store_connection", default=None)
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            # Concurrent workers must not race schema creation / the one-time upgrade.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("xuzhang_schema:" + schema,))
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            conn.execute("""CREATE TABLE IF NOT EXISTS records (
                owner_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, id TEXT NOT NULL, payload JSONB NOT NULL,
                sequence BIGINT GENERATED ALWAYS AS IDENTITY,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (owner_id, kind, id), CHECK (jsonb_typeof(payload) = 'object')
            )""")
            # Empty ownership quarantines existing local data until an operator assigns it.
            conn.execute("ALTER TABLE records ADD COLUMN IF NOT EXISTS owner_id TEXT NOT NULL DEFAULT ''")
            primary = conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='records'::regclass AND contype='p'").fetchone()[0]
            if "owner_id" not in primary:
                conn.execute("ALTER TABLE records DROP CONSTRAINT records_pkey, ADD PRIMARY KEY (owner_id, kind, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS records_kind_sequence ON records (kind, sequence DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS records_book_id ON records (kind, (payload->>'book_id'))")
            conn.execute("CREATE INDEX IF NOT EXISTS records_source_project ON records (kind, (payload->>'source_project_id'))")
            conn.execute("CREATE INDEX IF NOT EXISTS records_owner_sequence ON records (owner_id, kind, sequence DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS records_owner_book ON records (owner_id, kind, (payload->>'book_id'))")
            conn.execute("CREATE INDEX IF NOT EXISTS records_owner_source ON records (owner_id, kind, (payload->>'source_project_id'))")
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS credentials (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL REFERENCES users(id),
                kind TEXT NOT NULL CHECK (kind IN ('session', 'api')), name TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
                revoked_at TIMESTAMPTZ, last_used_at TIMESTAMPTZ
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS credentials_user ON credentials (user_id, kind)")
            conn.execute("""CREATE TABLE IF NOT EXISTS auth_attempts (
                key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires_at TIMESTAMPTZ NOT NULL
            )""")
        self.pool = ConnectionPool(database_url, min_size=1, max_size=5, timeout=10, open=True,
                                   kwargs={"row_factory": dict_row, "options": f"-c search_path={schema}"})
        self.pool.wait(timeout=10)

    @contextmanager
    def connection(self):
        active = self._connection.get()
        if active is not None:
            # A mutation may read its source book. Reuse the transaction so it
            # cannot exhaust the pool while other writers wait on its row lock.
            with active.transaction():
                yield active
            return
        with self.pool.connection() as conn:
            token = self._connection.set(conn)
            try:
                with conn.transaction():
                    yield conn
            finally:
                self._connection.reset(token)

    def close(self):
        self.pool.close()

    def get(self, kind: str, identifier: str) -> dict:
        owner = current_owner()
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM records WHERE owner_id=%s AND kind=%s AND id=%s", (owner, kind, identifier)).fetchone()
        if not row:
            raise KeyError(f"找不到{kind}：{identifier}")
        return row["payload"]

    def list(self, kind: str, book_id: str | None = None, *, source_project_id: str | None = None) -> list[dict]:
        owner = current_owner()
        with self.connection() as conn:
            query = "SELECT payload FROM records WHERE owner_id=%s AND kind=%s"
            values = [owner, kind]
            if book_id is not None:
                query += " AND payload->>'book_id'=%s"
                values.append(book_id)
            if source_project_id is not None:
                query += " AND payload->>'source_project_id'=%s"
                values.append(source_project_id)
            rows = conn.execute(query + " ORDER BY sequence DESC", values).fetchall()
        return [row["payload"] for row in rows]

    def put(self, kind: str, value: dict) -> dict:
        owner = current_owner()
        with self.connection() as conn:
            conn.execute("""INSERT INTO records(owner_id,kind,id,payload) VALUES(%s,%s,%s,%s)
                ON CONFLICT(owner_id,kind,id) DO UPDATE SET payload=excluded.payload, updated_at=now()""",
                         (owner, kind, value["id"], Jsonb(value)))
        return value

    def mutate(self, kind: str, identifier: str, update: Callable[[dict], None]) -> dict:
        owner = current_owner()
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM records WHERE owner_id=%s AND kind=%s AND id=%s FOR UPDATE", (owner, kind, identifier)).fetchone()
            if not row:
                raise KeyError(f"找不到{kind}：{identifier}")
            value = row["payload"]
            update(value)
            conn.execute("UPDATE records SET payload=%s, updated_at=now() WHERE owner_id=%s AND kind=%s AND id=%s",
                         (Jsonb(value), owner, kind, identifier))
        return value

    def book_directory(self, identifier: str, *, create=False) -> Path:
        owner = current_owner()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier):
            raise ValueError("原著文件标识不合法")
        directory = self.directory / "users" / owner / identifier
        if create:
            directory.mkdir(parents=True)
        elif not directory.is_dir():
            # Callers must load the owned book first; legacy originals stay in place.
            directory = self.directory / identifier
        return directory
