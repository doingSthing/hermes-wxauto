# 本地微信桥接服务第一版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows-local HTTP bridge service that exposes WeChat conversation batch events and text sending for Hermes/OpenClaw-style local consumers.

**Architecture:** Add a focused `my_wxauto.bridge_server` module using Python standard-library `ThreadingHTTPServer`. A `BridgeRuntime` owns a `WeChat` instance, a bounded in-memory event queue, a listener thread, and a shared UI lock; the CLI starts the server and maps existing listener options into `BridgeServerConfig`.

**Tech Stack:** Python standard library (`http.server`, `threading`, `queue`, `json`, `urllib.parse`), existing `WeChat`, `listen_conversation_batches`, `ConversationBatch`, `WxResponse`, pytest.

---

## File Structure

- Modify `src/my_wxauto/listener.py`
  - Add optional `ui_lock` support to serialize the real probe section.
  - Keep existing behavior unchanged when `ui_lock=None`.

- Create `src/my_wxauto/bridge_server.py`
  - Define `BridgeServerConfig`, `BridgeRuntime`, `BridgeRequestHandler`, `BridgeHTTPServer`, and `run_bridge_server`.
  - Keep HTTP parsing and runtime behavior in one focused module.

- Modify `src/my_wxauto/cli.py`
  - Add `--bridge-server`, `--bridge-host`, `--bridge-port`, and queue/server options.
  - Reuse existing listener options: `--listen-max-chats`, `--listen-resolve-senders`, `--listen-sender-limit`, `--store-path`, `--no-wxauto4`, `--debug`, `--trace-ui`.

- Add `tests/test_bridge_server.py`
  - Unit-test runtime queue behavior, HTTP endpoints, bad requests, and queue overflow.

- Modify `tests/test_bridge_listener.py`
  - Add a lock-focused regression test for `ui_lock`.

- Modify `tests/test_cli.py`
  - Add a CLI test proving bridge server args build the expected config.

- Modify `README.md`
  - Add a short “Local bridge server” usage section after implementation is stable.

## Current Workspace Note

Before bridge-server implementation, the worktree already contains useful uncommitted changes from the listener debugging pass:

- `.gitignore` ignores `*.sqlite3`.
- `src/my_wxauto/cli.py` has `--listen-batches` debug output.
- `src/my_wxauto/listener.py` only batches the unread suffix when `unread_count` is available.
- `tests/test_bridge_listener.py` and `tests/test_cli.py` cover those behaviors.

Keep those changes. Do not revert them. Commit them either as a prerequisite commit before Task 1 or together with the first implementation checkpoint if the execution session has not already committed them.

---

### Task 1: Add `ui_lock` Support To The Listener

**Files:**
- Modify: `src/my_wxauto/listener.py`
- Test: `tests/test_bridge_listener.py`

- [ ] **Step 1: Write the failing lock regression test**

Append this test near the other `listen_conversation_batches` tests in `tests/test_bridge_listener.py`:

```python
def test_listen_conversation_batches_holds_ui_lock_during_probe(monkeypatch, tmp_path) -> None:
    emitted = []
    lock_events: list[str] = []

    class RecordingLock:
        def __enter__(self):
            lock_events.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            lock_events.append("exit")
            return False

    def fake_icons() -> list[dict[str, object]]:
        lock_events.append("icons")
        return [{"image_sha1": "changed"}]

    class FakeDetector:
        def __init__(self, **_kwargs: object) -> None:
            self.calls = 0

        def observe(self, _now: float, _signature: object) -> dict[str, object] | None:
            self.calls += 1
            return {"change_count": 1} if self.calls == 1 else None

    def fake_probe(**kwargs: object) -> dict[str, object]:
        lock_events.append("probe")
        kwargs["on_chat_opened"](
            {
                "chat_name": "alice",
                "source": "unread_session",
                "unread_count": 1,
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
        max_probes=1,
        ui_lock=RecordingLock(),
        store_path=tmp_path / "bridge.sqlite3",
        batching_config=BatchingConfig(quiet_window_seconds=0.0, max_batch_wait_seconds=8.0, max_batch_messages=10),
    )

    assert stats.event_count == 1
    assert [batch.messages[0].content for batch in emitted] == ["hello"]
    assert lock_events == ["icons", "enter", "probe", "exit"]
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
pytest tests/test_bridge_listener.py::test_listen_conversation_batches_holds_ui_lock_during_probe
```

