from __future__ import annotations

import time

import my_wxauto
from my_wxauto import listener
from my_wxauto.bridge_events import BridgeMessage, ConversationBatch
from my_wxauto.listener import ChatMessage, get_latest_message, get_visible_messages, listen_new_messages
from my_wxauto.wechat import WeChat
from my_wxauto.window import WindowRect


def test_listen_new_messages_calls_callback_with_latest_message(monkeypatch) -> None:
    icon_hashes = iter(["baseline", "changed"])
    events = []

    def fake_icons() -> list[dict[str, object]]:
        image_hash = next(icon_hashes, "changed")
        return [
            {
                "source": "primary-taskbar",
                "class_name": "Shell_TrayWnd",
                "rectangle": [0, 0, 10, 10],
                "image_sha1": image_hash,
            }
        ]

    def fake_probe(**kwargs: object) -> dict[str, object]:
        assert kwargs["open_unread_messages"] is True
        assert kwargs["max_controls"] == 12
        assert kwargs["timeout"] == 2.5
        return {
            "status": "ok",
            "unread_count": 1,
            "sessions": [
                {
                    "chat_name": "张勋",
                    "preview": "Alice: world",
                }
            ],
            "opened_unread_chats": [
                {
                    "chat_name": "张勋",
                    "source": "unread_session",
                    "messages": [
                        {
                            "content": "hello",
                            "message_type": "text",
                            "sender": None,
                            "time_text": "15:40",
                            "raw_name": "hello",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                        },
                        {
                            "content": "world",
                            "message_type": "text",
                            "sender": None,
                            "time_text": "15:41",
                            "raw_name": "world",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 5, "top": 6, "right": 7, "bottom": 8},
                        },
                    ],
                }
            ],
        }

    monkeypatch.setattr(listener.probes, "_ensure_windows", lambda: None)
    monkeypatch.setattr(listener.probes, "inspect_wechat_taskbar_icons", fake_icons)
    monkeypatch.setattr(listener.probes, "_probe_sessions_after_wakeup_with_timeout", fake_probe)
    monkeypatch.setattr(listener.time, "sleep", lambda _seconds: None)

    stats = listen_new_messages(
        events.append,
        seconds=5,
        interval=0.01,
        min_changes=1,
        max_controls=12,
        action_timeout=2.5,
        max_events=1,
    )

    assert stats.event_count == 1
    assert stats.flash_count == 1
    assert stats.stopped_reason == "max_events"
    assert events[0].chat_name == "张勋"
    assert len(events[0].messages) == 2
    assert events[0].latest_message is not None
    assert events[0].messages[0].content == "hello"
    assert events[0].messages[0].sender is None
    assert events[0].messages[0].time_text == "15:40"
    assert events[0].latest_message.content == "world"
    assert events[0].latest_message.sender == "Alice"
    assert events[0].latest_message.time_text == "15:41"


def test_events_from_probe_leaves_sender_empty_when_preview_does_not_match_latest_message() -> None:
    payload = {
        "unread_count": 1,
        "sessions": [
            {
                "chat_name": "张勋、张盼",
                "preview": "张勋: 另一条消息",
            }
        ],
        "opened_unread_chats": [
            {
                "chat_name": "张勋、张盼",
                "source": "unread_session",
                "messages": [
                    {
                        "content": "哈哈",
                        "message_type": "text",
                        "sender": None,
                        "raw_name": "哈哈",
                        "class_name": "mmui::ChatTextItemView",
                        "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                        "rect": {},
                    }
                ],
            }
        ],
    }

    events = listener._events_from_probe(payload, flash_index=1)

    assert events[0].latest_message is not None
    assert events[0].latest_message.sender is None


def test_chat_message_carries_is_self_flag() -> None:
    message = ChatMessage.from_probe(
        {
            "content": "hello",
            "message_type": "text",
            "is_self": True,
            "rect": {"left": 1, "top": 2, "right": 3, "bottom": 4},
        }
    )

    assert message.is_self is True
    assert message.to_dict()["is_self"] is True


