from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, Sequence

LOGGER = logging.getLogger(__name__)

DEFAULT_TRAY_ICON_KEYWORDS = ("微信", "WeChat", "Weixin")
DEFAULT_OVERFLOW_KEYWORDS = (
    "显示隐藏的图标",
    "显示隐藏图标",
    "Show hidden icons",
    "Hidden icons",
)


@dataclass(frozen=True)
class TrayIconInfo:
    name: str
    control_type: str
    rectangle: tuple[int, int, int, int]
    source: str


class TrayIconRestorer:
    def __init__(
        self,
        icon_keywords: Sequence[str] = DEFAULT_TRAY_ICON_KEYWORDS,
        overflow_keywords: Sequence[str] = DEFAULT_OVERFLOW_KEYWORDS,
    ) -> None:
        self.icon_keywords = tuple(icon_keywords)
        self.overflow_keywords = tuple(overflow_keywords)

    def restore_wechat(self) -> bool:
        try:
            if self._click_matching_taskbar_button():
                return True
            if self._double_click_matching_icon(include_overflow=False):
                return True
            if self._open_overflow():
                time.sleep(0.25)
                return self._double_click_matching_icon(include_overflow=True)
            return False
        except Exception:
            LOGGER.debug("Unable to restore WeChat from tray.", exc_info=True)
            return False

    def _click_matching_taskbar_button(self) -> bool:
        desktop = self._desktop()
        for _source, window in self._tray_windows(desktop, include_overflow=False):
            for control in self._matching_icon_controls(window):
                class_name = str(getattr(control.element_info, "class_name", "") or "")
                control_type = str(getattr(control.element_info, "control_type", "") or "")
                if "TaskListButton" not in class_name:
                    continue
                control.click_input()
                return True
        return False

    def list_icons(self) -> list[TrayIconInfo]:
        try:
            desktop = self._desktop()
        except Exception:
            LOGGER.debug("Unable to inspect tray icons.", exc_info=True)
            return []

        icons: list[TrayIconInfo] = []
        for source, window in self._tray_windows(desktop, include_overflow=True):
            for control in self._descendants(window):
                name = str(getattr(control.element_info, "name", "") or "").strip()
                if not name:
                    continue
                rect = control.rectangle()
                if rect.width() <= 0 or rect.height() <= 0:
                    continue
                icons.append(
                    TrayIconInfo(
                        name=name,
                        control_type=str(getattr(control.element_info, "control_type", "") or ""),
                        rectangle=(rect.left, rect.top, rect.right, rect.bottom),
                        source=source,
                    )
                )
        return icons

    def _double_click_matching_icon(self, *, include_overflow: bool) -> bool:
        desktop = self._desktop()
        for _source, window in self._tray_windows(desktop, include_overflow=include_overflow):
            for control in self._matching_icon_controls(window):
                control.double_click_input()
                return True
        return False

    def _open_overflow(self) -> bool:
        desktop = self._desktop()
        for _source, window in self._tray_windows(desktop, include_overflow=False):
            for control in self._descendants(window):
                name = str(getattr(control.element_info, "name", "") or "")
                if self._contains_any(name, self.overflow_keywords):
                    control.click_input()
                    return True
        return False

    def _matching_icon_controls(self, window: object) -> Iterable[object]:
        for control in self._descendants(window):
            name = str(getattr(control.element_info, "name", "") or "").strip()
            if not self._contains_any(name, self.icon_keywords):
                continue
            rect = control.rectangle()
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            yield control

    def _tray_windows(self, desktop: object, *, include_overflow: bool) -> Iterable[tuple[str, object]]:
        for class_name, source in (
            ("Shell_TrayWnd", "taskbar"),
            ("NotifyIconOverflowWindow", "overflow"),
        ):
            if source == "overflow" and not include_overflow:
                continue
            try:
                for window in desktop.windows(class_name=class_name):
                    yield source, window
            except Exception:
                LOGGER.debug("Unable to enumerate %s.", class_name, exc_info=True)

    def _descendants(self, window: object) -> list[object]:
        try:
            return window.descendants()
        except Exception:
            LOGGER.debug("Unable to enumerate tray descendants.", exc_info=True)
            return []

    def _contains_any(self, value: str, keywords: Sequence[str]) -> bool:
        folded = value.casefold()
        return any(keyword.casefold() in folded for keyword in keywords)

    def _desktop(self) -> object:
        from pywinauto import Desktop

        return Desktop(backend="uia")
