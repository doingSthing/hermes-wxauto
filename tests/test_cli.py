from __future__ import annotations

import json

from my_wxauto import cli
from my_wxauto.response import WxResponse


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
