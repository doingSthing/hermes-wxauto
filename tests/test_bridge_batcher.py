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
