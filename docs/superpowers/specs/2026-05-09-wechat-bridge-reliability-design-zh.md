# 微信桥接可靠性设计

日期：2026-05-09

## 目标

为 `my-wxauto` 构建可靠性核心，使其成为一个 Windows 本地的微信桥接层。该桥接层应提供稳定的消息捕获与投递基础能力，后续可以以非侵入式方式连接到 Hermes Agent 或 OpenClaw。

本设计聚焦两个问题：

1. 避免机器人对同一条微信消息重复处理。
2. 避免在机器人或模型思考期间漏掉消息。

本设计暂不实现 Hermes 或 OpenClaw 的集成。

参考：

- Hermes Agent: https://github.com/NousResearch/hermes-agent
- OpenClaw: https://github.com/openclaw/openclaw

## 当前背景

项目目前已经具备以下核心能力：

- 打开一个微信会话。
- 向一个会话发送文本消息。
- 通过任务栏或托盘闪烁检测新消息。
- 打开未读会话并读取当前可见消息。
- 尽可能读取可见消息的发送者信息。
- 标记一条可见消息是否看起来由当前用户自己发送。

当前监听器实现仍然是直接回调流。它应该先演进成一个小型本地消息管线，再接入真实的机器人框架。

## 关键决策

### 每个事件只对应一个会话

桥接层不能把多个彼此无关的微信会话混在一起，作为一个请求发送给 Hermes 或 OpenClaw。

正确方式应为：

- 每个被打开的会话都产生自己的事件。
- 每个事件只包含该会话中新观察到的一批消息。
- `max_chats_per_drain` 控制的是微信 UI 读取器在一次 drain 周期中最多打开多少个会话，它不是模型侧的批大小。

默认值：

```text
max_chats_per_drain = 5
```

### 读完一个会话后立即发出

当一次 drain 周期看到多个未读会话时，每个会话在读取完成后都应立刻发出。

桥接层不能等到所有未读会话都读取完之后，再统一交给下游机器人层。

流程：

```text
detect unread signal
  -> scan visible unread conversations
  -> open unread conversation 1
  -> read visible messages
  -> emit conversation event immediately
  -> open unread conversation 2
  -> read visible messages
  -> emit conversation event immediately
  -> stop after N conversations or time budget
  -> rescan later
```

### 私聊和群聊使用相同规则

第一版不区分私聊和群聊。

所有聊天都使用相同的分批和投递规则：

- 被 @ 的消息会触发处理。
- 非 @ 消息同样会触发处理。
- 第一版不做群聊专用的回复过滤。

### 冻结后的批次不再变动

第一版应避免在高频活跃会话中出现饥饿问题。

一个打开中的批次可以持续收集新消息，直到满足某个批次切分条件。一旦批次被冻结并提交给下游处理，同一会话后续到来的消息应进入下一个批次，而不是继续修改这个已冻结批次。

这意味着：

- 冻结前：消息会持续合并。
- 冻结后：批次内容保持稳定。
- 下游响应要绑定到它所处理的那个冻结批次。

这一设计优先保证消息捕获的可靠性和整体推进能力，而不是始终去回复绝对最新的一条消息。

## 消息去重

对于当前目标微信版本，微信 UI Automation 没有暴露稳定的消息 ID。桥接层应生成一个软消息键。

推荐键字段：

```text
chat_name
sender
is_self
message_type
content
time_text
occurrence_index_in_snapshot
```

最终得到的键应当做哈希并存入本地状态。

这个键本质上是尽力而为的方案。它应当足够稳定，以便在以下场景中防止重复处理：

- 同一个未读会话被扫描了两次。
- 微信因为同一条未读消息反复闪烁。
- 桥接层重启后又看到了最近刚显示过的消息。

对于在同一可见区域内重复出现的完全相同消息，这个键可能仍然不完美。`occurrence_index_in_snapshot` 用来降低这种风险。

## 本地状态

使用一个小型本地 SQLite 数据库来保存持久状态。

初始表如下：

```text
seen_messages
  message_key text primary key
  chat_name text not null
  first_seen_at real not null
  last_seen_at real not null
  payload_json text not null

conversation_batches
  batch_id text primary key
  chat_name text not null
  status text not null
  created_at real not null
  frozen_at real
  submitted_at real
  completed_at real
  message_count integer not null
  payload_json text not null

outgoing_echoes
  echo_key text primary key
  chat_name text not null
  content text not null
  sent_at real not null
  expires_at real not null
```

`seen_messages` 用于防止重复入站处理。

`conversation_batches` 提供可观测性，以及重放和调试能力。

`outgoing_echoes` 帮助避免把机器人自己发送的消息又当成新的入站用户消息。

## 分批规则

每个会话在任意时刻最多只有一个打开中的批次。

当满足任一条件时，批次被冻结：

```text
quiet_window_seconds = 1.5
max_batch_wait_seconds = 8.0
max_batch_messages = 10
```