Expected: fail with `TypeError` because `listen_conversation_batches()` does not accept `ui_lock`.

- [ ] **Step 3: Implement minimal `ui_lock` support**

In `src/my_wxauto/listener.py`, import `nullcontext`:

```python
from contextlib import nullcontext
```

Add the parameter to `listen_conversation_batches`:

```python
    ui_lock: Any | None = None,
```

Wrap only the real probe call in the main loop:

```python
            lock_context = ui_lock if ui_lock is not None else nullcontext()
            with lock_context:
                probes._probe_sessions_after_wakeup_with_timeout(
                    max_controls=max_controls,
                    timeout=action_timeout,
                    restore_icons=icons,
                    open_unread_messages=True,
                    max_unread_chats=effective_max_chats_per_drain,
                    max_ui_busy_seconds=max_ui_busy_seconds,
                    on_chat_opened=on_chat_opened,
                )
```

Do not hold the lock while sleeping, freezing batches, or invoking HTTP consumers.

- [ ] **Step 4: Verify listener tests**

Run:

```powershell
pytest tests/test_bridge_listener.py
```

Expected: all tests in `tests/test_bridge_listener.py` pass.

- [ ] **Step 5: Commit**

```powershell
git add src/my_wxauto/listener.py tests/test_bridge_listener.py
git commit -m "Add listener UI lock support"
```

---

### Task 2: Create Bridge Runtime And Queue Semantics

**Files:**
- Create: `src/my_wxauto/bridge_server.py`
- Test: `tests/test_bridge_server.py`

- [ ] **Step 1: Write failing runtime tests**

Create `tests/test_bridge_server.py` with these tests:

```python
from __future__ import annotations

import queue
import threading

import pytest

from my_wxauto.bridge_events import BridgeMessage, ConversationBatch
from my_wxauto.bridge_server import BridgeRuntime, BridgeServerConfig
from my_wxauto.response import WxResponse


class FakeWeChat:
    def __init__(self) -> None:
        self.listen_kwargs: dict[str, object] | None = None
        self.sent: list[tuple[str, str]] = []

    def listen_conversation_batches(self, callback, **kwargs: object):
        self.listen_kwargs = kwargs
        return None

    def SendMsg(self, message: str, who: str):
        self.sent.append((who, message))
        return WxResponse.success("sent", {"who": who, "message": message})


def _batch(content: str = "hello") -> ConversationBatch:
    message = BridgeMessage(
        chat_name="alice",
        content=content,
        message_type="text",
        sender="alice",
        is_self=False,
        time_text="15:41",
    ).with_key()
    return ConversationBatch(
        batch_id=f"batch-{content}",
        chat_name="alice",
        messages=(message,),
        created_at=10.0,
        frozen_at=11.0,
        status="frozen",
    )


def test_runtime_enqueue_and_poll_events() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(queue_size=2), wechat=FakeWeChat())

    runtime.enqueue_batch(_batch("one"))
    runtime.enqueue_batch(_batch("two"))

    payload = runtime.poll_events(timeout=0.0, limit=5)

    assert payload["status"] == "ok"
    assert payload["count"] == 2
    assert [event["messages"][0]["content"] for event in payload["events"]] == ["one", "two"]
    assert runtime.health()["queue_size"] == 0


def test_runtime_poll_events_times_out_empty() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(queue_size=2), wechat=FakeWeChat())

    payload = runtime.poll_events(timeout=0.01, limit=5)

    assert payload == {"status": "ok", "count": 0, "events": []}


def test_runtime_enqueue_raises_when_queue_is_full() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(queue_size=1), wechat=FakeWeChat())
    runtime.enqueue_batch(_batch("one"))

    with pytest.raises(queue.Full):
        runtime.enqueue_batch(_batch("two"))


def test_runtime_send_message_uses_ui_lock() -> None:
    events: list[str] = []

    class RecordingLock:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, exc_type, exc, tb):
            events.append("exit")
            return False

    wx = FakeWeChat()
    runtime = BridgeRuntime(BridgeServerConfig(), wechat=wx, ui_lock=RecordingLock())

    response = runtime.send_message("alice", "hello")

    assert response["status"] == "success"
    assert wx.sent == [("alice", "hello")]
    assert events == ["enter", "exit"]


def test_runtime_start_listener_passes_config_and_lock(monkeypatch) -> None:
    wx = FakeWeChat()
    started: list[threading.Thread] = []

    def fake_thread(*, target, daemon):
        thread = threading.Thread(target=lambda: None, daemon=daemon)
        started.append(thread)
        return thread

    monkeypatch.setattr("my_wxauto.bridge_server.threading.Thread", fake_thread)
    config = BridgeServerConfig(
        store_path="bridge.sqlite3",
        max_chats_per_drain=3,
        resolve_senders="profile_card",
        sender_resolve_limit=4,
    )
    runtime = BridgeRuntime(config, wechat=wx)

    runtime.start_listener()
    runtime._listener_target()

    assert len(started) == 1
    assert started[0].daemon is True
    assert wx.listen_kwargs is not None
    assert wx.listen_kwargs["store_path"] == "bridge.sqlite3"
    assert wx.listen_kwargs["max_chats_per_drain"] == 3
    assert wx.listen_kwargs["resolve_senders"] == "profile_card"
    assert wx.listen_kwargs["sender_resolve_limit"] == 4
    assert wx.listen_kwargs["ui_lock"] is runtime.ui_lock
```

