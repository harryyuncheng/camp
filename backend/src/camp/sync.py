"""Shared active orders for the native apps (Mac notch + iPhone Live Activity).

The backend is the authority for *which* sessions are current and their revisions; the Swift side owns the
transition rules (`LunchSession.applying`). Devices publish the result of a transition with the revision they
started from; a compare-and-swap either accepts it or hands back the newer record.

Several orders can be active at once (a morning coffee and a meal), so the state is a list of records keyed by
`sessionId`. The snapshot also exposes `record`: the *nearest* active order (earliest `arrivesAt` among those not
finished), which is what a single-card surface should show. Finished or day-old records are pruned on write.

Single user for now: no identity. `seq` increases on every accepted write so a device can long-poll
`wait_for_change(since=seq)` and get woken the moment the other device does something.

State lives in the `sync` table of the shared database (one row) so it survives restarts.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .models import SyncState
from .store import Store

FINISHED = {"delivered", "ended"}
KEEP_FINISHED_FOR = timedelta(hours=2)
KEEP_ANY_FOR = timedelta(hours=20)


class SyncConflict(Exception):
    def __init__(self, seq: int, record: Optional[dict], records: list[dict]):
        super().__init__("this order changed on another device")
        self.seq, self.record, self.records = seq, record, records


def _phase(record: dict) -> str:
    return str((record.get("session") or {}).get("phase", ""))


def _arrives(record: dict) -> float:
    """`arrivesAt` as Swift's JSONEncoder writes dates: seconds since 2001-01-01. Missing → sort last."""
    v = (record.get("session") or {}).get("arrivesAt")
    return float(v) if isinstance(v, (int, float)) else float("inf")


def _updated(record: dict) -> datetime:
    try:
        return datetime.fromisoformat(record["updatedAt"])
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc)


def nearest(records: list[dict]) -> Optional[dict]:
    """The order to show first: the unfinished one that arrives soonest, else the most recently touched one."""
    active = [r for r in records if _phase(r) not in FINISHED]
    if active:
        return min(active, key=_arrives)
    return max(records, key=_updated) if records else None


class LunchSyncService:
    def __init__(self, store: Store | None = None):
        self.store = store
        self.seq = 0
        self.records: list[dict[str, Any]] = []
        self._changed = asyncio.Condition()
        if self.store is not None:
            saved = self.store.get(SyncState, "lunch")
            if saved:
                self.seq = saved.seq
                self.records = list(saved.records) or ([saved.record] if saved.record else [])

    @property
    def record(self) -> Optional[dict]:
        return nearest(self.records)

    def snapshot(self) -> dict:
        return {"seq": self.seq, "record": self.record, "records": list(self.records)}

    def find(self, session_id: str) -> Optional[dict]:
        return next((r for r in self.records if r.get("sessionId") == session_id), None)

    async def wait_for_change(self, since: Optional[int], timeout: float) -> dict:
        """Returns immediately when the caller is behind; otherwise blocks up to `timeout` seconds."""
        if since is None or since != self.seq:
            return self.snapshot()
        async with self._changed:
            try:
                await asyncio.wait_for(self._changed.wait_for(lambda: self.seq != since), timeout)
            except asyncio.TimeoutError:
                pass
        return self.snapshot()

    async def publish(self, record: dict, expected_session_id: Optional[str], expected_revision: Optional[int],
                      device: str) -> dict:
        session_id, revision = str(record.get("sessionId", "")), int(record.get("revision", -1))
        if not session_id or revision < 0:
            raise ValueError("record needs sessionId and revision")
        current = self.find(session_id)
        if current is not None:
            # Same order: the writer must have started from the current revision and moved it forward.
            if expected_revision != current["revision"] or revision <= current["revision"]:
                raise SyncConflict(self.seq, current, list(self.records))
        elif expected_session_id is not None and self.find(expected_session_id) is None and self.records:
            # The writer believes an order is current that we no longer have: let them look first.
            raise SyncConflict(self.seq, self.record, list(self.records))
        stored = {**record, "device": device, "updatedAt": datetime.now(timezone.utc).isoformat()}
        records = [r for r in self.records if r.get("sessionId") != session_id] + [stored]
        await self._commit(self._prune(records))
        return self.snapshot()

    async def clear(self, session_id: Optional[str] = None) -> dict:
        """Forget one order, or every order when `session_id` is None."""
        await self._commit([] if session_id is None else [r for r in self.records if r.get("sessionId") != session_id])
        return self.snapshot()

    @staticmethod
    def _prune(records: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        kept = []
        for r in records:
            age = now - _updated(r)
            if age > KEEP_ANY_FOR or (_phase(r) in FINISHED and age > KEEP_FINISHED_FOR):
                continue
            kept.append(r)
        return sorted(kept, key=_arrives)

    async def _commit(self, records: list[dict]) -> None:
        async with self._changed:
            self.seq += 1
            self.records = records
            if self.store is not None:
                self.store.put(SyncState(seq=self.seq, record=nearest(records), records=records))
            self._changed.notify_all()
