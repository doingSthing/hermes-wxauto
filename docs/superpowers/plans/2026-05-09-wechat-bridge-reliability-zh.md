# 微信桥接可靠性实现计划

> **面向代理式执行者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐步实现本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 为 `my-wxauto` 构建可靠的本地消息采集核心：消息去重、按会话分批、每次 drain 最多处理五个未读会话，并暴露一个会话批次监听入口。

**架构：** 新增聚焦的桥接模块，用于规范化事件、基于 SQLite 的状态持久化，以及按会话分批。扩展现有的 `probes` drain 路径，使其可以打开多个未读会话，并在每个会话读取完成后立即上报。所有微信 UI 访问仍保留在现有 probe/listener 路径中，模型或框架集成不纳入本计划。

**技术栈：** Python 3.9+，标准库 `dataclasses`、`hashlib`、`json`、`sqlite3`、`time`，现有 `pytest` 测试，以及 `probes` 背后的现有 `pywinauto` / Win32 代码。

---

## 文件结构

- 创建 `src/my_wxauto/bridge_events.py`
  - 负责规范化桥接消息和会话批次的数据类。
  - 负责基于 `ChatMessage` 数据生成软消息键。
  - 不包含 SQLite、UI 自动化或线程逻辑。

- 创建 `src/my_wxauto/bridge_store.py`
  - 负责 `seen_messages`、`conversation_batches` 和 `outgoing_echoes` 的 SQLite schema 与持久化。
  - 不包含 UI 自动化，也不包含分批计时逻辑。

- 创建 `src/my_wxauto/bridge_batcher.py`
  - 负责每个会话的打开批次和冻结规则。
  - 使用 `BridgeStore` 做去重和回声抑制。
  - 不包含微信 UI 自动化。

- 修改 `src/my_wxauto/probes.py`
  - 为未读 drain 收集流程增加 `max_unread_chats`、`max_ui_busy_seconds` 和 `on_chat_opened` 参数传递。
  - 将硬编码的 `unread_sessions[:1]` 替换为有上限的迭代。

- 修改 `src/my_wxauto/listener.py`
  - 增加 `listen_conversation_batches`。
  - 保持 `listen_new_messages` 的行为兼容。
  - 通过 `ConversationBatcher` 将已打开的未读聊天负载转换为桥接批次。

- 修改 `src/my_wxauto/wechat.py`
  - 增加 `WeChat.listen_conversation_batches` 转发。

- 修改 `src/my_wxauto/__init__.py`
  - 导出属于公开能力一部分的桥接数据类。

- 测试：
  - 创建 `tests/test_bridge_events.py`
  - 创建 `tests/test_bridge_store.py`
  - 创建 `tests/test_bridge_batcher.py`
  - 创建 `tests/test_bridge_listener.py`
  - 修改 `tests/test_probes.py`
  - 修改 `tests/test_listener.py`

---

### 任务 1：规范化桥接事件与软消息键

**文件：**
- 创建：`src/my_wxauto/bridge_events.py`
- 创建：`tests/test_bridge_events.py`

- [ ] **步骤 1：先写失败测试，覆盖稳定消息键与批次序列化**

创建 `tests/test_bridge_events.py`，内容如下：

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

- [ ] **步骤 2：运行新测试并确认它们失败**

运行：

```powershell
pytest tests/test_bridge_events.py -q
```

预期：由于 `my_wxauto.bridge_events` 不存在，出现 `ModuleNotFoundError`。

- [ ] **步骤 3：实现 `bridge_events.py`**

创建 `src/my_wxauto/bridge_events.py`：

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

- [ ] **步骤 4：运行任务 1 的测试**

运行：

```powershell
pytest tests/test_bridge_events.py -q
```

预期：通过。

- [ ] **步骤 5：提交任务 1**

运行：

```powershell
git add src/my_wxauto/bridge_events.py tests/test_bridge_events.py
git commit -m "Add bridge event models"
```