- [ ] **Step 2: Run failing runtime tests**

Run:

```powershell
pytest tests/test_bridge_server.py
```

Expected: fail because `my_wxauto.bridge_server` does not exist.

- [ ] **Step 3: Implement runtime skeleton**

Create `src/my_wxauto/bridge_server.py` with:

```python
from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .bridge_events import ConversationBatch
from .wechat import WeChat


@dataclass(frozen=True)
class BridgeServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    store_path: str | Path = ".my_wxauto_bridge.sqlite3"
    queue_size: int = 100
    listen_interval: float = 0.25
    max_chats_per_drain: int = 5
    resolve_senders: bool | str = False
    sender_resolve_limit: int = 5
    prefer_wxauto4: bool = True
    debug: bool = False
    trace_ui: bool = False


class BridgeRuntime:
    def __init__(
        self,
        config: BridgeServerConfig,
        *,
        wechat: Any | None = None,
        ui_lock: Any | None = None,
    ) -> None:
        self.config = config
        self.ui_lock = ui_lock or threading.RLock()
        self.wechat = wechat or WeChat(
            prefer_wxauto4=config.prefer_wxauto4,
            debug=config.debug,
            trace_ui=config.trace_ui,
            bridge_store_path=config.store_path,
        )
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=config.queue_size)
        self._listener_thread: threading.Thread | None = None

    def health(self) -> dict[str, Any]:
        thread = self._listener_thread
        return {
            "status": "ok",
            "queue_size": self._events.qsize(),
            "listener_alive": bool(thread and thread.is_alive()),
            "store_path": str(self.config.store_path),
        }

    def enqueue_batch(self, batch: ConversationBatch) -> None:
        self._events.put_nowait(batch.to_event_dict())

    def poll_events(self, *, timeout: float = 30.0, limit: int = 5) -> dict[str, Any]:
        timeout = _clamp_float(timeout, minimum=0.0, maximum=120.0, default=30.0)
        limit = _clamp_int(limit, minimum=1, maximum=50, default=5)
        events: list[dict[str, Any]] = []
        try:
            events.append(self._events.get(timeout=timeout))
        except queue.Empty:
            return {"status": "ok", "count": 0, "events": []}

        while len(events) < limit:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return {"status": "ok", "count": len(events), "events": events}

    def send_message(self, who: str, message: str) -> dict[str, Any]:
        with self.ui_lock:
            response = self.wechat.SendMsg(message, who)
        return response.to_dict() if hasattr(response, "to_dict") else dict(response)

    def start_listener(self) -> None:
        if self._listener_thread is not None and self._listener_thread.is_alive():
            return
        self._listener_thread = threading.Thread(target=self._listener_target, daemon=True)
        self._listener_thread.start()

    def _listener_target(self) -> None:
        self.wechat.listen_conversation_batches(
            self.enqueue_batch,
            interval=self.config.listen_interval,
            max_chats_per_drain=self.config.max_chats_per_drain,
            store_path=self.config.store_path,
            resolve_senders=self.config.resolve_senders,
            sender_resolve_limit=self.config.sender_resolve_limit,
            ui_lock=self.ui_lock,
        )


def _clamp_float(value: object, *, minimum: float, maximum: float, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clamp_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))
```