def test_get_latest_message_returns_latest_visible_message_with_sender_from_preview(monkeypatch) -> None:
    def fake_payload(*, chat_name: str, max_controls: int, include_sessions: bool = True, **_kwargs: object) -> dict[str, object]:
        assert chat_name == "张勋、张盼"
        assert max_controls == 12
        assert include_sessions is True
        return {
            "unread_count": 0,
            "sessions": [
                {
                    "chat_name": "张勋、张盼",
                    "preview": "张勋: 哈哈",
                }
            ],
            "opened_unread_chats": [
                {
                    "chat_name": "张勋、张盼",
                    "source": "current_chat",
                    "messages": [
                        {
                            "content": "嗯",
                            "message_type": "text",
                            "sender": None,
                            "time_text": "4月30日 15:57",
                            "raw_name": "嗯",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {},
                        },
                        {
                            "content": "哈哈",
                            "message_type": "text",
                            "sender": None,
                            "time_text": "4月30日 16:19",
                            "raw_name": "哈哈",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {},
                        },
                    ],
                }
            ],
        }

    monkeypatch.setattr(listener, "_collect_current_chat_payload", fake_payload)

    message = get_latest_message("张勋、张盼", max_controls=12)

    assert message is not None
    assert message.content == "哈哈"
    assert message.sender == "张勋"
    assert message.time_text == "4月30日 16:19"


def test_get_visible_messages_can_resolve_senders_with_profile_card_strategy(monkeypatch) -> None:
    def fake_payload(*, chat_name: str, max_controls: int, include_sessions: bool = True, **_kwargs: object) -> dict[str, object]:
        assert include_sessions is False
        return {
            "unread_count": 0,
            "sessions": [],
            "opened_unread_chats": [
                {
                    "chat_name": chat_name,
                    "source": "current_chat",
                    "messages": [
                        {
                            "content": "第一条",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "第一条",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                        },
                        {
                            "content": "第二条",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "第二条",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 5, "top": 6, "right": 7, "bottom": 8},
                        },
                    ],
                }
            ],
        }

    def fake_resolver(message: ChatMessage) -> str | None:
        return {"第一条": "张盼", "第二条": "张勋"}.get(message.content)

    monkeypatch.setattr(listener, "_collect_current_chat_payload", fake_payload)

    messages = get_visible_messages(
        "张勋、张盼",
        resolve_senders="profile_card",
        sender_resolver=fake_resolver,
    )

    assert [message.content for message in messages] == ["第一条", "第二条"]
    assert [message.sender for message in messages] == ["张盼", "张勋"]


def test_get_visible_messages_limits_profile_card_sender_resolution(monkeypatch) -> None:
    def fake_payload(*, chat_name: str, max_controls: int, include_sessions: bool = True, **_kwargs: object) -> dict[str, object]:
        return {
            "unread_count": 0,
            "sessions": [],
            "opened_unread_chats": [
                {
                    "chat_name": chat_name,
                    "source": "current_chat",
                    "messages": [
                        {
                            "content": "第一条",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "第一条",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 1, "top": 2, "right": 3, "bottom": 4},
                        },
                        {
                            "content": "第二条",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "第二条",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 5, "top": 6, "right": 7, "bottom": 8},
                        },
                    ],
                }
            ],
        }

    resolver_calls: list[str] = []
    progress_events: list[dict[str, object]] = []

    def fake_resolver(message: ChatMessage) -> str | None:
        resolver_calls.append(message.content)
        return f"{message.content}发送人"

    monkeypatch.setattr(listener, "_collect_current_chat_payload", fake_payload)

    messages = get_visible_messages(
        "张勋、张盼",
        resolve_senders="profile_card",
        sender_resolver=fake_resolver,
        sender_resolve_limit=1,
        sender_progress=progress_events.append,
    )

    assert resolver_calls == ["第一条"]
    assert [message.sender for message in messages] == ["第一条发送人", None]
    assert [event["stage"] for event in progress_events] == ["start", "resolved", "skipped_limit"]


def test_get_visible_messages_skips_profile_card_resolution_when_avatar_is_not_visible(monkeypatch) -> None:
    def fake_payload(*, chat_name: str, max_controls: int, **_kwargs: object) -> dict[str, object]:
        return {
            "unread_count": 0,
            "sessions": [],
            "opened_unread_chats": [
                {
                    "chat_name": chat_name,
                    "source": "current_chat",
                    "messages": [
                        {
                            "content": "顶部裁剪消息",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "顶部裁剪消息",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 100, "top": 0, "right": 700, "bottom": 8},
                        },
                        {
                            "content": "可点击消息",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "可点击消息",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 100, "top": 120, "right": 700, "bottom": 180},
                        },
                    ],
                }
            ],
        }

    resolver_calls: list[str] = []
    progress_events: list[dict[str, object]] = []

    def fake_profile_card_resolver(message: ChatMessage, **_kwargs: object) -> str | None:
        resolver_calls.append(message.content)
        return "张勋"

    monkeypatch.setattr(listener, "_collect_current_chat_payload", fake_payload)
    monkeypatch.setattr(listener, "_resolve_sender_from_profile_card", fake_profile_card_resolver)

    messages = get_visible_messages(
        "张勋、张盼",
        resolve_senders="profile_card",
        sender_resolve_limit=1,
        sender_progress=progress_events.append,
    )

    assert resolver_calls == ["可点击消息"]
    assert [message.sender for message in messages] == [None, "张勋"]
    assert [event["stage"] for event in progress_events] == ["skipped_no_avatar", "start", "resolved"]


