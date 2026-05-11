# Batch Listener Sender Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional sender and self-message enrichment to `listen_conversation_batches` without changing the default fast listener behavior.

**Architecture:** Reuse the existing profile-card sender resolver and self-message pixel inference from `listener.py`. Add a small internal enrichment helper that converts probe chat payload messages into `ChatMessage`, enriches them only when requested, converts them back to dict payloads, then lets the existing `messages_from_chat_payload` and `ConversationBatcher` continue unchanged.

**Tech Stack:** Python 3.9+, existing `pytest` tests, existing `listener.py` sender-resolution helpers, existing `BridgeMessage`/`ConversationBatch` models.

---

## File Structure

- Modify `src/my_wxauto/listener.py`
  - Add optional sender-resolution parameters to `listen_conversation_batches`.
  - Add `_resolve_probe_chat_senders` and `_window_rect_from_dict` helpers.
  - Update `_resolve_visible_message_senders` so `is_self=True` messages are skipped before profile-card resolving.

- Modify `src/my_wxauto/wechat.py`
  - No implementation change should be needed because `WeChat.listen_conversation_batches` already forwards `**kwargs`.

- Modify `README.md`
  - Add a short optional sender-resolution snippet under the conversation batch listener section.

- Modify `tests/test_bridge_listener.py`
  - Add integration tests for default fast mode and enabled sender-resolution mode.
  - Add helper-level tests for resolving sender payloads before batching.

- Modify `tests/test_listener.py`
  - Add focused tests for `_resolve_visible_message_senders` skipping `is_self=True`.
  - Add facade delegation coverage for sender-resolution kwargs if not already covered by an existing generic forwarding test.

---

### Task 1: Add Probe Chat Sender Enrichment Helper

**Files:**
- Modify: `src/my_wxauto/listener.py`
- Modify: `tests/test_bridge_listener.py`
- Modify: `tests/test_listener.py`

- [ ] **Step 1: Write failing helper tests**

Append these tests to `tests/test_bridge_listener.py`:

```python
def test_resolve_probe_chat_senders_returns_original_payload_when_disabled(monkeypatch) -> None:
    chat = {
        "chat_name": "group",
        "message_region": {"left": 100, "top": 200, "right": 900, "bottom": 700},
        "messages": [
            {
                "content": "hello",
                "message_type": "text",
                "sender": None,
                "rect": {"left": 320, "top": 260, "right": 620, "bottom": 310},
            }
        ],
    }

    def fail_resolver(*_args: object, **_kwargs: object) -> str | None:
        raise AssertionError("sender resolver should not run in default mode")

    monkeypatch.setattr(listener, "_resolve_sender_from_profile_card", fail_resolver)

    assert listener._resolve_probe_chat_senders(chat, resolve_senders=False) is chat
```

Append this test to `tests/test_bridge_listener.py`:

```python
def test_resolve_probe_chat_senders_enriches_sender_before_batching(monkeypatch) -> None:
    chat = {
        "chat_name": "group",
        "message_region": {"left": 100, "top": 200, "right": 900, "bottom": 700},
        "messages": [
            {
                "content": "hello",
                "message_type": "text",
                "sender": None,
                "raw_name": "hello",
                "class_name": "mmui::ChatTextItemView",
                "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                "rect": {"left": 320, "top": 260, "right": 620, "bottom": 310},
            }
        ],
    }
    resolver_calls: list[str] = []
    progress_events: list[dict[str, object]] = []

    def fake_resolver(message: listener.ChatMessage, **_kwargs: object) -> str | None:
        resolver_calls.append(message.content)
        return "Alice"

    monkeypatch.setattr(listener, "_resolve_sender_from_profile_card", fake_resolver)
    monkeypatch.setattr(
        listener,
        "_annotate_messages_with_self_flags",
        lambda messages, _region: [{**messages[0], "visible_rect": messages[0]["rect"], "is_self": False}],
    )

    enriched = listener._resolve_probe_chat_senders(
        chat,
        resolve_senders="profile_card",
        sender_resolve_limit=5,
        sender_resolve_timeout=20.0,
        profile_card_timeout=2.0,
        sender_progress=progress_events.append,
    )

    assert enriched is not chat
    assert resolver_calls == ["hello"]
    assert enriched["messages"][0]["sender"] == "Alice"
    assert enriched["messages"][0]["is_self"] is False
    assert enriched["messages"][0]["visible_rect"] == {"left": 320, "top": 260, "right": 620, "bottom": 310}
    assert [event["stage"] for event in progress_events] == ["start", "resolved"]
```

