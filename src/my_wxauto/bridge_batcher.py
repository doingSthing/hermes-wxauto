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