def test_get_visible_messages_skips_default_profile_card_resolution_for_non_text(monkeypatch) -> None:
    def fake_payload(*, chat_name: str, max_controls: int, **_kwargs: object) -> dict[str, object]:
        return {
            "unread_count": 0,
            "sessions": [],
            "opened_unread_chats": [
                {
                    "chat_name": chat_name,
                    "source": "current_chat",
                    "messages": [
                        {
                            "content": "图片",
                            "message_type": "unknown",
                            "sender": None,
                            "raw_name": "图片",
                            "class_name": "mmui::ChatBubbleItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 100, "top": 120, "right": 700, "bottom": 180},
                        },
                        {
                            "content": "文本消息",
                            "message_type": "text",
                            "sender": None,
                            "raw_name": "文本消息",
                            "class_name": "mmui::ChatTextItemView",
                            "automation_id": "chat_message_list.qt_scrollarea_viewport.chat_bubble_item_view",
                            "rect": {"left": 100, "top": 180, "right": 700, "bottom": 240},
                        },
                    ],
                }
            ],
        }

    resolver_calls: list[str] = []

    def fake_profile_card_resolver(message: ChatMessage, **_kwargs: object) -> str | None:
        resolver_calls.append(message.content)
        return "张勋"

    monkeypatch.setattr(listener, "_collect_current_chat_payload", fake_payload)
    monkeypatch.setattr(listener, "_resolve_sender_from_profile_card", fake_profile_card_resolver)

    messages = get_visible_messages("张勋、张盼", resolve_senders="profile_card", sender_resolve_limit=1)

    assert resolver_calls == ["文本消息"]
    assert [message.sender for message in messages] == [None, "张勋"]


def test_avatar_click_points_target_avatar_columns_from_message_row() -> None:
    message = ChatMessage(
        content="嗯",
        message_type="text",
        rect={"left": 350, "top": 419, "right": 926, "bottom": 475},
        visible_rect={"left": 350, "top": 419, "right": 926, "bottom": 475},
    )

    points = listener._avatar_click_points(message)

    assert (358, 447) in points
    assert (846, 447) in points


def test_infer_message_is_self_from_right_green_bubble_pixels() -> None:
    region = WindowRect(left=100, top=200, right=500, bottom=320)
    raw = bytearray([255, 255, 255, 255] * (region.width * region.height))
    for y in range(30, 70):
        for x in range(250, 360):
            offset = (y * region.width + x) * 4
            raw[offset : offset + 4] = bytes([105, 220, 150, 255])
    message = {
        "message_type": "text",
        "visible_rect": {"left": 100, "top": 200, "right": 500, "bottom": 320},
    }

    assert listener._infer_message_is_self_from_pixels(message, region, bytes(raw)) is True


def test_infer_message_is_not_self_without_right_green_bubble_pixels() -> None:
    region = WindowRect(left=100, top=200, right=500, bottom=320)
    raw = bytearray([255, 255, 255, 255] * (region.width * region.height))
    for y in range(30, 70):
        for x in range(20, 120):
            offset = (y * region.width + x) * 4
            raw[offset : offset + 4] = bytes([235, 235, 235, 255])
    message = {
        "message_type": "text",
        "visible_rect": {"left": 100, "top": 200, "right": 500, "bottom": 320},
    }

    assert listener._infer_message_is_self_from_pixels(message, region, bytes(raw)) is False


def test_profile_name_priority_prefers_display_name_and_rejects_labels() -> None:
    assert (
        listener._profile_name_priority(
            "Lagom",
            control_type="Text",
            class_name="mmui::XTextView",
            automation_id="right_v_view.nickname_button_view.display_name_text",
        )
        == 0
    )
    assert listener._profile_name_priority(
        "备注",
        control_type="Text",
        class_name="mmui::XTextView",
        automation_id="remark_line.key_text_h_view.key_text_view",
    ) is None