含义如下：

- 如果 1.5 秒内没有新消息到达，则冻结该批次。
- 如果消息持续不断到来，则从第一条消息开始累计 8 秒后冻结。
- 如果很短时间内收到了 10 条消息，则立即冻结。

冻结后：

- 该批次会提交给下游机器人处理。
- 同一会话后续的新消息会开启一个新的打开批次。

## Drain 循环

监听器应使用 drain 循环，而不是单次 probe 回调。

推荐默认限制：

```text
max_chats_per_drain = 5
max_ui_busy_seconds = 15.0
rescan_after_each_drain = true
```

行为如下：

- 通过任务栏或托盘闪烁检测新消息唤醒。
- 恢复微信窗口。
- 扫描当前可见的会话列表。
- 选出最多 `max_chats_per_drain` 个未读会话。
- 逐个打开并读取这些会话。
- 每个会话读取完成后立即发出其新消息。
- 当达到会话数量上限或 UI 时间预算后，停止本次 drain 周期。
- 若仍有更多未读消息，在后续周期中再次扫描。

第一版只保证处理当前可见的未读会话。对于非常长的未读列表，后续可以再增加滚动支持。

## 并发模型

所有直接操作微信 UI 的行为都必须串行化。

应使用单个 UI 操作队列或全局 UI 锁来保护以下操作：

- 恢复微信窗口。
- 扫描会话。
- 打开会话。
- 读取消息。
- 发送消息。

模型或机器人处理不能持有 UI 锁。

线程或任务划分：

```text
wakeup listener
  detects flashing and schedules drains

ui worker
  owns WeChat UI operations

batcher
  deduplicates messages and freezes conversation batches

robot dispatcher
  submits frozen batches to Hermes/OpenClaw/shim later

send worker
  serializes outgoing WeChat sends through the same UI queue/lock
```

## 下游集成形态

桥接层应暴露规范化后的会话批次，而不是 Hermes 专用负载。

推荐事件格式：

```json
{
  "event_id": "wechat-event-...",
  "batch_id": "wechat-batch-...",
  "platform": "wechat_desktop",
  "chat_id": "wechat:alice",
  "chat_name": "alice",
  "messages": [
    {
      "message_key": "...",
      "sender": "alice",
      "is_self": false,
      "message_type": "text",
      "content": "hello",
      "time_text": "15:41"
    }
  ]
}
```

后续接入 Hermes 时，应把每个会话批次分别作为独立的 Hermes event/session 发送。多个微信会话不能合并为一个 Hermes prompt。

## 防止回复回路

桥接层应避免被自己发出的消息再次触发机器人处理。

规则如下：

- 明确判断 `is_self` 为 true 的消息直接忽略。
- 机器人发送回复后，写入一条带短 TTL 的 `outgoing_echoes` 记录。
- 如果后续可见消息与近期发送回声匹配，则抑制其进入入站处理。

由于 `is_self` 判断本身只是尽力而为，回声缓存是一个额外保险。

## 错误处理

第一版应优先保证监听器持续运行，而不是追求完美恢复。

推荐行为：

- 如果某个会话打开失败，记录错误并继续当前 drain 周期。
- 如果某个会话读取消息失败，记录错误并继续。
- 如果恢复微信失败，则退避并在下一次唤醒时重试。
- 如果 UI 操作时间超过 `max_ui_busy_seconds`，停止当前 drain，稍后再扫描。
- 如果 SQLite 写入失败，则不要把受影响事件提交给下游，因为去重安全性已不可确认。

所有失败都应记录足够上下文：

- 会话名
- 操作名
- 耗时
- 异常类型 / 消息
- 当前 drain id

## 测试策略

单元测试应覆盖：

- 软消息键生成。
- 针对重复快照的去重。
- 按静默窗口冻结批次。
- 按最大等待时间冻结批次。
- 按最大消息数冻结批次。
- `max_chats_per_drain` 限制。
- drain 期间按会话立即发出。
- 发送回声抑制。
- 使用 fake worker 验证 UI 锁串行化。

由于微信 UI 行为强依赖环境，集成探针测试应继续保持对手工验证友好。

## 第一版非目标

以下内容有意不纳入当前范围：

- 滚动整个会话列表以找出所有未读会话。
- 区分群聊和私聊的行为。
- Hermes 源码级适配器实现。
- OpenClaw 连接器实现。
- 读取微信当前未渲染出来的历史消息。
- 从微信内部拿到完美消息 ID。

## 后续待定事项

在实现完这个可靠性核心之后，下一份设计应决定桥接接口形式：

- 本地 HTTP API
- SSE 或 WebSocket 事件流
- webhook 投递模式
- 可选的 MCP 工具服务

推荐路径仍然是一个 Windows 本地桥接层，再加一个薄的、非侵入式的 Hermes/OpenClaw shim。