Leave HTTP handler classes for Task 3.

- [ ] **Step 4: Verify runtime tests**

Run:

```powershell
pytest tests/test_bridge_server.py -k runtime
```

Expected: runtime tests pass. Handler tests may not exist yet.

- [ ] **Step 5: Commit**

```powershell
git add src/my_wxauto/bridge_server.py tests/test_bridge_server.py
git commit -m "Add bridge server runtime"
```

---

### Task 3: Add HTTP Handler For `/health`, `/events`, And `/send`

**Files:**
- Modify: `src/my_wxauto/bridge_server.py`
- Test: `tests/test_bridge_server.py`

- [ ] **Step 1: Add failing HTTP endpoint tests**

Append to `tests/test_bridge_server.py`:

```python
import http.client
import json

from my_wxauto.bridge_server import BridgeHTTPServer


def _server(runtime: BridgeRuntime) -> BridgeHTTPServer:
    server = BridgeHTTPServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _request(server: BridgeHTTPServer, method: str, path: str, body: dict[str, object] | str | None = None):
    conn = http.client.HTTPConnection(server.server_address[0], server.server_address[1], timeout=2)
    headers = {}
    payload: str | None = None
    if isinstance(body, dict):
        payload = json.dumps(body, ensure_ascii=False)
        headers["Content-Type"] = "application/json"
    elif isinstance(body, str):
        payload = body
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    response = conn.getresponse()
    data = response.read().decode("utf-8")
    conn.close()
    return response.status, json.loads(data)


def test_http_health_endpoint() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(store_path="bridge.sqlite3"), wechat=FakeWeChat())
    server = _server(runtime)
    try:
        status, payload = _request(server, "GET", "/health")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert payload["status"] == "ok"
    assert payload["queue_size"] == 0
    assert payload["store_path"] == "bridge.sqlite3"


def test_http_events_endpoint_returns_queued_events() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(), wechat=FakeWeChat())
    runtime.enqueue_batch(_batch("hello"))
    server = _server(runtime)
    try:
        status, payload = _request(server, "GET", "/events?timeout=0&limit=5")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert payload["count"] == 1
    assert payload["events"][0]["messages"][0]["content"] == "hello"


def test_http_events_endpoint_times_out_empty() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(), wechat=FakeWeChat())
    server = _server(runtime)
    try:
        status, payload = _request(server, "GET", "/events?timeout=0.01&limit=5")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert payload == {"status": "ok", "count": 0, "events": []}


def test_http_send_endpoint() -> None:
    wx = FakeWeChat()
    runtime = BridgeRuntime(BridgeServerConfig(), wechat=wx)
    server = _server(runtime)
    try:
        status, payload = _request(server, "POST", "/send", {"who": "alice", "message": "hello"})
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert payload["status"] == "success"
    assert wx.sent == [("alice", "hello")]


def test_http_send_rejects_invalid_json() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(), wechat=FakeWeChat())
    server = _server(runtime)
    try:
        status, payload = _request(server, "POST", "/send", "{bad json")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 400
    assert payload["status"] == "error"


def test_http_unknown_route_returns_404() -> None:
    runtime = BridgeRuntime(BridgeServerConfig(), wechat=FakeWeChat())
    server = _server(runtime)
    try:
        status, payload = _request(server, "GET", "/missing")
    finally:
        server.shutdown()
        server.server_close()

    assert status == 404
    assert payload["status"] == "error"
```

