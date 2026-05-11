# 本地微信桥接服务第一版设计

日期：2026-05-11

## 目标

为 `my-wxauto` 增加一个本机 HTTP 桥接服务，让 Hermes Agent、OpenClaw 或其他本地机器人进程可以用非侵入方式接入微信桌面端。

第一版只做桥接层，不做机器人思考逻辑：

- 把已有的 `listen_conversation_batches()` 暴露成可拉取的 HTTP 事件流。
- 把已有的 `WeChat.SendMsg()` 暴露成 HTTP 发送接口。
- 保持所有微信 UI 操作在本机进程内完成。
- 默认只监听 `127.0.0.1`，不暴露到局域网或公网。

## 背景

当前工程已经具备以下基础能力：

- 打开指定微信会话。
- 给指定会话发送文本消息。
- 通过任务栏或托盘闪烁检测未读消息。
- 打开未读会话并读取未读消息尾部。
- 对消息生成稳定 key，写入 SQLite 状态库做去重。
- 按会话生成 `ConversationBatch`，并支持发送人解析。

下一步需要把这些能力包装成一个本地服务，使外部机器人不需要 import 或修改 `my-wxauto` 内部代码，也不需要直接控制微信 UI。

## 非目标

第一版不做以下事情：

- 不实现 Hermes 或 OpenClaw 的内部适配器。
- 不调用大模型。
- 不实现公网访问、鉴权、TLS 或多用户权限模型。
- 不实现 WebSocket、SSE 或流式推送。
- 不实现事件 ack、重放游标或跨进程 outbox。
- 不支持发送图片、文件、语音或富文本。
- 不解决微信本身 UI 自动化不稳定导致的所有边缘情况。

## 方案选择

采用 Python 标准库 `http.server.ThreadingHTTPServer` 实现本地 HTTP 服务。

选择理由：

- 不新增 FastAPI、uvicorn 等运行时依赖。
- Windows 本地部署简单。
- 对 Hermes/OpenClaw 来说 HTTP 接入足够通用。
- 第一版接口少，标准库实现可控且易测试。

后续如果需要浏览器调试页面、SSE、WebSocket 或 OpenAPI 文档，再升级为 FastAPI。

## HTTP API

### `GET /health`

返回服务状态。

示例响应：

```json
{
  "status": "ok",
  "queue_size": 0,
  "listener_alive": true,
  "store_path": ".my_wxauto_bridge.sqlite3"
}
```

字段含义：

- `status`: 服务自身是否可响应。
- `queue_size`: 当前内存事件队列长度。
- `listener_alive`: 后台监听线程是否仍在运行。
- `store_path`: 当前使用的 SQLite 状态库路径。

### `GET /events?timeout=30&limit=5`

长轮询获取会话批次事件。

行为：

- 如果队列已有事件，立即返回最多 `limit` 条。
- 如果队列为空，最多等待 `timeout` 秒。
- 超时仍无事件时返回空数组。
- `timeout` 默认 30 秒，最大值限制为 120 秒。
- `limit` 默认 5，最大值限制为 50。

示例响应：

```json
{
  "status": "ok",
  "count": 1,
  "events": [
    {
      "event_id": "wechat-batch-...",
      "batch_id": "wechat-batch-...",
      "platform": "wechat_desktop",
      "chat_id": "wechat:张勋",
      "chat_name": "张勋",
      "message_count": 1,
      "messages": [
        {
          "message_key": "...",
          "chat_name": "张勋",
          "sender": "张勋",
          "is_self": false,
          "message_type": "text",
          "content": "你好",
          "time_text": "14:18",
          "occurrence_index": 0,
          "raw": {}
        }
      ]
    }
  ]
}
```

下游机器人应使用 `batch_id` 或 `message_key` 做幂等保护。

### `POST /send`

发送文本消息。

请求体：

```json
{
  "who": "张勋",
  "message": "你好"
}
```

响应体直接使用 `WxResponse.to_dict()` 风格：

```json
{
  "status": "success",
  "message": "已尝试向 张勋 发送消息。",
  "data": {
    "who": "张勋",
    "message": "你好"
  }
}
```

错误规则：