---

### 任务 2：SQLite 桥接存储

**文件：**
- 创建：`src/my_wxauto/bridge_store.py`
- 创建：`tests/test_bridge_store.py`

- [ ] **步骤 1：先写失败测试，覆盖已见消息、批次和发送回声**

创建 `tests/test_bridge_store.py`，内容如下：

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

- [ ] **步骤 2：运行新测试并确认它们失败**

运行：

```powershell
pytest tests/test_bridge_store.py -q
```

预期：由于 `my_wxauto.bridge_store` 不存在，出现 `ModuleNotFoundError`。

- [ ] **步骤 3：实现 `bridge_store.py`**

创建 `src/my_wxauto/bridge_store.py`：

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

- [ ] **步骤 4：运行任务 2 的测试**

运行：

```powershell
pytest tests/test_bridge_store.py -q
```

预期：通过。

- [ ] **步骤 5：提交任务 2**

运行：

```powershell
git add src/my_wxauto/bridge_store.py tests/test_bridge_store.py
git commit -m "Add bridge SQLite store"
```

---

### 任务 3：按会话分批器

**文件：**
- 创建：`src/my_wxauto/bridge_batcher.py`
- 创建：`tests/test_bridge_batcher.py`

- [ ] **步骤 1：先写失败测试，覆盖去重、冻结规则和回声抑制**

创建 `tests/test_bridge_batcher.py`，内容如下：

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

- [ ] **步骤 2：运行新测试并确认它们失败**

运行：

```powershell
pytest tests/test_bridge_batcher.py -q
```

预期：由于 `my_wxauto.bridge_batcher` 不存在，出现 `ModuleNotFoundError`。

- [ ] **步骤 3：实现 `bridge_batcher.py`**

创建 `src/my_wxauto/bridge_batcher.py`：

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

- [ ] **步骤 4：运行任务 3 的测试**

运行：

```powershell
pytest tests/test_bridge_batcher.py -q
```

预期：通过。

- [ ] **步骤 5：提交任务 3**

运行：

```powershell
git add src/my_wxauto/bridge_batcher.py tests/test_bridge_batcher.py
git commit -m "Add conversation batcher"
```

---

### 任务 4：在 Probes 中支持多会话 Drain

**文件：**
- 修改：`src/my_wxauto/probes.py`
- 修改：`tests/test_probes.py`

- [ ] **步骤 1：先写失败测试，覆盖 `max_unread_chats` 和按会话即时回调**

将以下测试追加到 `tests/test_probes.py`：

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

- [ ] **步骤 2：运行新测试并确认它们失败**

运行：

```powershell
pytest tests/test_probes.py::test_open_unread_sessions_respects_max_unread_chats_and_reports_each_chat tests/test_probes.py::test_open_unread_sessions_stops_at_ui_busy_budget -q
```

预期：由于传入了未预期的关键字参数，报 `TypeError`。

- [ ] **步骤 3：更新 `_probe_sessions_after_wakeup` 的签名和调用点**

在 `src/my_wxauto/probes.py` 中，将 `_probe_sessions_after_wakeup` 的签名从：

```python
def _probe_sessions_after_wakeup(
    *,
    max_controls: int,
    restore_icons: list[dict[str, Any]] | None = None,
    open_unread_messages: bool = False,
    report_progress: Callable[[str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
```

改为：

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

然后把对 `_open_unread_sessions_and_collect_messages` 的调用改成：

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

- [ ] **步骤 4：更新 `_open_unread_sessions_and_collect_messages`**

将函数签名改为：

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

将：

```python
    opened: list[dict[str, Any]] = []
    for index, session in enumerate(unread_sessions[:1]):
```

替换为：

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

每次 `opened.append(...)` 之后，使用实际追加的负载进行上报并调用回调：

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

对于 `no_click_point` 分支，把直接 append 替换为：

