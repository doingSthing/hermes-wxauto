from .base import BaseMessage as BaseMessage, HumanMessage as HumanMessage
from pathlib import Path
from typing import Any
from wxauto4 import uia as uia
from wxauto4.exceptions import WxautoNoteLoadTimeoutError as WxautoNoteLoadTimeoutError
from wxauto4.param import PROJECT_NAME as PROJECT_NAME, WxParam as WxParam, WxResponse as WxResponse
from wxauto4.ui.chatbox import ChatBox as ChatBox
from wxauto4.ui.component import Menu as Menu, WeChatImage as WeChatImage
from wxauto4.utils.lock import uilock as uilock
from wxauto4.utils.tools import get_file_dir as get_file_dir
from wxauto4.utils.win32 import ReadClipboardData as ReadClipboardData, SetClipboardText as SetClipboardText

class TextMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class QuoteMessage(BaseMessage):
    type: str
    repattern: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class VoiceMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    @uilock
    def to_text(self) -> str: """获取语音转文字内容"""

class ImageMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    @uilock
    def download(self): """下载图片"""

class VideoMessage(BaseMessage):
    type: str
    repattern: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    @uilock
    def download(self): """下载视频"""

class FileMessage(BaseMessage):
    type: str
    repattern: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    @uilock
    def download(self, dir_path: str | Path = None, force_click: bool = False, timeout: int = 30) -> Path: 
        """下载文件
        
        Args:
            dir_path (str | Path, optional): 保存路径. Defaults to None.
            force_click (bool, optional): 强制点击（已弃用该参数）
            timeout (int, optional): 超时时间. Defaults to 30.
        """

class LocationMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class LinkMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class EmotionMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class MergeMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class PersonalCardMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...

class NoteMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
    @uilock
    def get_content(self, wait: int = 0) -> list[str]: 
        """获取笔记内容

        Args:
            wait (int, optional): 笔记加载等待时间. Defaults to 3.
        
        Returns:
            List[str]: 笔记内容
        """
    @uilock
    def save_files(self, dir_path: str | Path = None, wait: int = 3): 
        """保存笔记中的文件
        
        Args:
            dir_path (Union[str, Path], optional): 保存路径. Defaults to None.
            wait (int, optional): 等待笔记加载时间. Defaults to 3.
        Returns:
            WxResponse: 保存结果
        """
    @uilock
    def to_markdown(self, dir_path: str | Path = None, wait: int = 3) -> Path: 
        """将笔记转换为Markdown格式并保存
        
        Args:
            dir_path (Union[str, Path], optional): 保存路径. Defaults to None.
            wait (int, optional): 等待笔记加载时间. Defaults to 3.
        Returns:
            Path: 保存路径
        """

class OtherMessage(BaseMessage):
    type: str
    def __init__(self, control: uia.Control, parent: ChatBox) -> None: ...
