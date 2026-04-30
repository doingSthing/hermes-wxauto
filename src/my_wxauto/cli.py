from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path

from .wechat import SearchOptions, WeChat
from .window import WeChatWindowController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open a WeChat conversation or send a message.")
    parser.add_argument("who", nargs="?", help="contact, group, or session name")
    parser.add_argument("--message", help="要发送的文本消息；不传时仅打开聊天窗口")
    parser.add_argument("--diagnose", action="store_true", help="print detected WeChat processes/windows and exit")
    parser.add_argument("--watch-wakeup", type=float, default=0.0, metavar="SECONDS", help="observe taskbar/tray flashing, then restore WeChat and print unread sessions")
    parser.add_argument("--wakeup-burst-changes", type=int, default=4, help="changes required in the burst window for --watch-wakeup")
    parser.add_argument("--wakeup-burst-window", type=float, default=3.0, help="burst window seconds for --watch-wakeup")
    parser.add_argument("--wakeup-cooldown", type=float, default=5.0, help="cooldown seconds after --watch-wakeup fires")
    parser.add_argument("--wakeup-action-timeout", type=float, default=12.0, help="seconds allowed for restoring WeChat and reading sessions after wakeup")
    parser.add_argument("--wakeup-max-probes", type=int, default=1, help="maximum wakeup probes to run; use 0 for unlimited")
    parser.add_argument("--wakeup-open-unread", action="store_true", help="after wakeup, click the first unread session and dump right-side chat messages")
    parser.add_argument("--probe-listener-signals", action="store_true", help="输出监听信号探针：窗口、左侧会话 UIA 控件、小红点候选")
    parser.add_argument("--watch-signals", type=float, default=0.0, metavar="SECONDS", help="持续观察左侧会话区域信号变化，单位秒")
    parser.add_argument("--watch-events", type=float, default=0.0, metavar="SECONDS", help="持续监听 WeChat/Weixin 进程 WinEvent 变化，单位秒")
    parser.add_argument("--watch-taskbar", type=float, default=0.0, metavar="SECONDS", help="持续观察微信任务栏/托盘图标元数据与像素变化，单位秒")
    parser.add_argument("--probe-interval", type=float, default=0.5, help="--watch-signals 的采样间隔秒数")
    parser.add_argument("--probe-max-controls", type=int, default=160, help="探针最多输出的 UIA 控件数量")
    parser.add_argument("--probe-no-uia", action="store_true", help="探针不采集 UIA 控件")
    parser.add_argument("--probe-no-badges", action="store_true", help="探针不采集红色小红点候选")
    parser.add_argument("--probe-taskbar", action="store_true", help="探针额外采集任务栏/托盘微信图标信息")
    parser.add_argument("--probe-no-taskbar", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", help="将命令输出直接写入 UTF-8 文件，避免 PowerShell 管道乱码")
    parser.add_argument("--append-output", action="store_true", help="配合 --output 使用，追加写入输出文件")
    parser.add_argument("--use-wxauto4", dest="use_wxauto4", action="store_true", default=True, help="默认开启：使用 wxauto4 构造器恢复/置前微信窗口")
    parser.add_argument("--no-wxauto4", dest="use_wxauto4", action="store_false", help="不使用 wxauto4 构造器，直接走窗口控制器")
    parser.add_argument("--click-search-box", action="store_true", help="使用坐标点击左上角搜索框")
    parser.add_argument("--no-click", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-shortcut", action="store_true", help="不使用搜索快捷键")
    parser.add_argument("--shortcut", default="ctrl+f", help="搜索快捷键，例如 ctrl+f 或 ctrl+k")
    parser.add_argument("--search-x", type=int, default=120, help="搜索框相对窗口左上角的 X 坐标")
    parser.add_argument("--search-y", type=int, default=55, help="搜索框相对窗口左上角的 Y 坐标")
    parser.add_argument("--wait", type=float, default=0.65, help="输入名称后等待搜索结果的秒数")
    parser.add_argument("--window-ready-wait", type=float, default=0.0, help="恢复微信窗口后，点击搜索前额外等待的秒数")
    parser.add_argument("--window-ready-timeout", type=float, default=5.0, help="等待微信窗口稳定的最长秒数")
    parser.add_argument("--keep-clipboard", action="store_true", help="不恢复原剪贴板文本")
    parser.add_argument("--debug", action="store_true", help="启用 debug 日志")
    parser.add_argument("--trace-ui", action="store_true", help="输出 UI 调试快照，用于定位点击/焦点问题")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.append_output else "w"
        with output_path.open(mode, encoding="utf-8", newline="\n") as output_file:
            with contextlib.redirect_stdout(output_file):
                return _run(args)
    return _run(args)


def _run(args: argparse.Namespace) -> int:
    if args.diagnose:
        controller = WeChatWindowController()
        print(json.dumps(controller.diagnose(), ensure_ascii=False, indent=2))
        return 0
    if args.probe_listener_signals:
        from .probes import probe_listener_signals

        payload = probe_listener_signals(
            include_uia=not args.probe_no_uia,
            include_badges=not args.probe_no_badges,
            include_taskbar=args.probe_taskbar and not args.probe_no_taskbar,
            max_controls=args.probe_max_controls,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.watch_signals > 0:
        from .probes import watch_listener_signals

        watch_listener_signals(
            seconds=args.watch_signals,
            interval=args.probe_interval,
            include_uia=not args.probe_no_uia,
            include_badges=not args.probe_no_badges,
            include_taskbar=args.probe_taskbar and not args.probe_no_taskbar,
            max_controls=args.probe_max_controls,
        )
        return 0
    if args.watch_events > 0:
        from .probes import watch_win_events

        watch_win_events(seconds=args.watch_events)
        return 0
    if args.watch_taskbar > 0:
        from .probes import watch_taskbar_icons

        watch_taskbar_icons(seconds=args.watch_taskbar, interval=args.probe_interval)
        return 0
    if args.watch_wakeup > 0:
        from .probes import watch_unread_wakeup

        watch_unread_wakeup(
            seconds=args.watch_wakeup,
            interval=args.probe_interval,
            max_controls=args.probe_max_controls,
            min_changes=args.wakeup_burst_changes,
            window_seconds=args.wakeup_burst_window,
            cooldown_seconds=args.wakeup_cooldown,
            action_timeout=args.wakeup_action_timeout,
            max_probes=args.wakeup_max_probes,
            open_unread_messages=args.wakeup_open_unread,
        )
        return 0
    if not args.who:
        build_parser().error("who is required unless --diagnose or a probe command is used")

    options = SearchOptions(
        search_box_offset=(args.search_x, args.search_y),
        search_shortcut=tuple(part.strip() for part in args.shortcut.split("+") if part.strip()),
        use_shortcut=not args.no_shortcut,
        use_click=args.click_search_box and not args.no_click,
        result_wait=args.wait,
        window_ready_wait=args.window_ready_wait,
        window_ready_timeout=args.window_ready_timeout,
        restore_clipboard=not args.keep_clipboard,
    )
    wx = WeChat(
        search_options=options,
        debug=args.debug,
        trace_ui=args.trace_ui,
        prefer_wxauto4=args.use_wxauto4,
    )
    if args.message is None:
        result = wx.ChatWith(args.who)
    else:
        result = wx.SendMsg(args.message, args.who)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result else 1
