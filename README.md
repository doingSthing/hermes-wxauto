# hermes-wxauto

`hermes-wxauto` 是一个面向新版 Windows 微信客户端的自动化兼容层，用来把桌面微信接入本地机器人流程。它提供三类基础能力：

- 打开联系人或群聊，并发送消息。
- 监听微信未读消息，按会话输出消息事件。
- 通过本地 HTTP 桥接服务接入 Hermes、OpenClaw 或其他本地机器人。

当前 Python 包名仍是 `my_wxauto`，所以源码目录下继续使用 `python -m my_wxauto ...`；安装后可以使用命令行脚本 `hermes-wxauto ...`。

## 安装

准备环境：

- Windows。
- Python 3.9+。
- 已登录 Windows 微信客户端。
- 如果要接入 Hermes，需要先在本机 WSL 中安装并配置好 Hermes。

建议在虚拟环境中安装：

```powershell
cd F:\ai-work\2026-4-28\my-wxauto
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e .[dev]
```

安装完成后可以验证命令是否可用：

```powershell
hermes-wxauto --help
```

如果没有安装到环境中，也可以在项目根目录直接使用模块方式运行：

```powershell
python -m my_wxauto --help
```

## 基础使用

打开联系人或群聊：

```powershell
hermes-wxauto "张三"
```

发送一条消息：

```powershell
hermes-wxauto "张三" --message "你好"
```

查看当前能识别到的微信进程和窗口：

```powershell
hermes-wxauto --diagnose
```

如果你还没有执行安装命令，上面的 `hermes-wxauto` 都可以替换成：

```powershell
python -m my_wxauto
```

例如：

```powershell
python -m my_wxauto "张三" --message "你好"
```

## 桥接服务

桥接服务是本项目给外部机器人使用的本地 HTTP 服务。它负责：

- 监听微信未读消息。
- 按会话生成事件，每个事件只对应一个微信会话。
- 维护事件状态，避免消息重复处理。
- 提供 `/send` 接口，让机器人把回复发回微信。

启动桥接服务。这个命令建议放在独立终端中运行，它会一直监听：

```powershell
hermes-wxauto --bridge-server --bridge-host 127.0.0.1 --bridge-port 8765 --store-path .\.wxauto-bridge.sqlite3 --bridge-queue-size 1000 --listen-max-chats 5
```

常用参数说明：

- `--bridge-host 127.0.0.1`：只允许本机访问。
- `--bridge-port 8765`：HTTP 服务端口。
- `--store-path .\.wxauto-bridge.sqlite3`：桥接事件和状态的 SQLite 文件。
- `--bridge-queue-size 1000`：内存事件队列大小。
- `--listen-max-chats 5`：每一轮最多打开 5 个未读会话。
- `--debug`：输出更多程序调试信息。
- `--trace-ui`：输出窗口、焦点、搜索候选、点击坐标等 UI 诊断日志。

验证桥接服务是否启动：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