```python
            opened_chat = {"chat_name": chat_name, "source": source, "status": "no_click_point", "messages": []}
            opened.append(opened_chat)
            if report_progress is not None:
                report_progress("open_unread.chat", {"chat": opened_chat})
            if on_chat_opened is not None:
                on_chat_opened(opened_chat)
            continue
```

- [ ] **步骤 5：运行任务 4 的测试**

运行：

```powershell
pytest tests/test_probes.py::test_open_unread_sessions_respects_max_unread_chats_and_reports_each_chat tests/test_probes.py::test_open_unread_sessions_stops_at_ui_busy_budget -q
```

预期：通过。

- [ ] **步骤 6：运行现有 probe 测试**

运行：

```powershell
pytest tests/test_probes.py -q
```

预期：通过。

- [ ] **步骤 7：提交任务 4**

运行：

```powershell
git add src/my_wxauto/probes.py tests/test_probes.py
git commit -m "Support bounded unread chat drains"
```

---

### 任务 5：批次监听入口

**文件：**
- 修改：`src/my_wxauto/listener.py`
- 创建：`tests/test_bridge_listener.py`

- [ ] **步骤 1：先写失败测试，覆盖会话批次监听**

创建 `tests/test_bridge_listener.py`，内容如下：

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

- [ ] **步骤 2：运行新测试并确认它们失败**

运行：

```powershell
pytest tests/test_bridge_listener.py -q
```

预期：因为无法导入 `listen_conversation_batches` 而失败。

- [ ] **步骤 3：在 `listener.py` 中增加导入和函数签名**

在 `src/my_wxauto/listener.py` 中加入导入：

```python
from pathlib import Path

from .bridge_batcher import BatchingConfig, ConversationBatcher
from .bridge_events import ConversationBatch, messages_from_chat_payload
from .bridge_store import BridgeStore
```

在 `listen_new_messages` 之后加入这个函数：

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

- [ ] **步骤 4：更新 `_probe_sessions_after_wakeup_with_timeout` 以转发新参数**

在 `src/my_wxauto/probes.py` 中找到 `_probe_sessions_after_wakeup_with_timeout`。将它的签名扩展为：

```python
    max_unread_chats: int = 1,
    max_ui_busy_seconds: float = 15.0,
    on_chat_opened: Callable[[dict[str, Any]], None] | None = None,
```

不要把 `on_chat_opened` 传进子进程 worker。当前 `multiprocessing` 使用的是 `spawn` 上下文，本地闭包无法被 pickle。应当在父进程中保留该回调，并在接收到阶段为 `open_unread.chat` 的进度消息时调用它。

在父进程循环中，将处理进度消息的分支替换为：

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

只向 worker 目标传递可被 pickle 的值：

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

将 worker 的签名改为：

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

worker 内部最终调用需要包含：

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

- [ ] **步骤 5：运行任务 5 的测试**

运行：

```powershell
pytest tests/test_bridge_listener.py -q
```

预期：通过。

- [ ] **步骤 6：运行 listener 和 probe 测试**

运行：

```powershell
pytest tests/test_listener.py tests/test_probes.py tests/test_bridge_listener.py -q
```

预期：通过。

- [ ] **步骤 7：提交任务 5**

运行：

```powershell
git add src/my_wxauto/listener.py src/my_wxauto/probes.py tests/test_bridge_listener.py
git commit -m "Add conversation batch listener"
```

---

### 任务 6：公开 WeChat 门面与包导出

**文件：**
- 修改：`src/my_wxauto/wechat.py`
- 修改：`src/my_wxauto/__init__.py`
- 修改：`tests/test_listener.py`

- [ ] **步骤 1：先写失败测试，覆盖 `WeChat.listen_conversation_batches` 与导出**

将以下内容追加到 `tests/test_listener.py`：

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

- [ ] **步骤 2：运行新测试并确认它们失败**

运行：

```powershell
pytest tests/test_listener.py::test_wechat_listen_conversation_batches_delegates_to_listener tests/test_listener.py::test_bridge_public_exports -q
```