Append this test to `tests/test_listener.py`:

```python
def test_resolve_visible_message_senders_skips_self_messages() -> None:
    messages = (
        ChatMessage(
            content="mine",
            message_type="text",
            is_self=True,
            visible_rect={"left": 300, "top": 100, "right": 650, "bottom": 160},
        ),
        ChatMessage(
            content="theirs",
            message_type="text",
            is_self=False,
            visible_rect={"left": 300, "top": 180, "right": 650, "bottom": 240},
        ),
    )
    resolver_calls: list[str] = []
    progress_events: list[dict[str, object]] = []

    def fake_resolver(message: ChatMessage) -> str | None:
        resolver_calls.append(message.content)
        return f"{message.content}-sender"

    resolved = listener._resolve_visible_message_senders(
        messages,
        fake_resolver,
        limit=0,
        timeout=None,
        progress=progress_events.append,
        candidate_filter=lambda _message: True,
    )

    assert resolver_calls == ["theirs"]
    assert resolved[0].sender is None
    assert resolved[0].is_self is True
    assert resolved[1].sender == "theirs-sender"
    assert [event["stage"] for event in progress_events] == ["skipped_self", "start", "resolved"]
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
pytest tests/test_bridge_listener.py::test_resolve_probe_chat_senders_returns_original_payload_when_disabled tests/test_bridge_listener.py::test_resolve_probe_chat_senders_enriches_sender_before_batching tests/test_listener.py::test_resolve_visible_message_senders_skips_self_messages -q
```

Expected:

- The first two tests fail because `_resolve_probe_chat_senders` does not exist.
- The third test fails because `_resolve_visible_message_senders` does not yet skip `is_self=True` with `skipped_self`.

- [ ] **Step 3: Implement helper functions**

In `src/my_wxauto/listener.py`, update the import:

```python
from .window import WeChatWindowController, WindowRect
```

Add these helpers before `get_latest_message`:

```python
def _resolve_probe_chat_senders(
    chat: dict[str, Any],
    *,
    resolve_senders: bool | str = False,
    sender_resolve_limit: int = 5,
    sender_resolve_timeout: float | None = 20.0,
    profile_card_timeout: float = 2.0,
    sender_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    if not _sender_resolution_enabled(resolve_senders):
        return chat

    region = _window_rect_from_dict(chat.get("message_region"))
    raw_messages = [
        message
        for message in (chat.get("messages") or [])
        if isinstance(message, dict)
    ]
    if not raw_messages:
        return chat

    if region is not None:
        raw_messages = [_message_with_visible_rect(message, region) for message in raw_messages]
        raw_messages = _annotate_messages_with_self_flags(raw_messages, region)

    messages = tuple(ChatMessage.from_probe(message) for message in raw_messages)
    if not messages:
        return chat

    resolved = _resolve_visible_message_senders(
        messages,
        lambda message: _resolve_sender_from_profile_card(
            message,
            timeout=profile_card_timeout,
            progress=sender_progress,
        ),
        limit=sender_resolve_limit,
        timeout=sender_resolve_timeout,
        progress=sender_progress,
        candidate_filter=_message_has_avatar_candidates,
    )
    return {**chat, "messages": [message.to_dict() for message in resolved]}


def _sender_resolution_enabled(resolve_senders: bool | str) -> bool:
    return resolve_senders is True or resolve_senders == "profile_card"


def _window_rect_from_dict(value: object) -> WindowRect | None:
    if not isinstance(value, dict):
        return None
    try:
        return WindowRect(
            left=int(value["left"]),
            top=int(value["top"]),
            right=int(value["right"]),
            bottom=int(value["bottom"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
```

