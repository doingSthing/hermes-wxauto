from __future__ import annotations

import json

import pytest

from my_wxauto import hermes_sidecar
from my_wxauto.hermes_sidecar import BridgeClient, format_prompt, session_name_for_chat


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_format_prompt_includes_chat_and_messages() -> None:
    prompt = format_prompt(
        {
            "chat_name": "测试群",
            "messages": [
                {"time_text": "09:30", "sender": "Alice", "content": "早上好"},
                {"time_text": None, "sender": None, "is_self": True, "content": " 我来处理 "},
                {"sender": None, "is_self": False, "content": "谢谢"},
                {"sender": "Ignored", "content": ""},
                {"sender": "Blank", "content": "   "},
                "not a message",
            ],
        }
    )

    assert "你正在作为微信机器人回复一个会话。" in prompt
    assert "会话名：测试群" in prompt
    assert "本次收到的新消息：" in prompt
    assert "- 09:30 Alice: 早上好" in prompt
    assert "- 我: 我来处理" in prompt
    assert "- 对方: 谢谢" in prompt
    assert "Ignored" not in prompt
    assert "Blank" not in prompt
    assert "not a message" not in prompt
    assert "会话名：测试群\n\n本次收到的新消息：" in prompt
    assert "谢谢\n\n请只输出要发送到微信的回复文本。" in prompt
    assert prompt.endswith("请只输出要发送到微信的回复文本。不要解释，不要包含前后缀。")


def test_session_name_for_chat_is_stable_and_ascii() -> None:
    first = session_name_for_chat("测试群")
    second = session_name_for_chat("测试群")

    assert first == second
    assert first.startswith("wxauto-")
    assert first.isascii()
    assert len(first) <= 48


def test_format_prompt_normalizes_none_chat_name() -> None:
    prompt = format_prompt({"chat_name": None, "messages": []})

    assert "会话名：" in prompt
    assert "会话名：None" not in prompt


def test_session_name_for_chat_normalizes_non_string_values() -> None:
    none_name = session_name_for_chat(None)
    numeric_name = session_name_for_chat(123)

    assert none_name == session_name_for_chat(None)
    assert numeric_name == session_name_for_chat(123)
    assert none_name.startswith("wxauto-")
    assert numeric_name.startswith("wxauto-")
    assert none_name.isascii()
    assert numeric_name.isascii()
    assert len(none_name) <= 48
    assert len(numeric_name) <= 48


def test_bridge_client_gets_health(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_urlopen(req: object, timeout: float) -> _Response:
        calls.append((req, timeout))
        return _Response(b'{"ok": true}')

    monkeypatch.setattr(hermes_sidecar.request, "urlopen", fake_urlopen)

    client = BridgeClient("http://127.0.0.1:8765/", timeout=3.0)
    result = client.health()

    req, timeout = calls[0]
    assert result == {"ok": True}
    assert req.full_url == "http://127.0.0.1:8765/health"
    assert req.get_method() == "GET"
    assert timeout == 3.0


def test_bridge_client_polls_events(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_urlopen(req: object, timeout: float) -> _Response:
        calls.append((req, timeout))
        return _Response(b'{"events": []}')

    monkeypatch.setattr(hermes_sidecar.request, "urlopen", fake_urlopen)

    client = BridgeClient("http://bridge", timeout=2.5)
    result = client.poll_events(timeout=30.0, limit=10)

    req, request_timeout = calls[0]
    assert result == {"events": []}
    assert req.full_url == "http://bridge/events?timeout=30.0&limit=10"
    assert req.get_method() == "GET"
    assert request_timeout == 32.5


def test_bridge_client_sends_message(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_urlopen(req: object, timeout: float) -> _Response:
        calls.append((req, timeout))
        return _Response(b'{"sent": true}')

    monkeypatch.setattr(hermes_sidecar.request, "urlopen", fake_urlopen)

    client = BridgeClient("http://bridge", timeout=4.0)
    result = client.send("张三", "你好")

    req, timeout = calls[0]
    assert result == {"sent": True}
    assert req.full_url == "http://bridge/send"
    assert req.get_method() == "POST"
    assert json.loads(req.data.decode("utf-8")) == {"who": "张三", "message": "你好"}
    assert "你好".encode("utf-8") in req.data
    headers = {k.lower(): v for k, v in req.headers.items()}
    assert headers["content-type"] == "application/json; charset=utf-8"
    assert timeout == 4.0


def test_bridge_client_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req: object, timeout: float) -> _Response:
        return _Response(b'[]')

    monkeypatch.setattr(hermes_sidecar.request, "urlopen", fake_urlopen)

    client = BridgeClient("http://bridge")

    with pytest.raises(RuntimeError, match="bridge response must be a JSON object"):
        client.health()