def test_profile_card_name_reader_timeout_returns_none(monkeypatch) -> None:
    def slow_reader(*, timeout: float = 2.0, max_controls: int = 80) -> str | None:
        time.sleep(0.2)
        return "迟到的昵称"

    monkeypatch.setattr(listener, "_read_profile_card_name", slow_reader)

    started = time.perf_counter()
    sender = listener._read_profile_card_name_with_timeout(timeout=0.01)

    assert sender is None
    assert time.perf_counter() - started < 0.15


def test_collect_region_controls_retries_when_first_attempt_is_empty(monkeypatch) -> None:
    calls: list[float] = []

    def fake_collect(window: object, *, region: object, max_controls: int, timeout: float) -> list[dict[str, object]]:
        calls.append(timeout)
        if len(calls) == 1:
            return []
        return [{"name": "嗯"}]

    monkeypatch.setattr(listener, "_collect_uia_controls_with_timeout", fake_collect)
    monkeypatch.setattr(listener.time, "sleep", lambda _seconds: None)

    controls = listener._collect_region_controls_with_retries(
        object(),
        region=object(),
        max_controls=10,
        timeout=2.0,
        attempts=3,
        delay=0.1,
    )

    assert controls == [{"name": "嗯"}]
    assert calls == [2.0, 2.0]


def test_wechat_listen_new_messages_delegates_to_listener(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def callback(event: object) -> None:
        calls.append({"callback_event": event})

    def fake_listen_new_messages(callback_arg, **kwargs: object) -> str:
        calls.append({"callback": callback_arg, **kwargs})
        return "stats"

    monkeypatch.setattr(listener, "listen_new_messages", fake_listen_new_messages)

    wx = WeChat(prefer_wxauto4=False)
    result = wx.listen_new_messages(callback, seconds=3, max_events=1)

    assert result == "stats"
    assert calls == [{"callback": callback, "seconds": 3, "max_events": 1}]


def test_wechat_listen_conversation_batches_delegates_to_listener(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def callback(batch: object) -> None:
        calls.append({"callback_batch": batch})

    def fake_listen_conversation_batches(callback_arg, **kwargs: object) -> str:
        calls.append({"callback": callback_arg, **kwargs})
        return "batch-stats"

    monkeypatch.setattr(listener, "listen_conversation_batches", fake_listen_conversation_batches)

    wx = WeChat(prefer_wxauto4=False)
    result = wx.listen_conversation_batches(callback, seconds=3, max_events=1)

    assert result == "batch-stats"
    assert calls == [{"callback": callback, "seconds": 3, "max_events": 1}]


def test_bridge_public_exports() -> None:
    assert my_wxauto.BridgeMessage is BridgeMessage
    assert my_wxauto.ConversationBatch is ConversationBatch
    assert "BridgeMessage" in my_wxauto.__all__
    assert "ConversationBatch" in my_wxauto.__all__


def test_wechat_message_reader_methods_delegate_to_listener(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_latest_message(who: str, **kwargs: object) -> str:
        calls.append({"method": "latest", "who": who, **kwargs})
        return "latest"

    def fake_get_visible_messages(who: str, **kwargs: object) -> str:
        calls.append({"method": "visible", "who": who, **kwargs})
        return "visible"

    monkeypatch.setattr(listener, "get_latest_message", fake_get_latest_message)
    monkeypatch.setattr(listener, "get_visible_messages", fake_get_visible_messages)

    wx = WeChat(prefer_wxauto4=False)

    assert wx.get_latest_message("张勋", max_controls=12) == "latest"
    assert wx.GetLatestMessage("张勋", max_controls=13) == "latest"
    assert wx.get_visible_messages("张勋", resolve_senders="profile_card") == "visible"
    assert wx.GetVisibleMessages("张勋", resolve_senders=False) == "visible"
    assert calls == [
        {"method": "latest", "who": "张勋", "open_chat": wx.ChatWith, "max_controls": 12},
        {"method": "latest", "who": "张勋", "open_chat": wx.ChatWith, "max_controls": 13},
        {"method": "visible", "who": "张勋", "open_chat": wx.ChatWith, "resolve_senders": "profile_card"},
        {"method": "visible", "who": "张勋", "open_chat": wx.ChatWith, "resolve_senders": False},
    ]


def test_wechat_message_reader_methods_can_skip_opening_chat(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_get_visible_messages(who: str, **kwargs: object) -> str:
        calls.append({"method": "visible", "who": who, **kwargs})
        return "visible"

    monkeypatch.setattr(listener, "get_visible_messages", fake_get_visible_messages)

    wx = WeChat(prefer_wxauto4=False)

    assert wx.get_visible_messages("张勋", open_first=False) == "visible"
    assert calls == [{"method": "visible", "who": "张勋", "open_chat": None}]
