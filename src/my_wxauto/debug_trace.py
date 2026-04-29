from __future__ import annotations

import json
import time
from typing import Any


def make_ui_tracer(enabled: bool):
    def trace(label: str, **extra: Any) -> None:
        if not enabled:
            return
        payload: dict[str, Any] = {
            "t": round(time.perf_counter(), 3),
            "label": label,
            "snapshot": _ui_snapshot(),
        }
        if extra:
            payload["extra"] = _json_safe(extra)
        print("MY_WXAUTO_TRACE " + json.dumps(payload, ensure_ascii=False), flush=True)

    return trace


def _ui_snapshot() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        import psutil
        import win32gui
        import win32process

        cursor = win32gui.GetCursorPos()
        data["cursor"] = [cursor[0], cursor[1]]

        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            process_name = ""
            try:
                process_name = psutil.Process(pid).name()
            except Exception:
                pass
            data["foreground"] = {
                "hwnd": hwnd,
                "title": win32gui.GetWindowText(hwnd),
                "class_name": win32gui.GetClassName(hwnd),
                "rect": list(win32gui.GetWindowRect(hwnd)),
                "pid": pid,
                "process_name": process_name,
            }

        data["under_cursor_window"] = _window_from_point(cursor[0], cursor[1])
    except Exception as exc:
        data["snapshot_error"] = repr(exc)
    return data


def _window_from_point(x: int, y: int) -> dict[str, Any] | None:
    try:
        import psutil
        import win32gui
        import win32process

        hwnd = win32gui.WindowFromPoint((x, y))
        if not hwnd:
            return None
        root = win32gui.GetAncestor(hwnd, 2) or hwnd
        _, pid = win32process.GetWindowThreadProcessId(root)
        process_name = ""
        try:
            process_name = psutil.Process(pid).name()
        except Exception:
            pass
        return {
            "hwnd": hwnd,
            "root_hwnd": root,
            "title": win32gui.GetWindowText(root),
            "class_name": win32gui.GetClassName(root),
            "rect": list(win32gui.GetWindowRect(root)),
            "pid": pid,
            "process_name": process_name,
        }
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_json_safe(v) for v in value]
        return repr(value)
