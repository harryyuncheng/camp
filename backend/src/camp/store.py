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
import threading
from contextlib import contextmanager
from typing import Iterable, Iterator, TypeVar

import psycopg
from pydantic import BaseModel

from .models import (ActivityPushToken, Batch, FeedbackEvent, LunchGroup, MenuItem, OfferRecord, Order, RampAttempt, RampOverageRequest, Restaurant,
                     ScheduledOrder, SyncState, User)

T = TypeVar("T", bound=BaseModel)

TABLES: dict[type[BaseModel], str] = {
    User: "users", Restaurant: "restaurants", MenuItem: "items",
    Order: "orders", Batch: "batches", FeedbackEvent: "events",
    LunchGroup: "groups", RampAttempt: "ramp_attempts", RampOverageRequest: "ramp_overages",
    SyncState: "sync", ScheduledOrder: "schedules", OfferRecord: "offers",
    ActivityPushToken: "activity_push_tokens",
}
# JSON keys promoted to indexed columns per table (used by the convenience queries)
INDEXED: dict[str, list[str]] = {
    "users": ["office_id"], "items": ["restaurant_id"], "orders": ["user_id", "date"],
    "events": ["user_id"], "batches": ["office_id", "date"], "restaurants": [],
    "groups": ["office_id", "date"], "ramp_attempts": [], "ramp_overages": ["ramp_user_id"], "sync": [], "schedules": ["user_id"], "activity_push_tokens": [],
    "offers": ["user_id", "date"],
}

DEFAULT_SQLITE = "camp.db"


class Store:
    def __init__(self, path_or_url: str = ":memory:"):
        self.url = path_or_url
        self.pg = path_or_url.startswith(("postgres://", "postgresql://"))
        if self.pg:
            # autocommit: a plain SELECT must not leave a transaction open (that held an ACCESS SHARE lock on every
            # table and blocked schema migrations from any other process). Writes use an explicit transaction below.
            self.conn = psycopg.connect(path_or_url, autocommit=True)
        else:
            self.conn = sqlite3.connect(path_or_url, check_same_thread=False, isolation_level=None)
        self._lock = threading.RLock()
        self._transaction_depth = 0
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
    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Atomic synchronous work on this connection; nested contexts use savepoints.

        The lock spans reads and writes. Do not hold a transaction across an await or a remote request.
        """
        with self._lock:
            if self.pg:
                with self.conn.transaction():
                    # One writer for synchronous read/modify/write operations across connections.
                    self.conn.execute("SELECT pg_advisory_xact_lock(1128353104)")
                    yield
                return
            depth = self._transaction_depth
            savepoint = f"camp_{depth}"
            self.conn.execute("BEGIN IMMEDIATE" if depth == 0 else f"SAVEPOINT {savepoint}")
            self._transaction_depth += 1
            try:
                yield
                self.conn.execute("COMMIT" if depth == 0 else f"RELEASE SAVEPOINT {savepoint}")
            except BaseException:
                if depth == 0:
                    self.conn.rollback()
                else:
                    self.conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self.conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            finally:
                self._transaction_depth -= 1

    def _q(self, sql: str) -> str:
        return sql if self.pg else sql.replace("%s", "?")

    def _where(self, table: str, col: str) -> str:
        return f"{col} = %s" if self.pg else f"json_extract(data, '$.{col}') = ?"

    def _rows(self, cls: type[T], sql: str, params: tuple = ()) -> list[T]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(self._q(sql), params)
            rows = cur.fetchall()
        if self.pg:
            return [cls.model_validate(r[0]) for r in rows]           # JSONB comes back parsed
        return [cls.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------ CRUD
    def put(self, obj: BaseModel) -> None:
        self.put_many([obj])

    def insert_event(self, event: FeedbackEvent) -> bool:
        with self.transaction():
            cur = self.conn.cursor()
            value = "%s::jsonb" if self.pg else "%s"
            cur.execute(self._q(f"INSERT INTO events (id, data) VALUES (%s, {value}) ON CONFLICT (id) DO NOTHING"),
                        (event.id, event.model_dump_json()))
            return cur.rowcount == 1

    def put_many(self, objs: Iterable[BaseModel]) -> None:
        with self.transaction():
            cur = self.conn.cursor()
            for o in objs:
                if self.pg:
                    cur.execute(f"INSERT INTO {TABLES[type(o)]} (id, data) VALUES (%s, %s::jsonb) "
                                f"ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()", (o.id, o.model_dump_json()))  # type: ignore[attr-defined]
                else:
                    cur.execute(f"INSERT OR REPLACE INTO {TABLES[type(o)]} (id, data) VALUES (?, ?)", (o.id, o.model_dump_json()))  # type: ignore[attr-defined]

    def delete_all(self, cls: type[BaseModel]) -> int:
        with self.transaction():
            cur = self.conn.cursor()
            cur.execute(f"DELETE FROM {TABLES[cls]}")
            return cur.rowcount

    def delete(self, cls: type[BaseModel], id: str) -> bool:
        with self.transaction():
            cur = self.conn.cursor()
            cur.execute(self._q(f"DELETE FROM {TABLES[cls]} WHERE id = %s"), (id,))
            return cur.rowcount > 0

    def get(self, cls: type[T], id: str) -> T | None:
        rows = self._rows(cls, f"SELECT data FROM {TABLES[cls]} WHERE id = %s", (id,))
        return rows[0] if rows else None

    def all(self, cls: type[T]) -> list[T]:
        return self._rows(cls, f"SELECT data FROM {TABLES[cls]}")

    def count(self, cls: type[BaseModel]) -> int:
        with self._lock:
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

    def schedules_for(self, user_id: str) -> list[ScheduledOrder]:
        return sorted(self._rows(ScheduledOrder, f"SELECT data FROM schedules WHERE {self._where('schedules', 'user_id')}", (user_id,)),
                      key=lambda s: (s.time_minutes, s.created_at))

    def overages_for(self, ramp_user_id: str) -> list[RampOverageRequest]:
        rows = self._rows(RampOverageRequest,
                          f"SELECT data FROM ramp_overages WHERE {self._where('ramp_overages', 'ramp_user_id')}", (ramp_user_id,))
        return sorted(rows, key=lambda r: r.created_at, reverse=True)

    def groups_for(self, office_id: str, date: str) -> list[LunchGroup]:
        rows = self._rows(LunchGroup, f"SELECT data FROM groups WHERE {self._where('groups', 'office_id')} AND {self._where('groups', 'date')}",
                          (office_id, date))
        return sorted(rows, key=lambda g: (g.delivery_minutes, g.created_at))

    # ------------------------------------------------------------ ops
    def copy_from(self, other: "Store") -> dict[str, int]:
        """Copy every row from another store (e.g. the old SQLite file) into this one. Upserts by id."""
        with other.transaction():
            snapshot = [(t, other.all(cls)) for cls, t in TABLES.items()]
        counts: dict[str, int] = {}
        with self.transaction():
            for t, rows in snapshot:
                self.put_many(rows)
                counts[t] = len(rows)
        return counts

    def close(self) -> None:
        with self._lock:
            self.conn.close()