预期：失败，因为 `WeChat` 还没有 `listen_conversation_batches`，且导出项缺失。

- [ ] **步骤 3：增加 WeChat 转发方法**

在 `src/my_wxauto/wechat.py` 中，在 `listen_new_messages` 后加入这个方法：

```python
    def listen_conversation_batches(self, callback, **kwargs: object):
        from . import listener

        return listener.listen_conversation_batches(callback, **kwargs)
```

- [ ] **步骤 4：导出桥接数据类**

在 `src/my_wxauto/__init__.py` 中，将导入改为包含：

```python
from .bridge_events import BridgeMessage, ConversationBatch
```

然后把 `__all__` 更新为：

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

- [ ] **步骤 5：运行任务 6 的测试**

运行：

```powershell
pytest tests/test_listener.py::test_wechat_listen_conversation_batches_delegates_to_listener tests/test_listener.py::test_bridge_public_exports -q
```

预期：通过。

- [ ] **步骤 6：提交任务 6**

运行：

```powershell
git add src/my_wxauto/wechat.py src/my_wxauto/__init__.py tests/test_listener.py
git commit -m "Expose conversation batch listener"
```

---

### 任务 7：端到端验证与 README 说明

**文件：**
- 修改：`README.md`

- [ ] **步骤 1：在 README 中添加一个简短的可靠性核心说明章节**

将以下章节追加到 `README.md`：

````markdown
## Conversation batch listener

`my-wxauto` 还暴露了一个面向机器人集成、以可靠性为导向的监听器。
它会在有上限的 drain 周期中读取未读微信会话，对消息去重，
按会话对消息分批，并且每次只发出一个会话批次。

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

该监听器不会把多个互不相关的会话合并成一次模型请求。
每个发出的批次都只属于一个微信会话。
````

- [ ] **步骤 2：运行全部测试**

运行：

```powershell
pytest -q
```

预期：全部通过，当前测试套件应当全部成功。

- [ ] **步骤 3：运行导入冒烟测试**

运行：

```powershell
@'
from my_wxauto import WeChat, BridgeMessage, ConversationBatch
print(WeChat.__name__, BridgeMessage.__name__, ConversationBatch.__name__)
'@ | python -
```

预期输出：

```text
WeChat BridgeMessage ConversationBatch
```

- [ ] **步骤 4：检查 git diff**

运行：

```powershell
git status --short
git diff --check
```

预期：

```text
M README.md
```

并且 `git diff --check` 退出码为 0。

- [ ] **步骤 5：提交任务 7**

运行：

```powershell
git add README.md
git commit -m "Document conversation batch listener"
```

---

## 规格覆盖检查

- 防止重复消息：任务 1 定义消息键；任务 2 持久化已见键；任务 3 应用去重。
- 避免模型思考期间漏消息：任务 5 独立发出批次，不等待模型回复。
- `max_chats_per_drain = 5`：任务 4 增加有上限的未读 drain；任务 5 连接默认监听值。
- 按会话发事件：任务 1 定义单会话批次事件；任务 5 独立发出每个已打开聊天。
- 私聊/群聊使用相同规则：任务 3 的分批没有聊天类型分支。
- 冻结后的批次保持稳定：任务 3 冻结批次并从打开状态中移除。
- 防止发送回声触发：任务 2 存储回声；任务 3 抑制匹配消息。
- UI 串行化：任务 4 和任务 5 让 UI 读取继续停留在现有单一 probe/listener 路径中，不引入并发 UI 访问。
- Hermes/OpenClaw 集成：明确不在本计划范围内，和已批准规格一致。

## 执行说明

- 本计划中不要修改 Hermes 或 OpenClaw。
- 本计划中不要加入本地 HTTP 服务器。
- 本计划中不要加入完整的会话列表滚动查找。
- 保持每次提交粒度与任务一致。
- 每个任务完成后按要求先跑测试再提交。