- [ ] **Step 2: Run failing HTTP tests**

Run:

```powershell
pytest tests/test_bridge_server.py -k http
```

Expected: fail because `BridgeHTTPServer` and request handling are not implemented.

- [ ] **Step 3: Implement HTTP classes**

Add to `src/my_wxauto/bridge_server.py`:

```python
class BridgeHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], runtime: BridgeRuntime) -> None:
        self.runtime = runtime
        super().__init__(server_address, BridgeRequestHandler)


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._write_json(200, self.server.runtime.health())
            return
        if parsed.path == "/events":
            query = parse_qs(parsed.query)
            timeout = query.get("timeout", [30.0])[0]
            limit = query.get("limit", [5])[0]
            self._write_json(200, self.server.runtime.poll_events(timeout=timeout, limit=limit))
            return
        self._write_json(404, {"status": "error", "message": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/send":
            self._write_json(404, {"status": "error", "message": "not found"})
            return

        try:
            payload = self._read_json()
        except ValueError as exc:
            self._write_json(400, {"status": "error", "message": str(exc)})
            return

        who = str(payload.get("who") or "").strip()
        message = str(payload.get("message") or "").strip()
        if not who or not message:
            self._write_json(400, {"status": "error", "message": "who and message are required"})
            return
        self._write_json(200, self.server.runtime.send_message(who, message))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid json") from exc
        if not isinstance(payload, dict):
            raise ValueError("json body must be an object")
        return payload

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
```

- [ ] **Step 4: Verify HTTP tests**

Run:

```powershell
pytest tests/test_bridge_server.py
```

Expected: all bridge server tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/my_wxauto/bridge_server.py tests/test_bridge_server.py
git commit -m "Add bridge server HTTP endpoints"
```

---

### Task 4: Wire Bridge Server Into The CLI

**Files:**
- Modify: `src/my_wxauto/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Append to `tests/test_cli.py`:

```python
def test_main_starts_bridge_server(monkeypatch, tmp_path) -> None:
    calls: list[object] = []

    def fake_run_bridge_server(config) -> None:
        calls.append(config)

    monkeypatch.setattr(cli, "run_bridge_server", fake_run_bridge_server)
    store_path = tmp_path / "bridge.sqlite3"

    exit_code = cli.main(
        [
            "--bridge-server",
            "--bridge-host",
            "127.0.0.1",
            "--bridge-port",
            "8765",
            "--bridge-queue-size",
            "20",
            "--listen-max-chats",
            "3",
            "--listen-resolve-senders",
            "profile_card",
            "--listen-sender-limit",
            "4",
            "--store-path",
            str(store_path),
            "--no-wxauto4",
        ]
    )

    config = calls[0]
    assert exit_code == 0
    assert config.host == "127.0.0.1"
    assert config.port == 8765
    assert config.queue_size == 20
    assert config.max_chats_per_drain == 3
    assert config.resolve_senders == "profile_card"
    assert config.sender_resolve_limit == 4
    assert config.store_path == str(store_path)
    assert config.prefer_wxauto4 is False
```

- [ ] **Step 2: Run failing CLI test**

Run:

```powershell
pytest tests/test_cli.py::test_main_starts_bridge_server
```

Expected: fail because bridge server CLI args or `run_bridge_server` import are missing.

- [ ] **Step 3: Implement CLI wiring**

In `src/my_wxauto/cli.py`, import:

```python
from .bridge_server import BridgeServerConfig, run_bridge_server
```

Add parser args:

```python
    parser.add_argument("--bridge-server", action="store_true", help="启动本地 HTTP 微信桥接服务")
    parser.add_argument("--bridge-host", default="127.0.0.1", help="桥接服务监听地址，默认仅本机")
    parser.add_argument("--bridge-port", type=int, default=8765, help="桥接服务监听端口")
    parser.add_argument("--bridge-queue-size", type=int, default=100, help="桥接服务内存事件队列容量")
```

Before the existing `if args.listen_batches:` branch, add:

```python
    if args.bridge_server:
        run_bridge_server(
            BridgeServerConfig(
                host=args.bridge_host,
                port=args.bridge_port,
                store_path=args.store_path,
                queue_size=args.bridge_queue_size,
                max_chats_per_drain=args.listen_max_chats,
                resolve_senders=_listener_sender_mode(args.listen_resolve_senders),
                sender_resolve_limit=args.listen_sender_limit,
                prefer_wxauto4=args.use_wxauto4,
                debug=args.debug,
                trace_ui=args.trace_ui,
            )
        )
        return 0
```

- [ ] **Step 4: Implement `run_bridge_server`**

Add to `src/my_wxauto/bridge_server.py`:

```python
def run_bridge_server(config: BridgeServerConfig) -> None:
    runtime = BridgeRuntime(config)
    runtime.start_listener()
    server = BridgeHTTPServer((config.host, int(config.port)), runtime)
    print(f"my-wxauto bridge server listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
```

- [ ] **Step 5: Verify CLI tests**

Run:

```powershell
pytest tests/test_cli.py
```

Expected: all CLI tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src/my_wxauto/cli.py src/my_wxauto/bridge_server.py tests/test_cli.py
git commit -m "Wire bridge server into CLI"
```

---

### Task 5: Document Usage And Run Full Verification

**Files:**
- Modify: `README.md`
- Test: full test suite

- [ ] **Step 1: Add README section**

Add this section after “Conversation batch listener” in `README.md`:

```markdown
## Local bridge server

`my-wxauto` can expose a local HTTP bridge for robot processes such as Hermes
or OpenClaw. The server stays on `127.0.0.1` by default and wraps the existing
conversation batch listener and text sender.

```powershell
python -m my_wxauto --bridge-server --bridge-host 127.0.0.1 --bridge-port 8765 --store-path .my_wxauto_bridge_server.sqlite3 --listen-resolve-senders profile_card
```

Fetch events with long polling:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/events?timeout=30&limit=5"
```

Send a text message:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/send" -Method Post -ContentType "application/json; charset=utf-8" -Body '{"who":"张勋","message":"你好"}'
```
```

If README encoding is already garbled, keep the added section UTF-8 and avoid rewriting unrelated text.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
pytest tests/test_bridge_server.py tests/test_bridge_listener.py tests/test_cli.py
```

Expected: targeted tests pass.

- [ ] **Step 3: Run full tests**

Run:

```powershell
pytest
```

Expected: all tests pass.

- [ ] **Step 4: Smoke-test help output**

Run:

```powershell
python -m my_wxauto --help | Select-String -Pattern "bridge-server|bridge-port|listen-resolve-senders"
```

Expected: help output includes bridge server flags.

- [ ] **Step 5: Commit docs**

```powershell
git add README.md
git commit -m "Document local bridge server"
```

---

### Task 6: Real WeChat Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Start the server in one terminal**

Run:

```powershell
python -m my_wxauto --bridge-server --bridge-host 127.0.0.1 --bridge-port 8765 --store-path .my_wxauto_bridge_server.sqlite3 --listen-resolve-senders profile_card --listen-sender-limit 5
```

Expected: terminal prints:

```text
my-wxauto bridge server listening on http://127.0.0.1:8765
```

- [ ] **Step 2: Check health**

Run in a second terminal:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/health"
```

Expected: JSON-like object with `status = ok`, `listener_alive = True`, and `store_path = .my_wxauto_bridge_server.sqlite3`.

- [ ] **Step 3: Trigger a WeChat message**

Use another WeChat account to send one message to the logged-in account.

- [ ] **Step 4: Fetch events**

Run:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/events?timeout=30&limit=5"
```

Expected: response contains one event with the new message in `events[0].messages`.

- [ ] **Step 5: Send a reply through the bridge**

Run:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/send" -Method Post -ContentType "application/json; charset=utf-8" -Body '{"who":"张勋","message":"桥接服务测试"}'
```

Expected: response has `status = success` or an existing `WxResponse` failure payload if WeChat UI fails.

- [ ] **Step 6: Confirm no self echo**

Fetch events again:

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/events?timeout=5&limit=5"
```

Expected: the sent reply does not appear as a fresh inbound event.
