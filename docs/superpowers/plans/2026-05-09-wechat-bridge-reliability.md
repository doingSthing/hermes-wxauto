# WeChat Bridge Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reliable local message-capture core for `my-wxauto`: dedup messages, batch per conversation, process up to five unread chats per drain, and expose a batch listener entry point.

**Architecture:** Add focused bridge modules for normalized events, SQLite-backed state, and per-conversation batching. Extend the existing `probes` drain path so it can open several unread sessions and report each session as soon as it is read. Keep all WeChat UI access in the existing probe/listener path and keep model/framework integration outside this plan.

**Tech Stack:** Python 3.9+, standard library `dataclasses`, `hashlib`, `json`, `sqlite3`, `time`, existing `pytest` tests, existing `pywinauto`/Win32 code behind probes.

---

## File Structure

- Create `src/my_wxauto/bridge_events.py`
  - Owns normalized bridge message and conversation batch dataclasses.
  - Owns soft message key generation from `ChatMessage` data.
  - Contains no SQLite, UI automation, or thread logic.

- Create `src/my_wxauto/bridge_store.py`
  - Owns SQLite schema and persistence for seen messages, conversation batches, and outgoing echoes.
  - Contains no UI automation and no batching timers.

- Create `src/my_wxauto/bridge_batcher.py`
  - Owns per-conversation open batches and freeze rules.
  - Uses `BridgeStore` for dedup and echo suppression.
  - Contains no WeChat UI automation.

- Modify `src/my_wxauto/probes.py`
  - Add `max_unread_chats`, `max_ui_busy_seconds`, and `on_chat_opened` plumbing to unread drain collection.
  - Replace the hard-coded `unread_sessions[:1]` with bounded iteration.

- Modify `src/my_wxauto/listener.py`
  - Add `listen_conversation_batches`.
  - Keep `listen_new_messages` behavior compatible.
  - Convert opened unread chat payloads into bridge batches through `ConversationBatcher`.

- Modify `src/my_wxauto/wechat.py`
  - Add `WeChat.listen_conversation_batches` delegation.

- Modify `src/my_wxauto/__init__.py`
  - Export bridge dataclasses that are part of the public capability.

- Tests:
  - Create `tests/test_bridge_events.py`
  - Create `tests/test_bridge_store.py`
  - Create `tests/test_bridge_batcher.py`
  - Create `tests/test_bridge_listener.py`
  - Modify `tests/test_probes.py`
  - Modify `tests/test_listener.py`

---

### Task 1: Normalized Bridge Events And Soft Message Keys

**Files:**
- Create: `src/my_wxauto/bridge_events.py`
- Create: `tests/test_bridge_events.py`

- [ ] **Step 1: Write failing tests for stable message keys and batch serialization**

Create `tests/test_bridge_events.py` with:

```python
from __future__ import annotations

from my_wxauto.bridge_events import (
    BridgeMessage,
    ConversationBatch,
    make_message_key,
    messages_from_chat_payload,
)


def test_make_message_key_is_stable_for_same_message() -> None:
    first = BridgeMessage(
        chat_name="alice",
        content="hello",
        message_type="text",
        sender="alice",
        is_self=False,
        time_text="15:41",
        occurrence_index=0,
    )
    second = BridgeMessage(
        chat_name="alice",
        content="hello",
        message_type="text",
        sender="alice",
        is_self=False,
        time_text="15:41",
        occurrence_index=0,
    )

    assert make_message_key(first) == make_message_key(second)
    assert len(make_message_key(first)) == 64


def test_make_message_key_uses_occurrence_index_for_repeated_text() -> None:
    first = BridgeMessage(chat_name="alice", content="ok", occurrence_index=0)
    second = BridgeMessage(chat_name="alice", content="ok", occurrence_index=1)

    assert make_message_key(first) != make_message_key(second)


def test_messages_from_chat_payload_adds_keys_and_occurrence_indexes() -> None:
    messages = messages_from_chat_payload(
        {
            "chat_name": "alice",
            "messages": [
                {"content": "ok", "message_type": "text", "sender": "alice"},
                {"content": "ok", "message_type": "text", "sender": "alice"},
            ],
        }
    )

    assert [message.occurrence_index for message in messages] == [0, 1]
    assert messages[0].message_key != messages[1].message_key
    assert messages[0].to_dict()["chat_name"] == "alice"


def test_conversation_batch_to_event_dict() -> None:
    message = BridgeMessage(
        chat_name="alice",
        content="hello",
        sender="alice",
        occurrence_index=0,
    ).with_key()
    batch = ConversationBatch(
        batch_id="batch-1",
        chat_name="alice",
        messages=(message,),
        created_at=10.0,
        frozen_at=11.0,
        status="frozen",
    )

    payload = batch.to_event_dict()

    assert payload["batch_id"] == "batch-1"
    assert payload["event_id"] == "batch-1"
    assert payload["platform"] == "wechat_desktop"
    assert payload["chat_id"] == "wechat:alice"
    assert payload["messages"][0]["content"] == "hello"
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_bridge_events.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'my_wxauto.bridge_events'`.

- [ ] **Step 3: Implement `bridge_events.py`**

Create `src/my_wxauto/bridge_events.py`:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


PLATFORM = "wechat_desktop"


@dataclass(frozen=True)
class BridgeMessage:
    chat_name: str
    content: str
    message_type: str = "unknown"
    sender: str | None = None
    is_self: bool | None = None
    time_text: str | None = None
    occurrence_index: int = 0
    message_key: str = ""
    raw: dict[str, Any] | None = None

    def with_key(self) -> "BridgeMessage":
        if self.message_key:
            return self
        return BridgeMessage(
            chat_name=self.chat_name,
            content=self.content,
            message_type=self.message_type,
            sender=self.sender,
            is_self=self.is_self,
            time_text=self.time_text,
            occurrence_index=self.occurrence_index,
            message_key=make_message_key(self),
            raw=self.raw,
        )

    def to_dict(self) -> dict[str, Any]:
        keyed = self.with_key()
        return {
            "message_key": keyed.message_key,
            "chat_name": keyed.chat_name,
            "sender": keyed.sender,
            "is_self": keyed.is_self,
            "message_type": keyed.message_type,
            "content": keyed.content,
            "time_text": keyed.time_text,
            "occurrence_index": keyed.occurrence_index,
            "raw": keyed.raw or {},
        }


