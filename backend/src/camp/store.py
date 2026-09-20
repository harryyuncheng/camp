"""Document store: one table per entity, JSON payload, with a few indexed columns for the common lookups.

Two backends behind one interface:
  * Postgres (production): `Store("postgresql://localhost/camp")`, JSONB rows + generated index columns.
  * SQLite (tests, offline): `Store(":memory:")` or `Store("camp.db")`.
`Store.from_env()` picks Postgres when CAMP_DATABASE_URL is set, else the CAMP_DB SQLite file.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel

from .models import Batch, FeedbackEvent, MenuItem, Order, Restaurant, User

T = TypeVar("T", bound=BaseModel)

TABLES: dict[type[BaseModel], str] = {
    User: "users", Restaurant: "restaurants", MenuItem: "items",
    Order: "orders", Batch: "batches", FeedbackEvent: "events",
}
# JSON keys promoted to indexed columns per table (used by the convenience queries)
INDEXED: dict[str, list[str]] = {
    "users": ["office_id"], "items": ["restaurant_id"], "orders": ["user_id", "date"],
    "events": ["user_id"], "batches": ["office_id", "date"], "restaurants": [],
}

DEFAULT_SQLITE = "camp.db"


class Store:
    def __init__(self, path_or_url: str = ":memory:"):
        self.url = path_or_url
        self.pg = path_or_url.startswith(("postgres://", "postgresql://"))
        if self.pg:
            import psycopg
            self.conn = psycopg.connect(path_or_url, autocommit=False)
        else:
            self.conn = sqlite3.connect(path_or_url, check_same_thread=False)
        self._migrate()

    @classmethod
    def from_env(cls) -> "Store":
        return cls(os.getenv("CAMP_DATABASE_URL") or os.getenv("CAMP_DB", DEFAULT_SQLITE))

    # ------------------------------------------------------------ schema
    def _migrate(self) -> None:
        cur = self.conn.cursor()
        for t in TABLES.values():
            if self.pg:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, data JSONB NOT NULL, "
                            f"updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
                for col in INDEXED[t]:
                    cur.execute(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} TEXT GENERATED ALWAYS AS (data->>'{col}') STORED")
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {t}_{col}_idx ON {t} ({col})")
            else:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
                for col in INDEXED[t]:
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {t}_{col}_idx ON {t} (json_extract(data, '$.{col}'))")
        self.conn.commit()

    # ------------------------------------------------------------ helpers
    def _q(self, sql: str) -> str:
        return sql if self.pg else sql.replace("%s", "?")

    def _where(self, table: str, col: str) -> str:
        return f"{col} = %s" if self.pg else f"json_extract(data, '$.{col}') = ?"

    def _rows(self, cls: type[T], sql: str, params: tuple = ()) -> list[T]:
        cur = self.conn.cursor()
        cur.execute(self._q(sql), params)
        rows = cur.fetchall()
        if self.pg:
            return [cls.model_validate(r[0]) for r in rows]           # JSONB comes back parsed
        return [cls.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------ CRUD
    def put(self, obj: BaseModel) -> None:
        self.put_many([obj])

    def put_many(self, objs: Iterable[BaseModel]) -> None:
        cur = self.conn.cursor()
        for o in objs:
            t = TABLES[type(o)]
            payload = o.model_dump_json()
            if self.pg:
                cur.execute(f"INSERT INTO {t} (id, data) VALUES (%s, %s::jsonb) "
                            f"ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()", (o.id, payload))  # type: ignore[attr-defined]
            else:
                cur.execute(f"INSERT OR REPLACE INTO {t} (id, data) VALUES (?, ?)", (o.id, payload))  # type: ignore[attr-defined]
        self.conn.commit()

    def delete_all(self, cls: type[BaseModel]) -> int:
        cur = self.conn.cursor()
        cur.execute(f"DELETE FROM {TABLES[cls]}")
        self.conn.commit()
        return cur.rowcount

    def get(self, cls: type[T], id: str) -> T | None:
        rows = self._rows(cls, f"SELECT data FROM {TABLES[cls]} WHERE id = %s", (id,))
        return rows[0] if rows else None

    def all(self, cls: type[T]) -> list[T]:
        return self._rows(cls, f"SELECT data FROM {TABLES[cls]}")

    def count(self, cls: type[BaseModel]) -> int:
        cur = self.conn.cursor()
        cur.execute(f"SELECT count(*) FROM {TABLES[cls]}")
        return int(cur.fetchone()[0])

    # ------------------------------------------------------------ indexed queries
    def users_in_office(self, office_id: str) -> list[User]:
        return self._rows(User, f"SELECT data FROM users WHERE {self._where('users', 'office_id')}", (office_id,))

    def items_for(self, restaurant_id: str) -> list[MenuItem]:
        return self._rows(MenuItem, f"SELECT data FROM items WHERE {self._where('items', 'restaurant_id')}", (restaurant_id,))

    def orders_for(self, user_id: str) -> list[Order]:
        return sorted(self._rows(Order, f"SELECT data FROM orders WHERE {self._where('orders', 'user_id')}", (user_id,)), key=lambda o: o.date)

    def events_for(self, user_id: str) -> list[FeedbackEvent]:
        return self._rows(FeedbackEvent, f"SELECT data FROM events WHERE {self._where('events', 'user_id')}", (user_id,))

    # ------------------------------------------------------------ ops
    def copy_from(self, other: "Store") -> dict[str, int]:
        """Copy every row from another store (e.g. the old SQLite file) into this one. Upserts by id."""
        counts: dict[str, int] = {}
        for cls, t in TABLES.items():
            rows = other.all(cls)
            self.put_many(rows)
            counts[t] = len(rows)
        return counts

    def close(self) -> None:
        self.conn.close()
