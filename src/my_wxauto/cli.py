from __future__ import annotations

import argparse
import json

from .wechat import SearchOptions, WeChat
from .window import WeChatWindowController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Open a WeChat conversation or send a message.")
    parser.add_argument("who", nargs="?", help="contact, group, or session name")
    parser.add_argument("--message", help="要发送的文本消息；不传时仅打开聊天窗口")
    parser.add_argument("--diagnose", action="store_true", help="print detected WeChat processes/windows and exit")
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
    if args.diagnose:
        controller = WeChatWindowController()
        print(json.dumps(controller.diagnose(), ensure_ascii=False, indent=2))
        return 0
    if not args.who:
        build_parser().error("who is required unless --diagnose is used")

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