In `_resolve_visible_message_senders`, add this block immediately after the existing `if message.sender:` block:

```python
        if message.is_self is True:
            _sender_progress(progress, "skipped_self", message, index=index, total=total, attempts=attempts)
            resolved.append(message)
            continue
```

- [ ] **Step 4: Run Task 1 focused tests**

Run:

```powershell
pytest tests/test_bridge_listener.py::test_resolve_probe_chat_senders_returns_original_payload_when_disabled tests/test_bridge_listener.py::test_resolve_probe_chat_senders_enriches_sender_before_batching tests/test_listener.py::test_resolve_visible_message_senders_skips_self_messages -q
```

Expected: PASS.

- [ ] **Step 5: Run related sender tests**

Run:

```powershell
pytest tests/test_listener.py::test_get_visible_messages_can_resolve_senders_with_profile_card_strategy tests/test_listener.py::test_get_visible_messages_limits_profile_card_sender_resolution tests/test_listener.py::test_get_visible_messages_skips_profile_card_resolution_when_avatar_is_not_visible tests/test_listener.py::test_get_visible_messages_skips_default_profile_card_resolution_for_non_text -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add src/my_wxauto/listener.py tests/test_bridge_listener.py tests/test_listener.py
git commit -m "Add batch listener sender enrichment helper"
```

---

### Task 2: Wire Optional Sender Resolution Into Batch Listener

**Files:**
- Modify: `src/my_wxauto/listener.py`
- Modify: `tests/test_bridge_listener.py`

- [ ] **Step 1: Write failing integration tests**

Append this test to `tests/test_bridge_listener.py`:

```python
def test_listen_conversation_batches_default_mode_does_not_resolve_senders(monkeypatch, tmp_path) -> None:
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
        kwargs["on_chat_opened"](
            {
                "chat_name": "group",
                "source": "unread_session",
                "message_region": {"left": 100, "top": 200, "right": 900, "bottom": 700},
                "messages": [
                    {
                        "content": "hello",
                        "message_type": "text",
                        "sender": None,
                        "is_self": None,
                        "time_text": "15:41",
                        "rect": {"left": 320, "top": 260, "right": 620, "bottom": 310},
                    }
                ],
            }
        )
        return {"status": "ok", "opened_unread_chats": []}

    def fail_resolve(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("default listener mode must not resolve senders")

    monkeypatch.setattr(listener.probes, "_ensure_windows", lambda: None)
    monkeypatch.setattr(listener.probes, "TaskbarFlashDetector", FakeDetector)
    monkeypatch.setattr(listener.probes, "inspect_wechat_taskbar_icons", fake_icons)
    monkeypatch.setattr(listener.probes, "_probe_sessions_after_wakeup_with_timeout", fake_probe)
    monkeypatch.setattr(listener.probes, "_taskbar_signature", lambda icons: tuple(item["image_sha1"] for item in icons))
    monkeypatch.setattr(listener, "_resolve_probe_chat_senders", fail_resolve)
    monkeypatch.setattr(listener.time, "sleep", lambda _seconds: None)

    stats = listen_conversation_batches(
        emitted.append,
        seconds=5,
        interval=0.01,
        min_changes=1,
        max_probes=1,
        store_path=tmp_path / "bridge.sqlite3",
        batching_config=BatchingConfig(quiet_window_seconds=0.0, max_batch_wait_seconds=8.0, max_batch_messages=10),
    )

    assert stats.event_count == 1
    assert emitted[0].messages[0].sender is None
    assert emitted[0].messages[0].is_self is None
```

Append this test to `tests/test_bridge_listener.py`:

```python
def test_listen_conversation_batches_resolves_senders_when_enabled(monkeypatch, tmp_path) -> None:
    emitted = []
    progress_events: list[dict[str, object]] = []

    def fake_icons() -> list[dict[str, object]]:
        return [{"image_sha1": "changed"}]

    class FakeDetector:
        def __init__(self, **_kwargs: object) -> None:
            self.calls = 0

        def observe(self, _now: float, _signature: object) -> dict[str, object] | None:
            self.calls += 1
            return {"change_count": 1} if self.calls == 1 else None

    def fake_probe(**kwargs: object) -> dict[str, object]:
        kwargs["on_chat_opened"](
            {
                "chat_name": "group",
                "source": "unread_session",
                "message_region": {"left": 100, "top": 200, "right": 900, "bottom": 700},
                "messages": [
                    {
                        "content": "hello",
                        "message_type": "text",
                        "sender": None,
                        "is_self": None,
                        "time_text": "15:41",
                        "rect": {"left": 320, "top": 260, "right": 620, "bottom": 310},
                    }
                ],
            }
        )
        return {"status": "ok", "opened_unread_chats": []}

    def fake_resolve(chat: dict[str, object], **kwargs: object) -> dict[str, object]:
        assert kwargs["resolve_senders"] == "profile_card"
        assert kwargs["sender_resolve_limit"] == 2
        assert kwargs["sender_resolve_timeout"] == 7.0
        assert kwargs["profile_card_timeout"] == 1.0
        assert kwargs["sender_progress"] is progress_events.append
        message = dict(chat["messages"][0])
        message["sender"] = "Alice"
        message["is_self"] = False
        return {**chat, "messages": [message]}

    monkeypatch.setattr(listener.probes, "_ensure_windows", lambda: None)
    monkeypatch.setattr(listener.probes, "TaskbarFlashDetector", FakeDetector)
    monkeypatch.setattr(listener.probes, "inspect_wechat_taskbar_icons", fake_icons)
    monkeypatch.setattr(listener.probes, "_probe_sessions_after_wakeup_with_timeout", fake_probe)
    monkeypatch.setattr(listener.probes, "_taskbar_signature", lambda icons: tuple(item["image_sha1"] for item in icons))
    monkeypatch.setattr(listener, "_resolve_probe_chat_senders", fake_resolve)
    monkeypatch.setattr(listener.time, "sleep", lambda _seconds: None)

    stats = listen_conversation_batches(
        emitted.append,
        seconds=5,
        interval=0.01,
        min_changes=1,
        max_probes=1,
        resolve_senders="profile_card",
        sender_resolve_limit=2,
        sender_resolve_timeout=7.0,
        profile_card_timeout=1.0,
        sender_progress=progress_events.append,
        store_path=tmp_path / "bridge.sqlite3",
        batching_config=BatchingConfig(quiet_window_seconds=0.0, max_batch_wait_seconds=8.0, max_batch_messages=10),
    )

    assert stats.event_count == 1
    assert emitted[0].messages[0].sender == "Alice"
    assert emitted[0].messages[0].is_self is False
```

- [ ] **Step 2: Run the new integration tests and verify they fail**

Run:

```powershell
pytest tests/test_bridge_listener.py::test_listen_conversation_batches_default_mode_does_not_resolve_senders tests/test_bridge_listener.py::test_listen_conversation_batches_resolves_senders_when_enabled -q
```

Expected:

- The enabled-mode test fails because `listen_conversation_batches` does not accept sender-resolution kwargs.

- [ ] **Step 3: Add listener parameters and wire the helper**

In `src/my_wxauto/listener.py`, extend `listen_conversation_batches` with these keyword-only parameters after `batching_config`:

```python
    resolve_senders: bool | str = False,
    sender_resolve_limit: int = 5,
    sender_resolve_timeout: float | None = 20.0,
    profile_card_timeout: float = 2.0,
    sender_progress: Callable[[dict[str, Any]], None] | None = None,
```

Update the docstring with this paragraph:

```python
    Sender resolution is disabled by default. Pass resolve_senders="profile_card"
    to click visible message avatars and read profile-card names before batching.
    This is slower and may briefly disturb the WeChat UI, so keep it opt-in.
```

In the nested `on_chat_opened`, replace:

```python
        messages = messages_from_chat_payload(chat)
```

with:

