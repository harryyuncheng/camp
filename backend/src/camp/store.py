"""SQLite store: one table per entity, JSON payload. Deliberately simple."""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable, TypeVar

from pydantic import BaseModel

from .models import Batch, FeedbackEvent, MenuItem, Order, Restaurant, User

T = TypeVar("T", bound=BaseModel)

TABLES: dict[type[BaseModel], str] = {
    User: "users", Restaurant: "restaurants", MenuItem: "items",
    Order: "orders", Batch: "batches", FeedbackEvent: "events",
}


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        for t in TABLES.values():
            self.conn.execute(f"CREATE TABLE IF NOT EXISTS {t} (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.conn.commit()

    def put(self, obj: BaseModel) -> None:
        t = TABLES[type(obj)]
        self.conn.execute(f"INSERT OR REPLACE INTO {t} (id, data) VALUES (?, ?)",
                          (obj.id, obj.model_dump_json()))  # type: ignore[attr-defined]
        self.conn.commit()

    def put_many(self, objs: Iterable[BaseModel]) -> None:
        for o in objs:
            self.put(o)

    def get(self, cls: type[T], id: str) -> T | None:
        row = self.conn.execute(f"SELECT data FROM {TABLES[cls]} WHERE id = ?", (id,)).fetchone()
        return cls.model_validate_json(row[0]) if row else None

    def all(self, cls: type[T]) -> list[T]:
        rows = self.conn.execute(f"SELECT data FROM {TABLES[cls]}").fetchall()
        return [cls.model_validate_json(r[0]) for r in rows]

    # convenience queries (filter in Python; fine at hackathon scale)
    def users_in_office(self, office_id: str) -> list[User]:
        return [u for u in self.all(User) if u.office_id == office_id]

    def items_for(self, restaurant_id: str) -> list[MenuItem]:
        return [i for i in self.all(MenuItem) if i.restaurant_id == restaurant_id]

    def orders_for(self, user_id: str) -> list[Order]:
        return sorted((o for o in self.all(Order) if o.user_id == user_id), key=lambda o: o.date)

    def events_for(self, user_id: str) -> list[FeedbackEvent]:
        return [e for e in self.all(FeedbackEvent) if e.user_id == user_id]
