import abc
from .utils import GetAllWindows as GetAllWindows, uilock as uilock
from _typeshed import Incomplete
from abc import ABC
from typing import Callable, Literal, Union
from wxautox.msgs.base import Message as Message
from wxautox.ui.sessionbox import SessionElement as SessionElement
from wxauto4.logger import wxlog as wxlog
from wxauto4.param import PROJECT_NAME as PROJECT_NAME, WxParam as WxParam, WxResponse as WxResponse
from wxauto4.ui import WeChatMainWnd as WeChatMainWnd, WeChatSubWnd as WeChatSubWnd
from wxauto4.ui.base import BaseUISubWnd as BaseUISubWnd, BaseUIWnd as BaseUIWnd
from wxauto4.ui.moment import PrivacyConfig as PrivacyConfig

class Listener(ABC, metaclass=abc.ABCMeta): ...

class Chat:
    who: Incomplete
    def __init__(self, core: WeChatSubWnd = None) -> None: ...
    def __add__(self, other): ...
    def __radd__(self, other): ...
    def Show(self) -> None: ...
    def ChatInfo(self) -> dict[str, str]: ...
    @uilock
    def SendMsg(self, msg: str, who: str = None, clear: bool = True, at: str | list[str] = None, exact: bool = False) -> WxResponse: 
        """发送消息

        Args:
            msg (str): 消息内容
            who (str, optional): 发送对象，不指定则发送给当前聊天对象，**当子窗口时，该参数无效**
            clear (bool, optional): 发送后是否清空编辑框.
            at (Union[str, List[str]], optional): @对象，不指定则不@任何人
            exact (bool, optional): 搜索who好友时是否精确匹配，默认False，**当子窗口时，该参数无效**

        Returns:
            WxResponse: 是否发送成功
        """
    @uilock
    def SendFiles(self, filepath, who: Incomplete | None = None, exact: bool = False) -> WxResponse: 
        """向当前聊天窗口发送文件
        
        Args:
            filepath (str|list): 要复制文件的绝对路径  
            who (str): 发送对象，不指定则发送给当前聊天对象，**当子窗口时，该参数无效**
            exact (bool, optional): 搜索who好友时是否精确匹配，默认False，**当子窗口时，该参数无效**
            
        Returns:
            WxResponse: 是否发送成功
        """
    def GetAllMessage(self) -> list['Message']: 
        """获取当前聊天窗口的所有消息
        
        Returns:
            List[Message]: 当前聊天窗口的所有消息
        """
    def Close(self) -> None: """关闭微信窗口"""

class WeChat(Chat, Listener):
    NavigationBox: Incomplete
    SessionBox: Incomplete
    ChatBox: Incomplete
    myinfo: Incomplete
    nickname: Incomplete
    listen: Incomplete
    def __init__(self, debug: bool = False, resize: bool=True, **kwargs) -> None: 
        """实例化入口

        Args:
            debug (bool, optional): 是否开启debug日志输出. Defaults to False.
            resize (bool, optional): 是否自动设定窗口尺寸. Defaults to True.
        """
    @property
    def path(self): ...
    @property
    def dir(self): ...
    def GetMyInfo(self) -> dict[str, str]: """获取我的信息"""
    def KeepRunning(self) -> None: """保持运行"""
    def IsOnline(self) -> bool: """判断是否在线"""
    def GetSession(self) -> list['SessionElement']: 
        """获取当前会话列表

        Returns:
            List[SessionElement]: 当前会话列表
        """
    @uilock
    def ChatWith(self, who: str, exact: bool = True, force: bool = False, force_wait: float | int = 0.5): 
        """打开聊天窗口
        
        Args:
            who (str): 要聊天的对象
            exact (bool, optional): 搜索who好友时是否精确匹配，默认True
            force (bool, optional): 不论是否匹配到都强制切换，若启用则exact参数无效，默认False
                > 注：force原理为输入搜索关键字后，在等待`force_wait`秒后不判断结果直接回车，谨慎使用
            force_wait (Union[float, int], optional): 强制切换时等待时间，默认0.5秒
            
        """

    def SwitchToChat(self) -> None: """切换到聊天页面"""
    def SwitchToContact(self) -> None: """切换到联系人页面"""
    def ShutDown(self) -> None: """杀掉微信进程"""