```python
        if _sender_resolution_enabled(resolve_senders):
            chat = _resolve_probe_chat_senders(
                chat,
                resolve_senders=resolve_senders,
                sender_resolve_limit=sender_resolve_limit,
                sender_resolve_timeout=sender_resolve_timeout,
                profile_card_timeout=profile_card_timeout,
                sender_progress=sender_progress,
            )
        messages = messages_from_chat_payload(chat)
```

- [ ] **Step 4: Run Task 2 tests**

Run:

```powershell
pytest tests/test_bridge_listener.py::test_listen_conversation_batches_default_mode_does_not_resolve_senders tests/test_bridge_listener.py::test_listen_conversation_batches_resolves_senders_when_enabled -q
```

Expected: PASS.

- [ ] **Step 5: Run full bridge listener tests**

Run:

```powershell
pytest tests/test_bridge_listener.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add src/my_wxauto/listener.py tests/test_bridge_listener.py
git commit -m "Wire optional sender resolution into batch listener"
```

---

### Task 3: Facade Coverage, README, And Verification

**Files:**
- Modify: `README.md`
- Modify: `tests/test_listener.py`

- [ ] **Step 1: Add facade delegation coverage for sender kwargs**

Update `tests/test_listener.py::test_wechat_listen_conversation_batches_delegates_to_listener` so the call includes sender-resolution kwargs:

```python
    result = wx.listen_conversation_batches(
        callback,
        seconds=3,
        max_events=1,
        resolve_senders="profile_card",
        sender_resolve_limit=2,
    )

    assert result == "stats"
    assert calls == [
        {
            "callback": callback,
            "seconds": 3,
            "max_events": 1,
            "resolve_senders": "profile_card",
            "sender_resolve_limit": 2,
        }
    ]
```

- [ ] **Step 2: Run the facade test**

Run:

```powershell
pytest tests/test_listener.py::test_wechat_listen_conversation_batches_delegates_to_listener -q
```

Expected: PASS because the facade already forwards arbitrary `**kwargs`.

- [ ] **Step 3: Update README**

In `README.md`, under the existing `Conversation batch listener` section, add:

````markdown
Sender resolution is opt-in because it clicks visible avatars and may slow down
or disturb the WeChat UI. Enable it only when the robot needs group-chat sender
names:

```python
wx.listen_conversation_batches(
    on_batch,
    max_chats_per_drain=5,
    resolve_senders="profile_card",
    sender_resolve_limit=5,
)
```
````

- [ ] **Step 4: Run focused tests**

Run:

```powershell
pytest tests/test_bridge_listener.py tests/test_listener.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full verification**

Run:

```powershell
pytest -q
```

Expected: PASS.

Run:

```powershell
python -c "from my_wxauto import WeChat; import inspect; print('resolve_senders' in str(inspect.signature(__import__('my_wxauto.listener').listener.listen_conversation_batches)))"
```

Expected output:

```text
True
```

Run:

```powershell
git diff --check
```

Expected: exit code 0.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add README.md tests/test_listener.py
git commit -m "Document optional batch sender resolution"
```

---

## Spec Coverage Check

- Default fast listener remains unchanged: Task 2 default-mode test fails if resolver runs.
- Explicit opt-in API: Task 2 adds `resolve_senders`, `sender_resolve_limit`, `sender_resolve_timeout`, `profile_card_timeout`, and `sender_progress`.
- Reuse existing profile-card strategy: Task 1 helper calls `_resolve_sender_from_profile_card`.
- Skip self messages: Task 1 updates `_resolve_visible_message_senders` and tests `skipped_self`.
- Preserve reliability semantics: enrichment happens before `messages_from_chat_payload`, then existing batcher/store/frozen retry flow remains unchanged.
- Real robot integration value: README documents opt-in behavior and the batch payload gets enriched `sender/is_self` where available.

## Execution Notes

- Do not add Hermes/OpenClaw integration in this plan.
- Do not add HTTP/SSE/WebSocket bridge service in this plan.
- Do not make sender resolution default-on.
- Do not modify the probe process to click avatars; avatar clicking must stay in the parent listener process through existing profile-card helpers.
- Keep commits task-sized.