@dataclass(frozen=True)
class ConversationBatch:
    batch_id: str
    chat_name: str
    messages: tuple[BridgeMessage, ...]
    created_at: float
    frozen_at: float | None = None
    submitted_at: float | None = None
    completed_at: float | None = None
    status: str = "open"

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def to_event_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.batch_id,
            "batch_id": self.batch_id,
            "platform": PLATFORM,
            "chat_id": f"wechat:{self.chat_name}",
            "chat_name": self.chat_name,
            "status": self.status,
            "created_at": self.created_at,
            "frozen_at": self.frozen_at,
            "submitted_at": self.submitted_at,
            "completed_at": self.completed_at,
            "message_count": self.message_count,
            "messages": [message.with_key().to_dict() for message in self.messages],
        }


def make_message_key(message: BridgeMessage) -> str:
    payload = {
        "chat_name": message.chat_name,
        "sender": message.sender,
        "is_self": message.is_self,
        "message_type": message.message_type,
        "content": message.content,
        "time_text": message.time_text,
        "occurrence_index": message.occurrence_index,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def messages_from_chat_payload(chat: dict[str, Any]) -> tuple[BridgeMessage, ...]:
    chat_name = str(chat.get("chat_name") or "")
    result: list[BridgeMessage] = []
    for index, payload in enumerate(chat.get("messages") or []):
        if not isinstance(payload, dict):
            continue
        content = str(payload.get("content") or payload.get("raw_name") or "")
        if not content:
            continue
        message = BridgeMessage(
            chat_name=chat_name,
            content=content,
            message_type=str(payload.get("message_type") or "unknown"),
            sender=_optional_str(payload.get("sender")),
            is_self=_optional_bool(payload.get("is_self")),
            time_text=_optional_str(payload.get("time_text")),
            occurrence_index=index,
            raw=payload,
        ).with_key()
        result.append(message)
    return tuple(result)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None
```

- [ ] **Step 4: Run tests for Task 1**

Run:

```powershell
pytest tests/test_bridge_events.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add src/my_wxauto/bridge_events.py tests/test_bridge_events.py
git commit -m "Add bridge event models"
```

---

### Task 2: SQLite Bridge Store

**Files:**
- Create: `src/my_wxauto/bridge_store.py`
- Create: `tests/test_bridge_store.py`

- [ ] **Step 1: Write failing tests for seen messages, batches, and outgoing echoes**

Create `tests/test_bridge_store.py` with:

```python
from __future__ import annotations

from my_wxauto.bridge_events import BridgeMessage, ConversationBatch
from my_wxauto.bridge_store import BridgeStore


def test_store_records_seen_message_once(tmp_path) -> None:
    store = BridgeStore(tmp_path / "bridge.sqlite3")
    message = BridgeMessage(chat_name="alice", content="hello", occurrence_index=0).with_key()

    assert store.record_seen_message(message, now=10.0) is True
    assert store.record_seen_message(message, now=12.0) is False
    assert store.is_seen(message.message_key) is True


def test_store_saves_and_updates_batch(tmp_path) -> None:
    store = BridgeStore(tmp_path / "bridge.sqlite3")
    message = BridgeMessage(chat_name="alice", content="hello", occurrence_index=0).with_key()
    batch = ConversationBatch(
        batch_id="batch-1",
        chat_name="alice",
        messages=(message,),
        created_at=10.0,
        frozen_at=11.0,
        status="frozen",
    )

    store.save_batch(batch)
    store.mark_batch_submitted("batch-1", submitted_at=12.0)
    store.mark_batch_completed("batch-1", completed_at=13.0)

    row = store.get_batch("batch-1")

    assert row is not None
    assert row["status"] == "completed"
    assert row["message_count"] == 1
    assert row["submitted_at"] == 12.0
    assert row["completed_at"] == 13.0


def test_store_matches_outgoing_echo_until_expiry(tmp_path) -> None:
    store = BridgeStore(tmp_path / "bridge.sqlite3")

    store.record_outgoing_echo("alice", "hello", sent_at=10.0, ttl_seconds=30.0)

    assert store.matches_outgoing_echo("alice", "hello", now=20.0) is True
    assert store.matches_outgoing_echo("alice", "hello", now=41.0) is False
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_bridge_store.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'my_wxauto.bridge_store'`.

- [ ] **Step 3: Implement `bridge_store.py`**

Create `src/my_wxauto/bridge_store.py`:

```python
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .bridge_events import BridgeMessage, ConversationBatch


class BridgeStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def record_seen_message(self, message: BridgeMessage, *, now: float | None = None) -> bool:
        keyed = message.with_key()
        timestamp = _now(now)
        payload = json.dumps(keyed.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    insert into seen_messages(message_key, chat_name, first_seen_at, last_seen_at, payload_json)
                    values (?, ?, ?, ?, ?)
                    """,
                    (keyed.message_key, keyed.chat_name, timestamp, timestamp, payload),
                )
                return True
            except sqlite3.IntegrityError:
                conn.execute(
                    "update seen_messages set last_seen_at = ? where message_key = ?",
                    (timestamp, keyed.message_key),
                )
                return False

    def is_seen(self, message_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "select 1 from seen_messages where message_key = ?",
                (message_key,),
            ).fetchone()
        return row is not None

    def save_batch(self, batch: ConversationBatch) -> None:
        payload = json.dumps(batch.to_event_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into conversation_batches(
                    batch_id, chat_name, status, created_at, frozen_at,
                    submitted_at, completed_at, message_count, payload_json
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch.batch_id,
                    batch.chat_name,
                    batch.status,
                    batch.created_at,
                    batch.frozen_at,
                    batch.submitted_at,
                    batch.completed_at,
                    batch.message_count,
                    payload,
                ),
            )

    def mark_batch_submitted(self, batch_id: str, *, submitted_at: float | None = None) -> None:
        timestamp = _now(submitted_at)
        with self._connect() as conn:
            conn.execute(
                "update conversation_batches set status = ?, submitted_at = ? where batch_id = ?",
                ("submitted", timestamp, batch_id),
            )

    def mark_batch_completed(self, batch_id: str, *, completed_at: float | None = None) -> None:
        timestamp = _now(completed_at)
        with self._connect() as conn:
            conn.execute(
                "update conversation_batches set status = ?, completed_at = ? where batch_id = ?",
                ("completed", timestamp, batch_id),
            )

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select batch_id, chat_name, status, created_at, frozen_at,
                       submitted_at, completed_at, message_count, payload_json
                from conversation_batches
                where batch_id = ?
                """,
                (batch_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def record_outgoing_echo(
        self,
        chat_name: str,
        content: str,
        *,
        sent_at: float | None = None,
        ttl_seconds: float = 300.0,
    ) -> str:
        timestamp = _now(sent_at)
        echo_key = _echo_key(chat_name, content)
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into outgoing_echoes(echo_key, chat_name, content, sent_at, expires_at)
                values (?, ?, ?, ?, ?)
                """,
                (echo_key, chat_name, content, timestamp, timestamp + ttl_seconds),
            )
        return echo_key

    def matches_outgoing_echo(self, chat_name: str, content: str, *, now: float | None = None) -> bool:
        timestamp = _now(now)
        self.prune_expired_echoes(now=timestamp)
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1 from outgoing_echoes
                where echo_key = ? and expires_at >= ?
                """,
                (_echo_key(chat_name, content), timestamp),
            ).fetchone()
        return row is not None

    def prune_expired_echoes(self, *, now: float | None = None) -> int:
        timestamp = _now(now)
        with self._connect() as conn:
            cursor = conn.execute(
                "delete from outgoing_echoes where expires_at < ?",
                (timestamp,),
            )
            return int(cursor.rowcount or 0)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists seen_messages (
                    message_key text primary key,
                    chat_name text not null,
                    first_seen_at real not null,
                    last_seen_at real not null,
                    payload_json text not null
                );

                create table if not exists conversation_batches (
                    batch_id text primary key,
                    chat_name text not null,
                    status text not null,
                    created_at real not null,
                    frozen_at real,
                    submitted_at real,
                    completed_at real,
                    message_count integer not null,
                    payload_json text not null
                );

                create table if not exists outgoing_echoes (
                    echo_key text primary key,
                    chat_name text not null,
                    content text not null,
                    sent_at real not null,
                    expires_at real not null
                );
                """
            )


def _echo_key(chat_name: str, content: str) -> str:
    raw = json.dumps({"chat_name": chat_name, "content": content}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now(value: float | None) -> float:
    return time.time() if value is None else float(value)
```

- [ ] **Step 4: Run tests for Task 2**

Run:

```powershell
pytest tests/test_bridge_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add src/my_wxauto/bridge_store.py tests/test_bridge_store.py
git commit -m "Add bridge SQLite store"
```

---

### Task 3: Per-Conversation Batcher

**Files:**
- Create: `src/my_wxauto/bridge_batcher.py`
- Create: `tests/test_bridge_batcher.py`

- [ ] **Step 1: Write failing tests for dedup, freeze rules, and echo suppression**

Create `tests/test_bridge_batcher.py` with:

```python
from __future__ import annotations

from my_wxauto.bridge_batcher import BatchingConfig, ConversationBatcher
from my_wxauto.bridge_events import BridgeMessage
from my_wxauto.bridge_store import BridgeStore


def _message(chat: str, content: str, index: int = 0, *, is_self: bool | None = False) -> BridgeMessage:
    return BridgeMessage(
        chat_name=chat,
        content=content,
        message_type="text",
        sender="alice",
        is_self=is_self,
        time_text="15:41",
        occurrence_index=index,
    ).with_key()


def test_batcher_deduplicates_repeated_messages(tmp_path) -> None:
    batcher = ConversationBatcher(BridgeStore(tmp_path / "bridge.sqlite3"))
    message = _message("alice", "hello")

    assert batcher.add_messages("alice", (message,), now=10.0) == 1
    assert batcher.add_messages("alice", (message,), now=11.0) == 0

    assert batcher.open_batch_for("alice") is not None
    assert batcher.open_batch_for("alice").message_count == 1


def test_batcher_ignores_self_messages(tmp_path) -> None:
    batcher = ConversationBatcher(BridgeStore(tmp_path / "bridge.sqlite3"))

    added = batcher.add_messages("alice", (_message("alice", "robot", is_self=True),), now=10.0)

    assert added == 0
    assert batcher.open_batch_for("alice") is None


def test_batcher_suppresses_recent_outgoing_echo(tmp_path) -> None:
    store = BridgeStore(tmp_path / "bridge.sqlite3")
    store.record_outgoing_echo("alice", "hello", sent_at=10.0, ttl_seconds=30.0)
    batcher = ConversationBatcher(store)

    added = batcher.add_messages("alice", (_message("alice", "hello"),), now=20.0)

    assert added == 0
    assert batcher.open_batch_for("alice") is None


def test_batcher_freezes_by_quiet_window(tmp_path) -> None:
    config = BatchingConfig(quiet_window_seconds=1.5, max_batch_wait_seconds=8.0, max_batch_messages=10)
    batcher = ConversationBatcher(BridgeStore(tmp_path / "bridge.sqlite3"), config=config)

    batcher.add_messages("alice", (_message("alice", "hello"),), now=10.0)

    assert batcher.freeze_due_batches(now=11.0) == ()
    frozen = batcher.freeze_due_batches(now=11.6)

    assert len(frozen) == 1
    assert frozen[0].status == "frozen"
    assert frozen[0].frozen_at == 11.6
    assert batcher.open_batch_for("alice") is None


def test_batcher_freezes_by_max_wait_when_chat_stays_busy(tmp_path) -> None:
    config = BatchingConfig(quiet_window_seconds=1.5, max_batch_wait_seconds=8.0, max_batch_messages=10)
    batcher = ConversationBatcher(BridgeStore(tmp_path / "bridge.sqlite3"), config=config)

    batcher.add_messages("alice", (_message("alice", "m1", 0),), now=10.0)
    batcher.add_messages("alice", (_message("alice", "m2", 1),), now=17.9)

    frozen = batcher.freeze_due_batches(now=18.1)

    assert len(frozen) == 1
    assert [message.content for message in frozen[0].messages] == ["m1", "m2"]


def test_batcher_freezes_by_message_count(tmp_path) -> None:
    config = BatchingConfig(quiet_window_seconds=1.5, max_batch_wait_seconds=8.0, max_batch_messages=2)
    batcher = ConversationBatcher(BridgeStore(tmp_path / "bridge.sqlite3"), config=config)

    frozen = batcher.add_messages(
        "alice",
        (_message("alice", "m1", 0), _message("alice", "m2", 1)),
        now=10.0,
    )

    assert frozen == 2
    due = batcher.freeze_due_batches(now=10.0)
    assert len(due) == 1
    assert due[0].message_count == 2
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_bridge_batcher.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'my_wxauto.bridge_batcher'`.

- [ ] **Step 3: Implement `bridge_batcher.py`**

Create `src/my_wxauto/bridge_batcher.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass

from .bridge_events import BridgeMessage, ConversationBatch
from .bridge_store import BridgeStore


@dataclass(frozen=True)
class BatchingConfig:
    quiet_window_seconds: float = 1.5
    max_batch_wait_seconds: float = 8.0
    max_batch_messages: int = 10


@dataclass(frozen=True)
class _OpenBatch:
    batch_id: str
    chat_name: str
    messages: tuple[BridgeMessage, ...]
    created_at: float
    last_message_at: float

    @property
    def message_count(self) -> int:
        return len(self.messages)


class ConversationBatcher:
    def __init__(self, store: BridgeStore, *, config: BatchingConfig | None = None) -> None:
        self.store = store
        self.config = config or BatchingConfig()
        self._open: dict[str, _OpenBatch] = {}

    def add_messages(self, chat_name: str, messages: tuple[BridgeMessage, ...], *, now: float) -> int:
        accepted: list[BridgeMessage] = []
        for message in messages:
            keyed = message.with_key()
            if keyed.is_self is True:
                continue
            if self.store.matches_outgoing_echo(chat_name, keyed.content, now=now):
                continue
            if not self.store.record_seen_message(keyed, now=now):
                continue
            accepted.append(keyed)
        if not accepted:
            return 0

        existing = self._open.get(chat_name)
        if existing is None:
            self._open[chat_name] = _OpenBatch(
                batch_id=f"wechat-batch-{uuid.uuid4().hex}",
                chat_name=chat_name,
                messages=tuple(accepted),
                created_at=now,
                last_message_at=now,
            )
        else:
            self._open[chat_name] = _OpenBatch(
                batch_id=existing.batch_id,
                chat_name=existing.chat_name,
                messages=(*existing.messages, *accepted),
                created_at=existing.created_at,
                last_message_at=now,
            )
        return len(accepted)

    def open_batch_for(self, chat_name: str) -> _OpenBatch | None:
        return self._open.get(chat_name)

    def freeze_due_batches(self, *, now: float) -> tuple[ConversationBatch, ...]:
        frozen: list[ConversationBatch] = []
        for chat_name, batch in list(self._open.items()):
            if not self._is_due(batch, now=now):
                continue
            event = ConversationBatch(
                batch_id=batch.batch_id,
                chat_name=batch.chat_name,
                messages=batch.messages,
                created_at=batch.created_at,
                frozen_at=now,
                status="frozen",
            )
            self.store.save_batch(event)
            frozen.append(event)
            del self._open[chat_name]
        return tuple(frozen)

    def _is_due(self, batch: _OpenBatch, *, now: float) -> bool:
        if batch.message_count >= self.config.max_batch_messages:
            return True
        if now - batch.created_at >= self.config.max_batch_wait_seconds:
            return True
        return now - batch.last_message_at >= self.config.quiet_window_seconds
```

- [ ] **Step 4: Run tests for Task 3**

Run:

```powershell
pytest tests/test_bridge_batcher.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add src/my_wxauto/bridge_batcher.py tests/test_bridge_batcher.py
git commit -m "Add conversation batcher"
```

---

### Task 4: Multi-Conversation Drain In Probes

**Files:**
- Modify: `src/my_wxauto/probes.py`
- Modify: `tests/test_probes.py`

- [ ] **Step 1: Write failing tests for `max_unread_chats` and immediate per-chat callback**

Append these tests to `tests/test_probes.py`:

```python

def test_open_unread_sessions_respects_max_unread_chats_and_reports_each_chat(monkeypatch) -> None:
    window = WeChatWindow(
        hwnd=100,
        title="WeChat",
        class_name="Qt51514QWindowIcon",
        pid=42,
        process_name="Weixin.exe",
        exe=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
        rect=WindowRect(100, 200, 1000, 900),
        visible=True,
        minimized=False,
    )
    sessions = [
        {"chat_name": "a", "rect": {"left": 300, "top": 280, "right": 540, "bottom": 340}},
        {"chat_name": "b", "rect": {"left": 300, "top": 340, "right": 540, "bottom": 400}},
        {"chat_name": "c", "rect": {"left": 300, "top": 400, "right": 540, "bottom": 460}},
    ]
    clicked: list[tuple[int, int]] = []
    reported: list[str] = []

    def fake_collect(window_arg, *, region, max_controls):
        chat_name = sessions[len(clicked) - 1]["chat_name"]
        return [
            {
                "name": f"message from {chat_name}",
                "control_type": "ListItem",
                "class_name": "mmui::ChatTextItemView",
                "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                "rect": {"left": 542, "top": 591, "right": 1118, "bottom": 647},
            }
        ]

    monkeypatch.setattr(probes, "_click_point", lambda point: clicked.append(point))
    monkeypatch.setattr(probes, "_collect_uia_controls", fake_collect)
    monkeypatch.setattr(probes.time, "sleep", lambda _seconds: None)

    opened = probes._open_unread_sessions_and_collect_messages(
        window,
        sessions,
        max_controls=12,
        max_unread_chats=2,
        on_chat_opened=lambda chat: reported.append(chat["chat_name"]),
    )

    assert [chat["chat_name"] for chat in opened] == ["a", "b"]
    assert reported == ["a", "b"]
    assert len(clicked) == 2


def test_open_unread_sessions_stops_at_ui_busy_budget(monkeypatch) -> None:
    window = WeChatWindow(
        hwnd=100,
        title="WeChat",
        class_name="Qt51514QWindowIcon",
        pid=42,
        process_name="Weixin.exe",
        exe=r"C:\Program Files\Tencent\Weixin\Weixin.exe",
        rect=WindowRect(100, 200, 1000, 900),
        visible=True,
        minimized=False,
    )
    sessions = [
        {"chat_name": "a", "rect": {"left": 300, "top": 280, "right": 540, "bottom": 340}},
        {"chat_name": "b", "rect": {"left": 300, "top": 340, "right": 540, "bottom": 400}},
    ]
    times = iter([100.0, 100.0, 116.0, 116.0])

    monkeypatch.setattr(probes.time, "perf_counter", lambda: next(times, 116.0))
    monkeypatch.setattr(probes.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(probes, "_click_point", lambda _point: None)
    monkeypatch.setattr(
        probes,
        "_collect_uia_controls",
        lambda *_args, **_kwargs: [
            {
                "name": "hello",
                "control_type": "ListItem",
                "class_name": "mmui::ChatTextItemView",
                "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                "rect": {"left": 542, "top": 591, "right": 1118, "bottom": 647},
            }
        ],
    )

    opened = probes._open_unread_sessions_and_collect_messages(
        window,
        sessions,
        max_controls=12,
        max_unread_chats=5,
        max_ui_busy_seconds=15.0,
    )

    assert [chat["chat_name"] for chat in opened] == ["a"]
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_probes.py::test_open_unread_sessions_respects_max_unread_chats_and_reports_each_chat tests/test_probes.py::test_open_unread_sessions_stops_at_ui_busy_budget -q
```

Expected: FAIL with `TypeError` for unexpected keyword arguments.

- [ ] **Step 3: Update `_probe_sessions_after_wakeup` signature and call site**

In `src/my_wxauto/probes.py`, change `_probe_sessions_after_wakeup` signature from:

```python
def _probe_sessions_after_wakeup(
    *,
    max_controls: int,
    restore_icons: list[dict[str, Any]] | None = None,
    open_unread_messages: bool = False,
    report_progress: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
```

to:

```python
def _probe_sessions_after_wakeup(
    *,
    max_controls: int,
    restore_icons: list[dict[str, Any]] | None = None,
    open_unread_messages: bool = False,
    report_progress: Callable[[str, dict[str, Any] | None], None] | None = None,
    max_unread_chats: int = 1,
    max_ui_busy_seconds: float = 15.0,
    on_chat_opened: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
```

Then change the call to `_open_unread_sessions_and_collect_messages` to:

```python
        opened_unread_chats = _open_unread_sessions_and_collect_messages(
            ready,
            message_targets,
            max_controls=max_controls,
            report_progress=report_progress,
            max_unread_chats=max_unread_chats,
            max_ui_busy_seconds=max_ui_busy_seconds,
            on_chat_opened=on_chat_opened,
        )
```

- [ ] **Step 4: Update `_open_unread_sessions_and_collect_messages`**

Change the function signature to:

```python
def _open_unread_sessions_and_collect_messages(
    window: WeChatWindow,
    unread_sessions: list[dict[str, Any]],
    *,
    max_controls: int,
    report_progress: Callable[[str, dict[str, Any] | None], None] | None = None,
    max_unread_chats: int = 1,
    max_ui_busy_seconds: float = 15.0,
    on_chat_opened: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
```

Replace:

```python
    opened: list[dict[str, Any]] = []
    for index, session in enumerate(unread_sessions[:1]):
```

with:

```python
    opened: list[dict[str, Any]] = []
    started_at = time.perf_counter()
    limit = max(1, int(max_unread_chats))
    for index, session in enumerate(unread_sessions[:limit]):
        if opened and time.perf_counter() - started_at >= max_ui_busy_seconds:
            if report_progress is not None:
                report_progress(
                    "open_unread.stop_ui_budget",
                    {
                        "opened_count": len(opened),
                        "max_ui_busy_seconds": max_ui_busy_seconds,
                    },
                )
            break
```

After each `opened.append(...)`, report and call the callback with the exact appended payload:

```python
        opened_chat = {
            "chat_name": chat_name,
            "source": source,
            "status": "ok",
            "click_point": list(click_point),
            "message_region": _rect_to_dict(region),
            "uia": {
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "count": len(controls),
                "controls": controls,
            },
            "messages": messages,
        }
        opened.append(opened_chat)
        if report_progress is not None:
            report_progress("open_unread.chat", {"chat": opened_chat})
        if on_chat_opened is not None:
            on_chat_opened(opened_chat)
```

For the `no_click_point` branch, replace the direct append with:

```python
            opened_chat = {"chat_name": chat_name, "source": source, "status": "no_click_point", "messages": []}
            opened.append(opened_chat)
            if report_progress is not None:
                report_progress("open_unread.chat", {"chat": opened_chat})
            if on_chat_opened is not None:
                on_chat_opened(opened_chat)
            continue
```

- [ ] **Step 5: Run Task 4 tests**

Run:

```powershell
pytest tests/test_probes.py::test_open_unread_sessions_respects_max_unread_chats_and_reports_each_chat tests/test_probes.py::test_open_unread_sessions_stops_at_ui_busy_budget -q
```

Expected: PASS.

- [ ] **Step 6: Run existing probe tests**

Run:

```powershell
pytest tests/test_probes.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

Run:

```powershell
git add src/my_wxauto/probes.py tests/test_probes.py
git commit -m "Support bounded unread chat drains"
```

---

### Task 5: Batch Listener Entry Point

**Files:**
- Modify: `src/my_wxauto/listener.py`
- Create: `tests/test_bridge_listener.py`

- [ ] **Step 1: Write failing tests for conversation batch listener**

Create `tests/test_bridge_listener.py` with:

```python
from __future__ import annotations

from my_wxauto import listener
from my_wxauto.bridge_batcher import BatchingConfig
from my_wxauto.listener import listen_conversation_batches


def test_listen_conversation_batches_emits_one_batch_per_chat(monkeypatch, tmp_path) -> None:
    emitted = []

    def fake_icons() -> list[dict[str, object]]:
        return [{"image_sha1": "changed"}]

    class FakeDetector:
        def __init__(self, **_kwargs: object) -> None:
            self.calls = 0

        def observe(self, _now: float, _signature: object) -> dict[str, object] | None:
            self.calls += 1
            return {"change_count": 1} if self.calls == 1 else None

    def fake_probe(**kwargs: object) -> dict[str, object]:
        assert kwargs["open_unread_messages"] is True
        assert kwargs["max_unread_chats"] == 5
        on_chat_opened = kwargs["on_chat_opened"]
        on_chat_opened(
            {
                "chat_name": "alice",
                "source": "unread_session",
                "messages": [
                    {
                        "content": "hello",
                        "message_type": "text",
                        "sender": "alice",
                        "is_self": False,
                        "time_text": "15:41",
                    }
                ],
            }
        )
        on_chat_opened(
            {
                "chat_name": "bob",
                "source": "unread_session",
                "messages": [
                    {
                        "content": "hi",
                        "message_type": "text",
                        "sender": "bob",
                        "is_self": False,
                        "time_text": "15:42",
                    }
                ],
            }
        )
        return {"status": "ok", "opened_unread_chats": []}

    monkeypatch.setattr(listener.probes, "_ensure_windows", lambda: None)
    monkeypatch.setattr(listener.probes, "TaskbarFlashDetector", FakeDetector)
    monkeypatch.setattr(listener.probes, "inspect_wechat_taskbar_icons", fake_icons)
    monkeypatch.setattr(listener.probes, "_probe_sessions_after_wakeup_with_timeout", fake_probe)
    monkeypatch.setattr(listener.probes, "_taskbar_signature", lambda icons: tuple(item["image_sha1"] for item in icons))
    monkeypatch.setattr(listener.time, "sleep", lambda _seconds: None)

    stats = listen_conversation_batches(
        emitted.append,
        seconds=5,
        interval=0.01,
        min_changes=1,
        max_probes=1,
        max_chats_per_drain=5,
        store_path=tmp_path / "bridge.sqlite3",
        batching_config=BatchingConfig(quiet_window_seconds=0.0, max_batch_wait_seconds=8.0, max_batch_messages=10),
    )

    assert stats.event_count == 2
    assert [batch.chat_name for batch in emitted] == ["alice", "bob"]
    assert emitted[0].messages[0].content == "hello"
    assert emitted[1].messages[0].content == "hi"


def test_listen_conversation_batches_deduplicates_repeated_probe_messages(monkeypatch, tmp_path) -> None:
    emitted = []

    def fake_icons() -> list[dict[str, object]]:
        return [{"image_sha1": "changed"}]

    class FakeDetector:
        def __init__(self, **_kwargs: object) -> None:
            self.calls = 0

        def observe(self, _now: float, _signature: object) -> dict[str, object] | None:
            self.calls += 1
            return {"change_count": self.calls} if self.calls <= 2 else None

    def fake_probe(**kwargs: object) -> dict[str, object]:
        kwargs["on_chat_opened"](
            {
                "chat_name": "alice",
                "source": "unread_session",
                "messages": [
                    {
                        "content": "hello",
                        "message_type": "text",
                        "sender": "alice",
                        "is_self": False,
                        "time_text": "15:41",
                    }
                ],
            }
        )
        return {"status": "ok", "opened_unread_chats": []}

    monkeypatch.setattr(listener.probes, "_ensure_windows", lambda: None)
    monkeypatch.setattr(listener.probes, "TaskbarFlashDetector", FakeDetector)
    monkeypatch.setattr(listener.probes, "inspect_wechat_taskbar_icons", fake_icons)
    monkeypatch.setattr(listener.probes, "_probe_sessions_after_wakeup_with_timeout", fake_probe)
    monkeypatch.setattr(listener.probes, "_taskbar_signature", lambda icons: tuple(item["image_sha1"] for item in icons))
    monkeypatch.setattr(listener.time, "sleep", lambda _seconds: None)

    stats = listen_conversation_batches(
        emitted.append,
        seconds=5,
        interval=0.01,
        min_changes=1,
        max_probes=2,
        store_path=tmp_path / "bridge.sqlite3",
        batching_config=BatchingConfig(quiet_window_seconds=0.0, max_batch_wait_seconds=8.0, max_batch_messages=10),
    )

    assert stats.event_count == 1
    assert len(emitted) == 1
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_bridge_listener.py -q
```

Expected: FAIL with `ImportError` for `listen_conversation_batches`.

- [ ] **Step 3: Add imports and function signature to `listener.py`**

In `src/my_wxauto/listener.py`, add imports:

```python
from pathlib import Path

from .bridge_batcher import BatchingConfig, ConversationBatcher
from .bridge_events import ConversationBatch, messages_from_chat_payload
from .bridge_store import BridgeStore
```

Add this function after `listen_new_messages`:

```python
def listen_conversation_batches(
    callback: Callable[[ConversationBatch], None],
    *,
    seconds: float = 0.0,
    interval: float = 0.25,
    max_controls: int = 260,
    min_changes: int = 4,
    window_seconds: float = 3.0,
    cooldown_seconds: float = 5.0,
    action_timeout: float = 15.0,
    max_events: int = 0,
    max_probes: int = 0,
    max_chats_per_drain: int = 5,
    max_ui_busy_seconds: float = 15.0,
    store_path: str | Path = ".my_wxauto_bridge.sqlite3",
    batching_config: BatchingConfig | None = None,
) -> ListenerStats:
    probes._ensure_windows()
    store = BridgeStore(store_path)
    batcher = ConversationBatcher(store, config=batching_config)
    detector = probes.TaskbarFlashDetector(
        min_changes=min_changes,
        window_seconds=window_seconds,
        cooldown_seconds=cooldown_seconds,
    )
    started = time.perf_counter()
    deadline = None if seconds <= 0 else time.monotonic() + seconds
    flash_count = 0
    event_count = 0
    stopped_reason = "timeout" if deadline is not None else "stopped"

    def emit_due(now: float) -> bool:
        nonlocal event_count, stopped_reason
        for batch in batcher.freeze_due_batches(now=now):
            callback(batch)
            event_count += 1
            if max_events > 0 and event_count >= max_events:
                stopped_reason = "max_events"
                return True
        return False

    def on_chat_opened(chat: dict[str, Any]) -> None:
        now = time.monotonic()
        chat_name = str(chat.get("chat_name") or "")
        if not chat_name:
            return
        messages = messages_from_chat_payload(chat)
        if not messages:
            return
        batcher.add_messages(chat_name, messages, now=now)
        emit_due(now)

    while deadline is None or time.monotonic() < deadline:
        if emit_due(time.monotonic()):
            return _stats(started, flash_count, event_count, stopped_reason)
        icons = probes.inspect_wechat_taskbar_icons()
        flash = detector.observe(time.monotonic(), probes._taskbar_signature(icons))
        if flash is not None:
            flash_count += 1
            payload = probes._probe_sessions_after_wakeup_with_timeout(
                max_controls=max_controls,
                timeout=action_timeout,
                restore_icons=icons,
                open_unread_messages=True,
                max_unread_chats=max_chats_per_drain,
                max_ui_busy_seconds=max_ui_busy_seconds,
                on_chat_opened=on_chat_opened,
            )
            if str(payload.get("status") or "ok") != "ok":
                pass
            if emit_due(time.monotonic()):
                return _stats(started, flash_count, event_count, stopped_reason)
            if max_probes > 0 and flash_count >= max_probes:
                stopped_reason = "max_probes"
                break
        time.sleep(interval)

    emit_due(time.monotonic())
    return _stats(started, flash_count, event_count, stopped_reason)
```

- [ ] **Step 4: Update `_probe_sessions_after_wakeup_with_timeout` to forward new kwargs**

Find `_probe_sessions_after_wakeup_with_timeout` in `src/my_wxauto/probes.py`. Extend its signature with:

```python
    max_unread_chats: int = 1,
    max_ui_busy_seconds: float = 15.0,
    on_chat_opened: Callable[[dict[str, Any]], None] | None = None,
```

Do not pass `on_chat_opened` into the spawned worker process. A local closure is not picklable under the current `multiprocessing` `spawn` context. Instead, keep the callback in the parent and invoke it when a progress message with stage `open_unread.chat` arrives.

In the parent loop, replace the progress-message branch with:

```python
        if message.get("status") == "progress":
            last_progress = message
            public_progress = {key: value for key, value in message.items() if key != "status"}
            if on_progress is not None:
                on_progress(public_progress)
            if message.get("stage") == "open_unread.chat" and on_chat_opened is not None:
                chat = message.get("chat")
                if isinstance(chat, dict):
                    on_chat_opened(chat)
            continue
```

Pass only pickle-safe values into the worker target:

```python
    process = context.Process(
        target=_probe_sessions_after_wakeup_worker,
        args=(
            result_queue,
            max_controls,
            restore_icons,
            open_unread_messages,
            max_unread_chats,
            max_ui_busy_seconds,
        ),
    )
```

Change the worker signature to:

```python
def _probe_sessions_after_wakeup_worker(
    result_queue: mp.Queue[dict[str, Any]],
    max_controls: int,
    restore_icons: list[dict[str, Any]] | None,
    open_unread_messages: bool,
    max_unread_chats: int,
    max_ui_busy_seconds: float,
) -> None:
```

The final call inside the worker should include:

```python
result = _probe_sessions_after_wakeup(
    max_controls=max_controls,
    restore_icons=restore_icons,
    open_unread_messages=open_unread_messages,
    max_unread_chats=max_unread_chats,
    max_ui_busy_seconds=max_ui_busy_seconds,
    report_progress=report_progress,
)
```

- [ ] **Step 5: Run Task 5 tests**

Run:

```powershell
pytest tests/test_bridge_listener.py -q
```

Expected: PASS.

- [ ] **Step 6: Run listener and probe tests**

Run:

```powershell
pytest tests/test_listener.py tests/test_probes.py tests/test_bridge_listener.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
git add src/my_wxauto/listener.py src/my_wxauto/probes.py tests/test_bridge_listener.py
git commit -m "Add conversation batch listener"
```

---

### Task 6: Public WeChat Facade And Package Exports

**Files:**
- Modify: `src/my_wxauto/wechat.py`
- Modify: `src/my_wxauto/__init__.py`
- Modify: `tests/test_listener.py`

- [ ] **Step 1: Write failing tests for `WeChat.listen_conversation_batches` and exports**

Append to `tests/test_listener.py`:

```python

def test_wechat_listen_conversation_batches_delegates_to_listener(monkeypatch) -> None:
    from my_wxauto import listener

    calls = []
    wx = WeChat(prefer_wxauto4=False)

    def callback(event: object) -> None:
        calls.append({"callback_event": event})

    def fake_listen_conversation_batches(callback_arg, **kwargs: object) -> str:
        calls.append({"callback": callback_arg, **kwargs})
        return "stats"

    monkeypatch.setattr(listener, "listen_conversation_batches", fake_listen_conversation_batches)

    result = wx.listen_conversation_batches(callback, seconds=3, max_events=1)

    assert result == "stats"
    assert calls == [{"callback": callback, "seconds": 3, "max_events": 1}]


def test_bridge_public_exports() -> None:
    import my_wxauto

    assert hasattr(my_wxauto, "BridgeMessage")
    assert hasattr(my_wxauto, "ConversationBatch")
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_listener.py::test_wechat_listen_conversation_batches_delegates_to_listener tests/test_listener.py::test_bridge_public_exports -q
```

Expected: FAIL because `WeChat` has no `listen_conversation_batches` and exports are missing.

- [ ] **Step 3: Add WeChat delegation**

In `src/my_wxauto/wechat.py`, add this method after `listen_new_messages`:

```python
    def listen_conversation_batches(self, callback, **kwargs: object):
        from . import listener

        return listener.listen_conversation_batches(callback, **kwargs)
```

- [ ] **Step 4: Export bridge dataclasses**

In `src/my_wxauto/__init__.py`, change the imports to include:

```python
from .bridge_events import BridgeMessage, ConversationBatch
```

Then update `__all__` to:

```python
__all__ = [
    "WeChat",
    "WxResponse",
    "ChatMessage",
    "ListenerStats",
    "NewMessageEvent",
    "BridgeMessage",
    "ConversationBatch",
]
```

- [ ] **Step 5: Run Task 6 tests**

Run:

```powershell
pytest tests/test_listener.py::test_wechat_listen_conversation_batches_delegates_to_listener tests/test_listener.py::test_bridge_public_exports -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git add src/my_wxauto/wechat.py src/my_wxauto/__init__.py tests/test_listener.py
git commit -m "Expose conversation batch listener"
```

---

### Task 7: End-To-End Verification And README Note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a short reliability-core README section**

Append this section to `README.md`:

````markdown
## Conversation batch listener

`my-wxauto` also exposes a reliability-oriented listener for robot integrations.
It reads unread WeChat conversations in bounded drain cycles, deduplicates
messages, batches messages per conversation, and emits one conversation batch
at a time.

```python
from my_wxauto import WeChat

wx = WeChat()

def on_batch(batch):
    print(batch.to_event_dict())

wx.listen_conversation_batches(
    on_batch,
    max_chats_per_drain=5,
)
```

The listener does not send multiple unrelated conversations as one model
request. Each emitted batch belongs to one WeChat conversation.
````

- [ ] **Step 2: Run all tests**

Run:

```powershell
pytest -q
```

Expected: PASS. The current suite should report all tests passing.

- [ ] **Step 3: Run import smoke test**

Run:

```powershell
@'
from my_wxauto import WeChat, BridgeMessage, ConversationBatch
print(WeChat.__name__, BridgeMessage.__name__, ConversationBatch.__name__)
'@ | python -
```

Expected output:

```text
WeChat BridgeMessage ConversationBatch
```

- [ ] **Step 4: Check git diff**

Run:

```powershell
git status --short
git diff --check
```

Expected:

```text
M README.md
```

and `git diff --check` exits with code 0.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add README.md
git commit -m "Document conversation batch listener"
```

---

## Spec Coverage Check

- Duplicate message prevention: Task 1 defines message keys; Task 2 persists seen keys; Task 3 applies dedup.
- Missing messages during model thinking: Task 5 emits batches independently from downstream processing and does not wait for model replies.
- `max_chats_per_drain = 5`: Task 4 adds bounded unread drains; Task 5 wires the listener default.
- Per-conversation events: Task 1 defines one conversation batch event; Task 5 emits each opened chat independently.
- Same rules for private/group chats: Task 3 batching has no chat-type branching.
- Frozen batch is stable: Task 3 freezes batches and removes them from open state.
- Outgoing echo prevention: Task 2 stores echoes; Task 3 suppresses matching messages.
- UI serialization: Task 4 and Task 5 keep UI reads in the existing single probe/listener path and do not introduce concurrent UI access.
- Hermes/OpenClaw integration: intentionally outside this plan, matching the approved spec.

## Execution Notes

- Do not modify Hermes or OpenClaw in this plan.
- Do not add a local HTTP server in this plan.
- Do not add full session-list scrolling in this plan.
- Keep commits task-sized.
- Run the specified tests after each task before committing.
