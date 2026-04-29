from __future__ import annotations

import ctypes
import os
import logging
import platform
import subprocess
import time
from dataclasses import dataclass, replace
from typing import Sequence

import psutil

from .exceptions import WeChatWindowNotFoundError, WindowActivationError
from .tray import TrayIconRestorer

LOGGER = logging.getLogger(__name__)

DEFAULT_PROCESS_NAMES = (
    "wechat.exe",
    "weixin.exe",
    "wechatapp.exe",
    "wechatappex.exe",
)
MAIN_PROCESS_NAMES = ("wechat.exe", "weixin.exe")
DEFAULT_TITLE_KEYWORDS = ("微信", "WeChat")
DEFAULT_CLASS_KEYWORDS = ("WeChat", "Weixin", "Qt")


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height


@dataclass(frozen=True)
class WeChatWindow:
    hwnd: int
    title: str
    class_name: str
    pid: int
    process_name: str
    exe: str
    rect: WindowRect
    visible: bool = True
    minimized: bool = False
    recovered_from_process: bool = False
    recovered_from_tray: bool = False

    @property
    def center(self) -> tuple[int, int]:
        return (
            self.rect.left + self.rect.width // 2,
            self.rect.top + self.rect.height // 2,
        )

    def point(self, offset: tuple[int, int]) -> tuple[int, int]:
        return self.rect.left + offset[0], self.rect.top + offset[1]


