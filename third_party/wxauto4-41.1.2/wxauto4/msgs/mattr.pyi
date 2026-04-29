from .base import BaseMessage as BaseMessage, HumanMessage as HumanMessage, OcrResult as OcrResult
from typing import Any
from wxauto4 import uia as uia
from wxauto4.logger import wxlog as wxlog
from wxauto4.param import PROJECT_NAME as PROJECT_NAME, WxParam as WxParam, WxResponse as WxResponse
from wxauto4.ui.chatbox import ChatBox as ChatBox
from wxauto4.ui.component import ProfileWnd as ProfileWnd
from wxauto4.utils import uilock as uilock

class SystemMessage(BaseMessage):
    attr: str
    sender: str
    sender_remark: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class FriendMessage(HumanMessage):
    attr: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    @uilock
    def sender_info(self) -> dict: 
        """获取发送人信息
        
        Returns:
            Dict: 发送人信息
        """

class SelfMessage(HumanMessage):
    attr: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
