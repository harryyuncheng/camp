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
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, TypeVar

from pydantic import BaseModel

import threading

from .models import (Batch, FeedbackEvent, LunchGroup, MenuItem, Order, RampAttempt, RampOverageRequest, Restaurant,
                     ScheduledOrder, SyncState, User)

T = TypeVar("T", bound=BaseModel)

TABLES: dict[type[BaseModel], str] = {
    User: "users", Restaurant: "restaurants", MenuItem: "items",
    Order: "orders", Batch: "batches", FeedbackEvent: "events",
    LunchGroup: "groups", RampAttempt: "ramp_attempts", RampOverageRequest: "ramp_overages",
    SyncState: "sync", ScheduledOrder: "schedules",
}
# JSON keys promoted to indexed columns per table (used by the convenience queries)
INDEXED: dict[str, list[str]] = {
    "users": ["office_id"], "items": ["restaurant_id"], "orders": ["user_id", "date"],
    "events": ["user_id"], "batches": ["office_id", "date"], "restaurants": [],
    "groups": ["office_id", "date"], "ramp_attempts": [], "ramp_overages": ["ramp_user_id"], "sync": [], "schedules": ["user_id"],
}

DEFAULT_SQLITE = "camp.db"

# One backend-seeded group per office, day, restaurant and category. Two first loads racing for an empty day both
# try to seed; the second insert fails on this index and the caller re-reads instead of leaving a second set.
SEED_INDEX = "groups_seed_idx"
SEED_KEY = ("office_id", "date", "restaurant_id", "category")


class Store:
    def __init__(self, path_or_url: str = ":memory:"):
        self.url = path_or_url
        self.pg = path_or_url.startswith(("postgres://", "postgresql://"))
        if self.pg:
            import psycopg
            # autocommit: a plain SELECT must not leave a transaction open (that held an ACCESS SHARE lock on every
            # table and blocked schema migrations from any other process). Writes use an explicit transaction below.
            self.conn = psycopg.connect(path_or_url, autocommit=True)
        else:
            self.conn = sqlite3.connect(path_or_url, check_same_thread=False)
        self._lock = threading.RLock()
        self._tx_depth = 0
        self._migrate()

    @property
    def integrity_error(self) -> type[Exception]:
        """The backend's constraint-violation exception (what a seed that lost the race to another request raises)."""
        if self.pg:
            import psycopg
            return psycopg.IntegrityError
        return sqlite3.IntegrityError

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
        try:
            self._create_seed_index()
        except self.integrity_error:
            self.conn.rollback()
            self.dedupe_seeded_groups()
            self._create_seed_index()

    def _create_seed_index(self) -> None:
        cur = self.conn.cursor()
        if self.pg:
            cols = ", ".join(f"(data->>'{c}')" for c in SEED_KEY)
            cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {SEED_INDEX} ON groups ({cols}) "
                        f"WHERE (data->>'seeded') = 'true' AND (data->>'status') <> 'cancelled'")
        else:
            cols = ", ".join(f"json_extract(data, '$.{c}')" for c in SEED_KEY)
            cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {SEED_INDEX} ON groups ({cols}) "
                        f"WHERE json_extract(data, '$.seeded') = 1 AND json_extract(data, '$.status') <> 'cancelled'")
        self.conn.commit()

    def dedupe_seeded_groups(self) -> int:
        """Collapse seeded groups that share a SEED_KEY into the oldest one. Members the keeper lacks move over with
        their orders; members it already has get their duplicate orders cancelled. Returns the number of rows removed."""
        keepers: dict[tuple, LunchGroup] = {}
        removed = 0
        with self.transaction():
            for g in sorted(self.all(LunchGroup), key=lambda g: g.created_at):
                if not g.seeded or g.status == "cancelled":
                    continue
                key = (g.office_id, g.date, g.restaurant_id, g.category)
                keeper = keepers.setdefault(key, g)
                if keeper is g:
                    continue
                have = {m.user_id for m in keeper.members}
                for m in g.members:
                    orders = [o for oid in (m.order_ids or ([m.order_id] if m.order_id else [])) if (o := self.get(Order, oid))]
                    if m.user_id in have:
                        for o in orders:
                            o.status = "cancelled"
                    else:
                        for o in orders:
                            o.group_id = keeper.id
                        keeper.members.append(m)
                        have.add(m.user_id)
                    self.put_many(orders)
                self.delete(LunchGroup, g.id)
                removed += 1
            self.put_many(keepers.values())
        return removed

    # ------------------------------------------------------------ helpers
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

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group several writes so they commit together or not at all; nests (inner blocks join the outer one)."""
        with self._lock:
            if self.pg:
                with self.conn.transaction():
                    self._tx_depth += 1
                    try:
                        yield
                    finally:
                        self._tx_depth -= 1
                return
            self._tx_depth += 1
            try:
                yield
            except BaseException:
                if self._tx_depth == 1:
                    self.conn.rollback()
                raise
            else:
                if self._tx_depth == 1:
                    self.conn.commit()
            finally:
                self._tx_depth -= 1

    def _commit(self) -> None:
        if not self._tx_depth:
            self.conn.commit()

    # ------------------------------------------------------------ CRUD
    def put(self, obj: BaseModel) -> None:
        self.put_many([obj])

    def put_many(self, objs: Iterable[BaseModel]) -> None:
        with self._lock:
            if self.pg:
                with self.conn.transaction():
                    cur = self.conn.cursor()
                    for o in objs:
                        cur.execute(f"INSERT INTO {TABLES[type(o)]} (id, data) VALUES (%s, %s::jsonb) "
                                    f"ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()", (o.id, o.model_dump_json()))  # type: ignore[attr-defined]
                return
            cur = self.conn.cursor()
            for o in objs:
                # upsert by id only: INSERT OR REPLACE would silently evict a row that clashes on any other unique index
                cur.execute(f"INSERT INTO {TABLES[type(o)]} (id, data) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET data = excluded.data",
                            (o.id, o.model_dump_json()))  # type: ignore[attr-defined]
            self._commit()

    def delete_all(self, cls: type[BaseModel]) -> int:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(f"DELETE FROM {TABLES[cls]}")
            self._commit()
            return cur.rowcount

    def delete(self, cls: type[BaseModel], id: str) -> bool:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(self._q(f"DELETE FROM {TABLES[cls]} WHERE id = %s"), (id,))
            self._commit()
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
        counts: dict[str, int] = {}
        for cls, t in TABLES.items():
            rows = other.all(cls)
            self.put_many(rows)
            counts[t] = len(rows)
        return counts

    def close(self) -> None:
        self.conn.close()
