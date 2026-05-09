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