- JSON 无效或字段缺失时返回 HTTP 400。
- 微信发送失败时返回 HTTP 200，响应体中 `status` 为 `error` 或 `failure`，保持与现有 `WeChat.SendMsg()` 语义一致。

## 运行方式

CLI 增加服务启动参数：

```powershell
python -m my_wxauto --bridge-server --bridge-host 127.0.0.1 --bridge-port 8765 --store-path .my_wxauto_bridge.sqlite3
```

监听相关参数复用已有 CLI 语义：

- `--listen-max-chats`
- `--listen-resolve-senders`
- `--listen-sender-limit`
- `--store-path`
- `--no-wxauto4`
- `--debug`
- `--trace-ui`

第一版默认开启后台监听，服务启动后即可通过 `/events` 拉取批次事件。

## 内部组件

新增模块为 `my_wxauto.bridge_server`。

核心对象：

- `BridgeServerConfig`: host、port、store_path、监听参数、队列大小。
- `BridgeRuntime`: 持有 `WeChat`、事件队列、监听线程和 UI 锁。
- `BridgeRequestHandler`: HTTP 请求处理器，调用 runtime 完成 `/health`、`/events`、`/send`。
- `run_bridge_server(config)`: CLI 入口调用的阻塞式启动函数。

事件队列：

- 使用内存 `queue.Queue` 保存 `ConversationBatch.to_event_dict()`。
- 默认容量 100。
- 如果队列满，监听回调抛出异常，让现有 frozen batch 重试机制保留消息，不静默丢弃。

## 并发模型

所有直接触碰微信 UI 的操作必须串行化。

第一版采用一个 `threading.RLock`：

- 后台监听线程执行微信恢复、打开未读会话、读取消息时持有锁。
- `/send` 调用 `WeChat.SendMsg()` 时持有同一把锁。
- `/events` 和 `/health` 不触碰微信 UI，不需要持有 UI 锁。

为了做到这一点，`listen_conversation_batches()` 增加可选 `ui_lock` 参数。服务层创建同一把 `RLock`，后台监听线程把它传给监听器，`/send` 处理时也使用这把锁。监听器只在执行实际微信 UI probe 时持有锁，不在长轮询睡眠或事件队列处理时持有锁。

## 事件可靠性边界

第一版提供进程内可靠性，不承诺完整跨进程投递可靠性。

已经覆盖：

- 消息 key 去重。
- SQLite 保存 seen message 和 batch 状态。
- 监听回调失败时 frozen batch 可重试。
- 队列满时不静默吞掉事件。

第一版不覆盖：

- 事件成功入内存队列后，服务进程崩溃导致的 HTTP 消费侧未取事件。
- 下游机器人处理失败后的 ack/retry 协议。
- 多消费者分发。

这些可以在第二版通过 outbox 表、`/ack` 和消费游标解决。

## 测试策略

自动化测试覆盖：

- `/health` 返回队列长度、监听线程状态和 store path。
- `/events` 在队列有事件时立即返回。
- `/events` 在无事件时可超时返回空数组。
- `/send` 校验 JSON 入参并调用 runtime 发送。
- CLI 参数能正确构造 bridge server 配置。
- 队列满时监听回调抛出异常。
- 全量测试不回归现有打开聊天、发送消息、监听批次能力。

真实微信验证：

1. 启动服务：

   ```powershell
   python -m my_wxauto --bridge-server --bridge-host 127.0.0.1 --bridge-port 8765 --store-path .my_wxauto_bridge_server.sqlite3 --listen-resolve-senders profile_card
   ```

2. 用另一个微信发送消息。
3. 调用 `GET http://127.0.0.1:8765/events?timeout=30&limit=5`。
4. 确认响应中只包含未读新消息。
5. 调用 `POST http://127.0.0.1:8765/send` 发送回复。
6. 确认机器人自己的回复不会被下一轮当作新入站消息处理。

## 验收标准

- 服务可在 Windows 本机启动，并只绑定到 `127.0.0.1`。
- `/events` 能返回 `ConversationBatch.to_event_dict()` 结构。
- `/send` 能复用现有发送逻辑并记录 outgoing echo。
- 监听和发送不会并发抢微信 UI。
- 不新增第三方 HTTP 服务依赖。
- 现有测试和新增服务测试全部通过。