只测试桥接服务的发送能力：

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/send -ContentType "application/json; charset=utf-8" -Body (@{ who = "张三"; message = "桥接发送测试" } | ConvertTo-Json -Compress)
```

## Hermes Sidecar

sidecar 是连接桥接服务和 Hermes 的适配进程。它会从 bridge 拉取微信消息事件，把一个会话的新消息交给 Hermes 思考，再通过 bridge 把 Hermes 的回复发送回原会话。

推荐启动顺序如下。

终端 1：启动微信桥接服务：

```powershell
hermes-wxauto --bridge-server --bridge-host 127.0.0.1 --bridge-port 8765 --store-path .\.wxauto-bridge.sqlite3 --bridge-queue-size 1000 --listen-max-chats 5
```

终端 2：首次联调建议先用 dry-run。dry-run 会调用 Hermes 并打印回复，但不会真正发送微信消息，也不会 ack/complete 事件：

```powershell
python -m my_wxauto.hermes_sidecar --bridge-url http://127.0.0.1:8765 --dry-run --once --debug
```

确认 dry-run 正常后，启动正式 sidecar：

```powershell
python -m my_wxauto.hermes_sidecar --bridge-url http://127.0.0.1:8765
```

正式 sidecar 会持续运行。收到事件后，它会调用 Hermes、发送微信回复，并将事件标记为完成。

sidecar 会为每个微信会话维护独立 Hermes session。默认 session 文件在：

```text
~/.wxauto/hermes_sessions.json
```

## HTTP API

桥接服务提供以下接口：

```text
GET  http://127.0.0.1:8765/health
GET  http://127.0.0.1:8765/events?timeout=30&limit=5
POST http://127.0.0.1:8765/events/{batch_id}/ack
POST http://127.0.0.1:8765/events/{batch_id}/complete
POST http://127.0.0.1:8765/send
```

`/send` 请求体示例：

```json
{ "who": "张三", "message": "你好" }
```

`/events` 返回的每个 event 都只属于一个微信会话。外部机器人应逐会话处理，不要把多个会话混进同一个模型请求。

事件生命周期：

- `frozen`：监听器已生成会话批次，等待外部机器人确认处理。
- `submitted`：外部机器人已通过 `/events/{batch_id}/ack` 确认开始处理。
- `completed`：外部机器人已完成处理，并通过 `/events/{batch_id}/complete` 确认。

`/events` 会返回尚未完成的 `frozen` 或 `submitted` 事件，但不会改变事件状态。外部机器人开始处理前应调用 `ack`，发送回复成功后应调用 `complete`。sidecar 的 `--dry-run` 模式不会调用 `ack` 或 `complete`。

## 发送定位诊断

如果怀疑消息发错会话，先不要真实发送，先执行 dry-run：

```powershell
hermes-wxauto "张三" --message "发送前定位测试" --send-dry-run --trace-ui --output send-dry-run.txt
```

重点查看 `send-dry-run.txt` 里的两类日志：

- `search_result.candidates`：本次搜索识别到的候选控件。
- `search_result.selected`：最终选择的候选项和点击坐标。

确认 dry-run 打开的是正确会话后，再执行真实发送：

```powershell
hermes-wxauto "张三" --message "真实发送测试" --trace-ui --output send-real-test.txt
```

## 微信搜索策略

默认会借助 `wxauto4` 恢复或置前最小化、托盘状态的微信窗口，但搜索、打开会话、粘贴发送由本项目控制。默认流程是：

1. 恢复并激活微信窗口。
2. 使用 `Ctrl+F` 聚焦搜索框。
3. 粘贴联系人或群聊名称。
4. 优先点击搜索结果里的聊天入口。
5. 打开会话后粘贴消息并回车发送。

如果搜索结果里同时出现“聊天记录”“搜索网络结果”和真正的联系人/群聊，本项目会优先选择 `最常使用 / 联系人 / 群聊` 分组下的精确匹配，避免点进聊天记录弹窗或网络搜索结果。

如果搜索快捷键不适配当前微信版本，可以改为坐标点击搜索框：

```powershell
hermes-wxauto "张三" --no-shortcut --click-search-box
```

如果当前微信版本需要先按方向键下再回车，可以显式指定：

```powershell
hermes-wxauto "张三" --search-down-count 1
```

## Python API

```python
from my_wxauto import WeChat

wx = WeChat()
wx.ChatWith("张三")
wx.SendMsg("你好", "张三")
```

监听会话批次：

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

发送人解析默认关闭，因为 `profile_card` 模式会点击消息头像、读取资料卡，速度更慢，也会短暂打扰微信界面。确实需要群聊发送人时再开启：

```python
wx.listen_conversation_batches(
    on_batch,
    max_chats_per_drain=5,
    resolve_senders="profile_card",
    sender_resolve_limit=5,
)
```

## 诊断建议

PowerShell 管道有时会让中文输出乱码，建议用 `--output` 直接写 UTF-8 文件：

```powershell
hermes-wxauto "张三" --message "发送前定位测试" --send-dry-run --trace-ui --output send-dry-run.txt
```

如果桥接服务出现 `queue.Full`，通常表示监听线程生成事件的速度超过了 `/events` 消费速度。短期可以调大 `--bridge-queue-size`，并尽快启动 sidecar 或其他消费者。后续需要继续补 bridge 事件 lease 和队列满时的兜底处理。

## 核心代码位置

- `src/my_wxauto/wechat.py`：打开会话、发送消息、搜索结果选择。
- `src/my_wxauto/listener.py`：监听未读消息和读取可见消息。
- `src/my_wxauto/bridge_server.py`：本地 HTTP 桥接服务。
- `src/my_wxauto/hermes_sidecar.py`：Hermes sidecar adapter。
- `src/my_wxauto/bridge_store.py`：事件状态和去重存储。

## 设计取舍

新版微信 4.x 的界面大量迁移到 Qt Quick/QML 后，传统 UIAutomation 控件树经常不可用。因此本项目优先采用接近真人操作的路径：恢复窗口、聚焦搜索、粘贴名称、打开会话、粘贴并发送消息。

这类自动化天然无法像旧版 UIA 那样强校验“精确匹配”。调用方如需更高确定性，应传入足够唯一的联系人或群聊名称，并优先通过 dry-run 和 trace 日志验证。

## 免责声明

本工具仅供学习研究使用。使用者应遵守微信用户协议及相关法律法规，并自行承担使用本工具产生的风险与责任。