class WeChatWindowController:
    def __init__(
        self,
        process_names: Sequence[str] = DEFAULT_PROCESS_NAMES,
        title_keywords: Sequence[str] = DEFAULT_TITLE_KEYWORDS,
        class_keywords: Sequence[str] = DEFAULT_CLASS_KEYWORDS,
        min_size: tuple[int, int] = (360, 300),
        tray_restorer: TrayIconRestorer | None = None,
        prefer_tray_restore: bool = True,
    ) -> None:
        self.process_names = tuple(name.lower() for name in process_names)
        self.title_keywords = tuple(title_keywords)
        self.class_keywords = tuple(class_keywords)
        self.min_size = min_size
        self.tray_restorer = tray_restorer or TrayIconRestorer()
        self.prefer_tray_restore = prefer_tray_restore
        self._configure_dpi_awareness()

    def find_main_window(self, reveal: bool = True) -> WeChatWindow:
        candidates = self.list_candidate_windows()
        recovered_from_process = False
        recovered_from_tray = False
        if not candidates and reveal:
            if self.reveal_from_tray():
                recovered_from_tray = True
                candidates = self._wait_for_candidate_windows(
                    timeout=5.0,
                    settle_after_first=0.5,
                )
            if not candidates and self.reveal_from_running_processes():
                recovered_from_process = True
                candidates = self._wait_for_candidate_windows(
                    timeout=5.0,
                    settle_after_first=1.5,
                )
        if not candidates:
            raise WeChatWindowNotFoundError(
                "No WeChat main window was found. Open WeChat once, or run with --diagnose to inspect detected processes/windows."
            )
        window = max(candidates, key=self._score_window)
        if recovered_from_process:
            window = replace(window, recovered_from_process=True)
        if recovered_from_tray:
            window = replace(window, recovered_from_tray=True)
        return window

    def list_candidate_windows(self) -> list[WeChatWindow]:
        self._ensure_windows()
        import win32gui
        import win32process

        windows: list[WeChatWindow] = []

        def callback(hwnd: int, _extra: object) -> bool:
            rect_tuple = win32gui.GetWindowRect(hwnd)
            rect = WindowRect(*rect_tuple)
            visible = bool(win32gui.IsWindowVisible(hwnd))
            minimized = bool(win32gui.IsIconic(hwnd))
            title = win32gui.GetWindowText(hwnd) or ""
            class_name = win32gui.GetClassName(hwnd) or ""
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name, exe = self._process_info(pid)

            candidate = WeChatWindow(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                pid=pid,
                process_name=proc_name,
                exe=exe,
                rect=rect,
                visible=visible,
                minimized=minimized,
            )
            if self._looks_like_wechat(candidate):
                windows.append(candidate)
            return True

        try:
            win32gui.EnumWindows(callback, None)
        except Exception as exc:
            windows.append({"error": str(exc)})
        return windows

    def get_window(self, hwnd: int) -> WeChatWindow | None:
        self._ensure_windows()
        import win32gui
        import win32process

        if not win32gui.IsWindow(hwnd):
            return None

        rect = WindowRect(*win32gui.GetWindowRect(hwnd))
        title = win32gui.GetWindowText(hwnd) or ""
        class_name = win32gui.GetClassName(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc_name, exe = self._process_info(pid)
        return WeChatWindow(
            hwnd=hwnd,
            title=title,
            class_name=class_name,
            pid=pid,
            process_name=proc_name,
            exe=exe,
            rect=rect,
            visible=bool(win32gui.IsWindowVisible(hwnd)),
            minimized=bool(win32gui.IsIconic(hwnd)),
        )

    def activate(self, window: WeChatWindow, wait: float = 0.35) -> WeChatWindow:
        self._ensure_windows()
        import win32con
        import win32gui

        try:
            if self.prefer_tray_restore and (window.minimized or not window.visible):
                tray_window = self._restore_window_from_tray()
                if tray_window is not None:
                    return tray_window
            if win32gui.IsIconic(window.hwnd):
                win32gui.ShowWindow(window.hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(window.hwnd, win32con.SW_SHOWNORMAL)
                win32gui.ShowWindow(window.hwnd, win32con.SW_SHOW)
            self._force_foreground(window.hwnd)
            time.sleep(wait)
            refreshed = self.get_window(window.hwnd) or window
            if window.recovered_from_process and not refreshed.recovered_from_process:
                refreshed = replace(refreshed, recovered_from_process=True)
            if window.recovered_from_tray and not refreshed.recovered_from_tray:
                refreshed = replace(refreshed, recovered_from_tray=True)
            return refreshed
        except Exception as exc:
            raise WindowActivationError(f"Failed to activate WeChat window: {exc}") from exc

    def wait_until_ready(
        self,
        window: WeChatWindow,
        *,
        timeout: float = 5.0,
        stable_for: float = 0.5,
        min_wait: float = 0.0,
    ) -> WeChatWindow:
        if min_wait > 0:
            time.sleep(min_wait)

        deadline = time.monotonic() + timeout
        latest = self.get_window(window.hwnd) or window
        last_signature: tuple[object, ...] | None = None
        stable_since: float | None = None

        while time.monotonic() < deadline:
            current = self.get_window(window.hwnd)
            if current is None:
                candidates = self.list_candidate_windows()
                current = max(candidates, key=self._score_window) if candidates else None
            if current is None:
                time.sleep(0.15)
                continue

            if window.recovered_from_process and not current.recovered_from_process:
                current = replace(current, recovered_from_process=True)
            if window.recovered_from_tray and not current.recovered_from_tray:
                current = replace(current, recovered_from_tray=True)
            latest = current
            if not self._is_ready_window(current):
                last_signature = None
                stable_since = None
                time.sleep(0.15)
                continue

            signature = self._window_signature(current)
            now = time.monotonic()
            if signature != last_signature:
                last_signature = signature
                stable_since = now
            elif stable_since is not None and now - stable_since >= stable_for:
                return current
            time.sleep(0.15)

        return latest

    def reveal_from_running_processes(self) -> bool:
        revealed = False
        seen_exes: set[str] = set()
        for process in self.list_wechat_processes():
            name = str(process.get("name") or "").lower()
            exe = process.get("exe") or ""
            if name not in MAIN_PROCESS_NAMES:
                continue
            if not exe or not os.path.exists(exe) or exe in seen_exes:
                continue
            seen_exes.add(exe)
            try:
                subprocess.Popen(
                    [exe],
                    cwd=os.path.dirname(exe) or None,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                revealed = True
            except OSError:
                LOGGER.debug("Unable to reveal WeChat from %s", exe, exc_info=True)
        return revealed

    def reveal_from_tray(self) -> bool:
        return self.tray_restorer.restore_wechat()

    def list_wechat_processes(self) -> list[dict[str, object]]:
        processes: list[dict[str, object]] = []
        seen_pids: set[int] = set()
        for process in psutil.process_iter(["pid", "name", "exe"]):
            try:
                info = process.info
                pid = int(info.get("pid") or 0)
                name = str(info.get("name") or "")
                exe = str(info.get("exe") or "")
            except (psutil.Error, OSError, ValueError):
                continue

            lower_name = name.lower()
            lower_exe = exe.lower()
            if (
                lower_name in self.process_names
                or "wechat" in lower_exe
                or "weixin" in lower_exe
            ):
                if pid not in seen_pids:
                    seen_pids.add(pid)
                    processes.append({"pid": pid, "name": name, "exe": exe})
        return processes

    def diagnose(self) -> dict[str, object]:
        return {
            "processes": self.list_wechat_processes(),
            "process_windows": self.list_wechat_process_windows(),
            "tray_icons": [icon.__dict__ for icon in self.tray_restorer.list_icons()],
            "windows": [self._window_to_dict(window) for window in self.list_candidate_windows()],
        }

    def list_wechat_process_windows(self) -> list[dict[str, object]]:
        self._ensure_windows()
        import win32gui
        import win32process

        processes = self.list_wechat_processes()
        pid_to_process = {int(process["pid"]): process for process in processes}
        if not pid_to_process:
            return []

        windows: list[dict[str, object]] = []

        def callback(hwnd: int, _extra: object) -> bool:
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pid_to_process:
                    return True
                rect = WindowRect(*win32gui.GetWindowRect(hwnd))
                windows.append(
                    {
                        "hwnd": hwnd,
                        "pid": pid,
                        "process_name": pid_to_process[pid].get("name"),
                        "title": win32gui.GetWindowText(hwnd) or "",
                        "class_name": win32gui.GetClassName(hwnd) or "",
                        "visible": bool(win32gui.IsWindowVisible(hwnd)),
                        "minimized": bool(win32gui.IsIconic(hwnd)),
                        "rect": {
                            "left": rect.left,
                            "top": rect.top,
                            "right": rect.right,
                            "bottom": rect.bottom,
                            "width": rect.width,
                            "height": rect.height,
                        },
                    }
                )
            except Exception as exc:
                windows.append({"hwnd": hwnd, "error": str(exc)})
            return True

        win32gui.EnumWindows(callback, None)
        return windows

    def _looks_like_wechat(self, window: WeChatWindow) -> bool:
        proc_name = window.process_name.lower()
        process_match = proc_name in self.process_names
        title_match = any(keyword in window.title for keyword in self.title_keywords)
        class_match = any(keyword in window.class_name for keyword in self.class_keywords)
        exe_match = "wechat" in window.exe.lower() or "weixin" in window.exe.lower()
        plausible_main_window = (
            window.visible
            and window.rect.width >= self.min_size[0]
            and window.rect.height >= self.min_size[1]
        )
        return (process_match or exe_match) and (title_match or class_match or plausible_main_window)

    def _is_ready_window(self, window: WeChatWindow) -> bool:
        return (
            window.visible
            and not window.minimized
            and window.rect.width >= self.min_size[0]
            and window.rect.height >= self.min_size[1]
            and window.rect.left > -10000
            and window.rect.top > -10000
        )

    def _window_signature(self, window: WeChatWindow) -> tuple[object, ...]:
        return (
            window.hwnd,
            window.title,
            window.class_name,
            window.visible,
            window.minimized,
            window.rect.left,
            window.rect.top,
            window.rect.right,
            window.rect.bottom,
        )

    def _score_window(self, window: WeChatWindow) -> tuple[int, int, int]:
        title_score = 0
        if window.title in self.title_keywords:
            title_score += 20
        elif any(keyword in window.title for keyword in self.title_keywords):
            title_score += 10

        class_score = 5 if any(keyword in window.class_name for keyword in self.class_keywords) else 0
        state_score = 0
        if window.visible:
            state_score += 20
        if not window.minimized:
            state_score += 10
        normal_size = window.rect.width >= self.min_size[0] and window.rect.height >= self.min_size[1]
        if normal_size:
            state_score += 5
        area = max(0, window.rect.width) * max(0, window.rect.height)
        return title_score + class_score + state_score, area, window.hwnd

    def _window_to_dict(self, window: WeChatWindow) -> dict[str, object]:
        return {
            "hwnd": window.hwnd,
            "title": window.title,
            "class_name": window.class_name,
            "pid": window.pid,
            "process_name": window.process_name,
            "exe": window.exe,
            "visible": window.visible,
            "minimized": window.minimized,
            "recovered_from_process": window.recovered_from_process,
            "recovered_from_tray": window.recovered_from_tray,
            "rect": {
                "left": window.rect.left,
                "top": window.rect.top,
                "right": window.rect.right,
                "bottom": window.rect.bottom,
                "width": window.rect.width,
                "height": window.rect.height,
            },
        }

    def _process_info(self, pid: int) -> tuple[str, str]:
        try:
            process = psutil.Process(pid)
            return process.name() or "", process.exe() or ""
        except (psutil.Error, OSError):
            return "", ""

    def _wait_for_candidate_windows(
        self,
        *,
        timeout: float,
        settle_after_first: float,
    ) -> list[WeChatWindow]:
        deadline = time.monotonic() + timeout
        first_seen_at: float | None = None
        latest_candidates: list[WeChatWindow] = []

        while time.monotonic() < deadline:
            candidates = self.list_candidate_windows()
            if candidates:
                latest_candidates = candidates
                if first_seen_at is None:
                    first_seen_at = time.monotonic()
                if time.monotonic() - first_seen_at >= settle_after_first:
                    return latest_candidates
            else:
                first_seen_at = None
                latest_candidates = []
            time.sleep(0.25)

        return latest_candidates

    def _restore_window_from_tray(self) -> WeChatWindow | None:
        if not self.reveal_from_tray():
            return None
        candidates = self._wait_for_candidate_windows(timeout=5.0, settle_after_first=0.5)
        if not candidates:
            return None
        return replace(max(candidates, key=self._score_window), recovered_from_tray=True)

    def _force_foreground(self, hwnd: int) -> None:
        import win32con
        import win32gui

        foreground = win32gui.GetForegroundWindow()
        if foreground == hwnd:
            return

        current_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        foreground_thread_id = ctypes.windll.user32.GetWindowThreadProcessId(foreground, 0)
        target_thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, 0)

        attached_threads: list[int] = []
        for thread_id in (foreground_thread_id, target_thread_id):
            if thread_id and thread_id != current_thread_id:
                if ctypes.windll.user32.AttachThreadInput(current_thread_id, thread_id, True):
                    attached_threads.append(thread_id)

        try:
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOP,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
            win32gui.SetForegroundWindow(hwnd)
        finally:
            for thread_id in attached_threads:
                ctypes.windll.user32.AttachThreadInput(current_thread_id, thread_id, False)

    def _configure_dpi_awareness(self) -> None:
        if platform.system() != "Windows":
            return
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            LOGGER.debug("Unable to configure DPI awareness.", exc_info=True)

    def _ensure_windows(self) -> None:
        if platform.system() != "Windows":
            raise OSError("my_wxauto 目前只支持 Windows 微信客户端。")
