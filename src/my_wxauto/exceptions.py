class WxAutoError(RuntimeError):
    """Base error raised by my_wxauto."""


class WeChatWindowNotFoundError(WxAutoError):
    """Raised when a WeChat main window cannot be found."""


class WindowActivationError(WxAutoError):
    """Raised when a candidate WeChat window cannot be activated."""


class ClipboardError(WxAutoError):
    """Raised when Windows clipboard operations fail."""
