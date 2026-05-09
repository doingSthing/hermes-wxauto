from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "my_wxauto"
if _SRC_PACKAGE.exists():
    __path__.append(str(_SRC_PACKAGE))

from .response import WxResponse
from .wechat import WeChat
from .bridge_events import BridgeMessage, ConversationBatch
from .listener import ChatMessage, ListenerStats, NewMessageEvent

__all__ = [
    "WeChat",
    "WxResponse",
    "BridgeMessage",
    "ConversationBatch",
    "ChatMessage",
    "ListenerStats",
    "NewMessageEvent",
]
