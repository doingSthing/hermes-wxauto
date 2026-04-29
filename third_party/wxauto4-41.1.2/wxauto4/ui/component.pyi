from wxauto4.exceptions import *
from .base import BaseUISubWnd as BaseUISubWnd
from _typeshed import Incomplete
from pathlib import Path
from typing import Literal
from wxauto4 import uia as uia
from wxauto4.logger import wxlog as wxlog
from wxauto4.ocr import WeChatOCR as WeChatOCR
from wxauto4.param import WxParam as WxParam, WxResponse as WxResponse
from wxauto4.utils.tools import find_all_windows_from_root as find_all_windows_from_root, find_window_from_root as find_window_from_root, get_file_dir as get_file_dir, is_valid_image as is_valid_image, now_time as now_time
from wxauto4.utils.win32 import FindWindow as FindWindow, GetAllWindows as GetAllWindows, ReadClipboardData as ReadClipboardData, SetClipboardText as SetClipboardText

wxocr: Incomplete

class UpdateWindow(BaseUISubWnd):
    control: Incomplete
    def __init__(self) -> None: ...
    def ignore(self) -> None: ...

class Menu(BaseUISubWnd):
    parent: Incomplete
    root: Incomplete
    control: Incomplete
    def __init__(self, parent, timeout: int = 2) -> None: ...
    @property
    def option_controls(self): ...
    @property
    def option_names(self): ...
    def select(self, item): ...

class SelectContactWnd(BaseUISubWnd):
    parent: Incomplete
    root: Incomplete
    control: Incomplete
    confirm_btn: Incomplete
    confirm_btn_rect: Incomplete
    def __init__(self, parent, timeout: int = 2) -> None: ...
    def search(self, keyword, interval: float = 0.1): ...
    def add_message(self, content): ...
    def confirm(self) -> None: ...
    def send(self, target, message: Incomplete | None = None, interval: float = 0.1) -> None: ...

class SearchNewFriendWnd(BaseUISubWnd):
    control: Incomplete
    def __init__(self) -> None: ...
    apply_btn: Incomplete
    search_edit: Incomplete
    search_btn: Incomplete
    def init(self) -> None: ...
    def search(self, keyword) -> None: ...
    def apply(self): ...

class WeChatImage(BaseUISubWnd):
    parent: Incomplete
    root: Incomplete
    control: Incomplete
    def __init__(self, parent) -> None: ...
    tools: Incomplete
    type: str
    def init(self) -> None: ...
    def load_original(self): """加载原图/视频"""
        
    def save(self, dir_path: Incomplete | None = None, timeout: int = 10, original: bool = False) -> Path: 
        """保存图片/视频

        Args:
            dir_path (str): 保存文件夹路径
            timeout (int, optional): 保存超时时间，默认10秒
            original (bool, optional): 是否保存原图/视频，默认False
        
        Returns:
            Path: 文件保存路径，即savepath
        """

class ProfileWnd(BaseUISubWnd):
    control: Incomplete
    def __init__(self) -> None: ...
    topui: Incomplete
    midui: Incomplete
    bottomui: Incomplete
    more_btn: Incomplete
    def init(self) -> None: ...
    @property
    def info(self): ...

class WeChatDialog(BaseUISubWnd):
    root: Incomplete
    def __init__(self, parent, wait: int = 3) -> None: ...
    @property
    def control(self): ...
    def get_all_text(self): ...
    def click_button(self, text: str, move: bool = True): ...

