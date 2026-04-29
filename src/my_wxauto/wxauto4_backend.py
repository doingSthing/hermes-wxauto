from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Wxauto4CallResult:
    ok: bool
    value: Any = None
    error: Exception | None = None


class Wxauto4Backend:
    def __init__(
        self,
        trace: Callable[..., None] | None = None,
        before_construct: Callable[[], None] | None = None,
        **wechat_kwargs: Any,
    ) -> None:
        self.wechat_kwargs = {"ads": False, "resize": False, **wechat_kwargs}
        self._wx: Any | None = None
        self.trace = trace or (lambda _label, **_extra: None)
        self.before_construct = before_construct or (lambda: None)

    @property
    def available(self) -> bool:
        try:
            self._wechat_class()
            return True
        except Exception:
            return False

    def chat_with(
        self,
        who: str,
        *,
        exact: bool = True,
        force: bool = False,
        force_wait: float | int = 0.5,
    ) -> Wxauto4CallResult:
        try:
            result = self.wx.ChatWith(
                who,
                exact=exact,
                force=force,
                force_wait=force_wait,
            )
            return Wxauto4CallResult(ok=True, value=result)
        except Exception as exc:
            return Wxauto4CallResult(ok=False, error=exc)

    def prepare_window(self) -> Wxauto4CallResult:
        try:
            self.trace("wxauto4.prepare.enter")
            self.trace("wxauto4.prepare.before_wx")
            self.wx
            self.trace("wxauto4.prepare.after_wx")
            return Wxauto4CallResult(ok=True, value="init")
        except Exception as exc:
            return Wxauto4CallResult(ok=False, error=exc)

    def send_msg(
        self,
        msg: str,
        who: str,
        *,
        exact: bool = True,
        force: bool = False,
        force_wait: float | int = 0.5,
    ) -> Wxauto4CallResult:
        try:
            result = self.wx.SendMsg(
                msg,
                who,
                exact=exact,
            )
            return Wxauto4CallResult(ok=True, value=result)
        except TypeError:
            try:
                result = self.wx.SendMsg(msg, who)
                return Wxauto4CallResult(ok=True, value=result)
            except Exception as exc:
                return Wxauto4CallResult(ok=False, error=exc)
        except Exception as exc:
            return Wxauto4CallResult(ok=False, error=exc)

    @property
    def wx(self) -> Any:
        if self._wx is None:
            self.trace("wxauto4.wx.before_import")
            wechat_class = self._wechat_class()
            self.trace("wxauto4.wx.after_import")
            self.trace("wxauto4.wx.before_construct", kwargs=self.wechat_kwargs)
            self.before_construct()
            self.trace("wxauto4.wx.after_before_construct")
            self._wx = wechat_class(**self.wechat_kwargs)
            self.trace("wxauto4.wx.after_construct")
        return self._wx

    def _wechat_class(self) -> Any:
        from wxauto4 import WeChat as Wxauto4WeChat

        return Wxauto4WeChat
