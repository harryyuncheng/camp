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
import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

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
        value = datetime.fromisoformat(record["updatedAt"])
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc)


def _validate(record: dict) -> None:
    session_id, revision = record.get("sessionId"), record.get("revision")
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
        raise ValueError("record needs a nonempty sessionId")
    if type(revision) is not int or not 0 <= revision < 2**63:
        raise ValueError("record needs a nonnegative integer revision")
    session = record.get("session")
    if not isinstance(session, dict) or session.get("id") != session_id:
        raise ValueError("session.id must match sessionId")
    if type(session.get("revision")) is not int or session["revision"] != revision:
        raise ValueError("session.revision must match revision")
    if session.get("phase") not in ("choosing", "reviewing", "confirmed", "delivered", "ended"):
        raise ValueError("session.phase is invalid")
    for field in ("arrivesAt", "closesAt", "confirmedAt", "deliveredAt"):
        value = session.get(field)
        if value is not None and (type(value) not in (int, float) or not -1e15 <= value <= 1e15):
            raise ValueError(f"session.{field} must be a finite numeric date")
    if record.get("group") is not None and not isinstance(record["group"], dict):
        raise ValueError("record.group must be an object")
    try:
        json.dumps(record, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ValueError("record must contain finite JSON values") from e


def nearest(records: list[dict]) -> Optional[dict]:
    """The order to show first: the unfinished one that arrives soonest, else the most recently touched one."""
    active = [r for r in records if _phase(r) not in FINISHED]
    if active:
        return min(active, key=_arrives)
    return max(records, key=_updated) if records else None


class LunchSyncService:
    def __init__(self, store: Store | None = None):
        self.store = store
        # Set by the API layer to fan an accepted write out to Live Activity push tokens. It runs detached
        # so a slow or unreachable APNs never holds the compare-and-swap lock or delays the long-poll.
        self.on_change: Optional[Callable[[dict, str], Awaitable[None]]] = None
        # Same, for the records a `clear` removed: phones showing them get an "end" push.
        self.on_remove: Optional[Callable[[list[dict]], Awaitable[None]]] = None
        self.seq = 0
        self.records: list[dict] = []
        self._changed = asyncio.Condition()
        if self.store is not None:
            saved = self.store.get(SyncState, "lunch")
            if saved:
                self.seq = saved.seq
                self.records = list(saved.records) or ([saved.record] if saved.record else [])
                pruned = self._prune(self.records)
                if pruned != self.records:
                    self._commit(pruned)

    @property
    def record(self) -> Optional[dict]:
        return nearest(self.records)

    def snapshot(self) -> dict:
        return copy.deepcopy({"seq": self.seq, "record": self.record, "records": self.records})

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
        _validate(record)
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("expectedRevision must be a nonnegative integer")
        async with self._changed:
            session_id, revision = record["sessionId"], record["revision"]
            current = self.find(session_id)
            if current is not None:
                if expected_session_id != session_id or expected_revision != current["revision"] or revision <= current["revision"]:
                    raise SyncConflict(self.seq, current, list(self.records))
            elif expected_session_id is not None and self.find(expected_session_id) is None and (
                self.records or expected_session_id == session_id
            ):
                raise SyncConflict(self.seq, self.record, list(self.records))
            stored = {**copy.deepcopy(record), "device": device, "updatedAt": datetime.now(timezone.utc).isoformat()}
            records = [r for r in self.records if r.get("sessionId") != session_id] + [stored]
            self._commit(self._prune(records))
            self._changed.notify_all()
            self._fanout(stored, device)
            return self.snapshot()

    def _fanout(self, stored: dict, device: str) -> None:
        """Schedules the push for `stored`. Detached on purpose; failures are logged by the sender."""
        if self.on_change is None:
            return
        try:
            asyncio.get_running_loop().create_task(self.on_change(stored, device))
        except RuntimeError:  # no loop (tests calling publish synchronously) - nothing to push to
            pass

    def _fanout_removed(self, removed: list[dict]) -> None:
        if not removed or self.on_remove is None:
            return
        try:
            asyncio.get_running_loop().create_task(self.on_remove(removed))
        except RuntimeError:
            pass

    async def clear(self, session_id: Optional[str] = None) -> dict:
        """Forget one order, or every order when `session_id` is None."""
        async with self._changed:
            removed = [r for r in self.records if session_id is None or r.get("sessionId") == session_id]
            self._commit([r for r in self.records if r not in removed])
            self._changed.notify_all()
            self._fanout_removed(removed)
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

    def _commit(self, records: list[dict]) -> None:
        seq = self.seq + 1
        if self.store is not None:
            self.store.put(SyncState(seq=seq, record=nearest(records), records=records))
        self.seq, self.records = seq, records
