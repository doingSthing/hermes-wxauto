from wxauto4 import uia
from wxauto4.param import PROJECT_NAME, WxParam
from wxauto4.logger import wxlog
from wxauto4.utils.lock import uilock
from wxauto4.utils.win32 import get_monitor_info
from abc import ABC, abstractmethod
import win32gui
from typing import Union
import time

class BaseUIWnd(ABC):
    _ui_cls_name: str = None
    _ui_name: str = None
    control: uia.Control

    @abstractmethod
    def _lang(self, text: str):pass

    def __repr__(self):
        return f"<{PROJECT_NAME} - {self.__class__.__name__} at {hex(id(self))}>"
    
    def __eq__(self, other):
        return self.control == other.control
    
    def __bool__(self):
        return self.exists()

    def _show(self):
        if hasattr(self, 'HWND'):
            win32gui.ShowWindow(self.HWND, 1)
        #     win32gui.SetWindowPos(self.HWND, -1, 0, 0, 0, 0, 3)
        #     win32gui.SetWindowPos(self.HWND, -2, 0, 0, 0, 0, 3)
        self.control.SwitchToThisWindow()

    @property
    def pid(self):
        return self.control.ProcessId

    @uilock
    def close(self):
        try:
            self.control.SendKeys('{Esc}')
        except:
            pass

    def exists(self, wait=0):
        try:
            result = self.control.Exists(wait)
            return result
        except:
            return False
        
    def auto_resize(self):
        try:
            # 获取显示器信息，判断显示器尺寸最高的那个，将子窗口放到该显示器，以加载更多消息
            monitors = get_monitor_info()
            xy = max(monitors, key=lambda x: x['Height'])['Position']
        except:
            xy = (0, 0)
        self.set_window_size(*WxParam.CHAT_WINDOW_SIZE, xy)
    
    def set_window_size(self, width, height, location: tuple=None):
        # win32gui.SetWindowPos(hwnd, 0, 0, 0, width, height, win32con.SWP_NOZORDER | win32con.SWP_NOMOVE)
        if not hasattr(self, 'HWND'):
            self.HWND =  self.control.NativeWindowHandle
        if location:
            x, y = location
            uia.win32gui.MoveWindow(self.HWND, x, y, width, height, True)
        else:
            uia.win32gui.SetWindowPos(self.HWND, 0, 0, 0, width, height, 6)

class BaseUISubWnd(BaseUIWnd):
    root: BaseUIWnd
    parent: None

    def _lang(self, text: str):
        if getattr(self, 'parent'):
            return self.parent._lang(text)
        else:
            return self.root._lang(text)


