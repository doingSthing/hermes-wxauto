import abc
from _typeshed import Incomplete
from abc import ABC
from typing import Any
from wxauto4 import uia as uia
from wxauto4.ocr import OcrResult as OcrResult, WeChatOCR as WeChatOCR
from wxauto4.param import PROJECT_NAME as PROJECT_NAME, WxParam as WxParam, WxResponse as WxResponse
from wxauto4.ui.chatbox import ChatBox as ChatBox
from wxauto4.ui.component import Menu as Menu, SelectContactWnd as SelectContactWnd
from wxauto4.utils import uilock as uilock

def truncate_string(s: str, n: int = 8) -> str: ...

class Message: ...

class BaseMessage(Message, ABC):
    type: str
    attr: str
    control: uia.Control
    parent: Incomplete
    ocr: Incomplete
    direction: Incomplete
    distince: Incomplete
    root: Incomplete
    id: Incomplete
    content: Incomplete
    hash_text: Incomplete
    hash: Incomplete
    chat_info: Incomplete
    sender: Incomplete
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    def roll_into_view(self): ...
    def exists(self): ...

class HumanMessage(BaseMessage, ABC, metaclass=abc.ABCMeta):
    attr: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    def click_head(self, right: bool = False) -> None: ...
    def click(self) -> None: ...
    def right_click(self) -> None: ...
    @uilock
    def tickle(self): ...
    @uilock
    def select_option(self, option: str, timeout: int = 2) -> WxResponse: ...
    @uilock
    def forward(self, targets: list[str] | str, message: str = None, timeout: int = 3, interval: float = 0.1) -> WxResponse: 
        """转发消息

        Args:
            targets (Union[List[str], str]): 目标用户列表
            message (str)：要附加的消息
            timeout (int, optional): 超时时间，单位为秒，若为None则不启用超时设置
            interval (float): 选择联系人时间间隔

        Returns:
            WxResponse: 调用结果
        """
    @uilock
    def quote(self, text: str, at: list[str] | str = None, timeout: int = 3) -> WxResponse: 
        """引用消息
        
        Args:
            text (str): 引用内容
            at (List[str], optional): @用户列表
            timeout (int, optional): 超时时间，单位为秒，若为None则不启用超时设置

        Returns:
            WxResponse: 调用结果
        """

class NotExistsMessage: ...
