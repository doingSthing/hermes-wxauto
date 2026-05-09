from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from my_wxauto import probes
from my_wxauto import cli
from my_wxauto.response import WxResponse


def test_root_compat_package_exports_bridge_types_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from my_wxauto import BridgeMessage, ConversationBatch; "
            "print(BridgeMessage.__name__, ConversationBatch.__name__)",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "BridgeMessage ConversationBatch\n"


class FakeWeChat:
    instances: list["FakeWeChat"] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        FakeWeChat.instances.append(self)

    def ChatWith(self, who: str) -> WxResponse:
        self.calls.append(("ChatWith", (who,)))
        return WxResponse.success("opened", {"who": who})

    def SendMsg(self, msg: str, who: str) -> WxResponse:
        self.calls.append(("SendMsg", (msg, who)))
        return WxResponse.success("sent", {"who": who, "message": msg})


def test_main_runs_wakeup_probe(monkeypatch, capsys) -> None:
    calls: list[dict[str, object]] = []

    def fake_watch_unread_wakeup(**kwargs: object) -> None:
        calls.append(kwargs)
        print("wakeup probe")

    monkeypatch.setattr(probes, "watch_unread_wakeup", fake_watch_unread_wakeup)

    exit_code = cli.main(
        [
            "--watch-wakeup",
            "10",
            "--probe-interval",
            "0.2",
            "--probe-max-controls",
            "12",
            "--wakeup-burst-changes",
            "3",
            "--wakeup-burst-window",
            "2",
            "--wakeup-cooldown",
            "4",
            "--wakeup-action-timeout",
            "9",
            "--wakeup-max-probes",
            "2",
            "--wakeup-open-unread",
        ]
    )

    assert exit_code == 0
    assert calls == [
        {
            "seconds": 10.0,
            "interval": 0.2,
            "max_controls": 12,
            "min_changes": 3,
            "window_seconds": 2.0,
            "cooldown_seconds": 4.0,
            "action_timeout": 9.0,
            "max_probes": 2,
            "open_unread_messages": True,
        }
    ]
    assert capsys.readouterr().out == "wakeup probe\n"


def test_main_opens_chat_without_message(monkeypatch, capsys) -> None:
    FakeWeChat.instances.clear()
    monkeypatch.setattr(cli, "WeChat", FakeWeChat)

    exit_code = cli.main(["张三"])

    assert exit_code == 0
    assert FakeWeChat.instances[0].calls == [("ChatWith", ("张三",))]
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"
    assert output["data"]["who"] == "张三"


def test_main_sends_message_when_message_argument_is_present(monkeypatch, capsys) -> None:
    FakeWeChat.instances.clear()
    monkeypatch.setattr(cli, "WeChat", FakeWeChat)

    exit_code = cli.main(["张三", "--message", "你好"])

    assert exit_code == 0
    assert FakeWeChat.instances[0].calls == [("SendMsg", ("你好", "张三"))]
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "success"
    assert output["data"]["message"] == "你好"


def test_main_writes_utf8_output_file(monkeypatch, capsys, tmp_path) -> None:
    FakeWeChat.instances.clear()
    monkeypatch.setattr(cli, "WeChat", FakeWeChat)
    output_path = tmp_path / "probe-output.txt"

    exit_code = cli.main(["张三", "--output", str(output_path)])

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["status"] == "success"
    assert output["data"]["who"] == "张三"
