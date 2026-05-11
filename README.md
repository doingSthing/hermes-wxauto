# my-wxauto

`my-wxauto` 是一个面向新版 Windows 微信客户端的自动化兼容层。当前已支持两个核心动作：

```python
from my_wxauto import WeChat

wx = WeChat()
wx.ChatWith("张三")
wx.SendMsg("你好", "张三")
```

## Conversation batch listener

`my-wxauto` also exposes a reliability-oriented listener for robot integrations.
It reads unread WeChat conversations in bounded drain cycles, deduplicates
messages, batches messages per conversation, and emits one conversation batch
at a time.

```python
from my_wxauto import WeChat

wx = WeChat()

def on_batch(batch):
    print(batch.to_event_dict())

wx.listen_conversation_batches(
    on_batch,
    max_chats_per_drain=5,
)
```

The listener does not send multiple unrelated conversations as one model
request. Each emitted batch belongs to one WeChat conversation.

Sender resolution is opt-in because it clicks visible avatars and may slow down
or disturb the WeChat UI. Enable it only when the robot needs group-chat sender
names:

```python
wx.listen_conversation_batches(
    on_batch,
    max_chats_per_drain=5,
    resolve_senders="profile_card",
    sender_resolve_limit=5,
)
```

## 免责声明

本工具仅供学习研究使用。使用者应遵守微信用户协议及相关法律法规，并自行承担使用本工具产生的风险与责任。

## 设计取舍

新版微信 4.x 的界面大量迁移到 Qt Quick/QML 后，传统 UIAutomation 控件树经常不可用。因此这里先不依赖读取控件树，而是采用更接近真人操作的路径：

1. 枚举并激活微信主窗口。
2. 点击左上角搜索框，必要时再使用搜索快捷键。
3. 通过剪贴板粘贴联系人/群聊名称。
4. 回车打开第一条搜索结果。
5. 如需发送文本消息，则在聊天窗口中粘贴消息并回车发送。

这个动作天然无法像旧版 UIA 那样强校验“精确匹配”。`exact=True` 会保留在接口里，但第一版只会记录为未验证匹配。调用方如需绝对精确，建议给 `who` 传入足够唯一的名称。

## 命令行

在项目根目录可以直接运行：

```powershell
python -m my_wxauto "张三"
```

默认会参考 `F:\ai-work\2026-3\wxbot` 的做法，先借助 `wxauto4` 把微信窗口从最小化/托盘状态恢复并置前；但搜索动作由本项目自己完成，使用 `Ctrl+F` 聚焦搜索，不再沿用 `wxauto4.ChatWith()` 的旧坐标点击。

也可以先安装成可编辑包：

```powershell
python -m pip install -e .
my-wxauto "张三"
```

如搜索快捷键不适配当前微信版本，可以只用点击搜索框：

```powershell
python -m my_wxauto "张三" --no-shortcut
```

查看当前能识别到的微信进程和窗口：

```powershell
python -m my_wxauto --diagnose
```

恢复最小化/托盘状态时，程序会优先模拟“双击微信托盘图标”。如果 `--diagnose` 里的 `tray_icons` 没有出现包含“微信/WeChat/Weixin”的项，说明当前环境没有把托盘图标暴露给自动化层，会退回到直接启动 `Weixin.exe` 的兜底路径。

如果托盘恢复不可用，程序才会退回到旧的 `Weixin.exe` 拉起方式；这种方式在新版微信上可能出现空白主体窗口。只有在你的机器上搜索层也需要更久才响应时，再加大恢复后的等待：

```powershell
python -m my_wxauto "张三" --window-ready-wait 2
```

也可以微调搜索框点击位置，单位是相对微信窗口左上角的像素：

```powershell
python -m my_wxauto "张三" --search-x 120 --search-y 55
```

强制完全不使用 `wxauto4` 的窗口恢复能力：

```powershell
python -m my_wxauto "张三" --no-wxauto4
```

直接发送文本消息：

```powershell
python -m my_wxauto "张三" --message "你好"
```
