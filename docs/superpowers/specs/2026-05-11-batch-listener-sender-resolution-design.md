# Batch Listener 可选发送人解析设计

## 目标

为 `listen_conversation_batches` 增加可选的发送人解析能力，使机器人集成在需要群聊上下文时可以拿到每条消息的 `sender` 和尽可能可靠的 `is_self` 标识。

默认监听路径必须继续保持轻量、快速、不额外点击头像。只有调用方显式开启发送人解析时，监听器才会尝试通过头像资料卡读取昵称。

## 背景

当前 batch listener 已经可以：

- 根据微信闪烁/未读信号打开未读会话。
- 读取当前可见消息内容。
- 去重、按会话分批、持久化状态。
- 每个会话单独回调一个 `ConversationBatch`。
- 发送消息后记录 outgoing echo，避免读到自己的回复。

但实时监听路径使用的是 `probes._parse_chat_message_items` 的轻量解析。该路径目前只能稳定拿到内容、类型、时间和控件矩形，不能默认拿到发送人，所以 batch 中经常出现：

```text
sender = None
is_self = None
```

已有的 `get_visible_messages(..., resolve_senders="profile_card")` 路径已经实现了头像资料卡解析，可复用其中的解析能力。

## 非目标

本设计不做以下事情：

- 不实现 Hermes 或 OpenClaw 的接入。
- 不新增 HTTP/SSE/WebSocket 桥接服务。
- 不默认开启头像点击解析。
- 不保证所有文件、图片、系统消息都能解析到发送人。
- 不尝试解析不可见历史消息。
- 不把多个会话合并成一个模型请求。

## API 设计

在 `listen_conversation_batches` 及 `WeChat.listen_conversation_batches` 中增加可选参数：

```python
wx.listen_conversation_batches(
    on_batch,
    resolve_senders="profile_card",
    sender_resolve_limit=5,
    sender_resolve_timeout=20.0,
    profile_card_timeout=2.0,
    sender_progress=print,
)
```

参数含义：

- `resolve_senders`: 默认 `False`。为 `"profile_card"` 或 `True` 时启用头像资料卡解析。
- `sender_resolve_limit`: 每个会话最多尝试解析多少条消息。默认 `5`。若调用方显式传 `0`，表示不限制。
- `sender_resolve_timeout`: 单个会话发送人解析的总耗时上限。
- `profile_card_timeout`: 单次点击头像后等待并读取资料卡昵称的上限。
- `sender_progress`: 可选调试回调，用于输出解析阶段、点击点、结果或跳过原因。

默认调用保持不变：

```python
wx.listen_conversation_batches(on_batch)
```

该调用不点击头像，不解析发送人。

## 数据流

开启发送人解析后，每个未读会话的处理流程为：

1. 监听器发现微信未读/闪烁信号。
2. probe 打开最多 `max_chats_per_drain` 个未读会话。
3. 每打开一个会话，读取当前聊天区可见消息。
4. 将原始 probe 消息转换为 `ChatMessage`。
5. 为消息补充 `visible_rect`，并尽可能用气泡像素判断 `is_self`。
6. 对符合条件的消息调用头像资料卡解析，读取昵称。
7. 将解析后的消息转换为 `BridgeMessage`。
8. 进入现有 `ConversationBatcher` 去重、分批、冻结和回调流程。

未开启发送人解析时，流程仍保持当前快速路径：

```text
probe payload -> BridgeMessage -> ConversationBatcher
```

## 解析策略

### `is_self`

优先复用现有像素推断能力：

- 对每条消息使用 `visible_rect` 和聊天区截图判断气泡位置/颜色。
- 能判断时写入 `is_self=True/False`。
- 无法判断时保持 `None`。

`is_self=True` 的消息不需要点击头像解析发送人。

### `sender`

仅在以下条件满足时尝试头像资料卡解析：

- `resolve_senders` 已开启。
- 消息当前可见并有合理的头像点击候选点。
- 消息不是明确的 `is_self=True`。
- 未超过 `sender_resolve_limit`。
- 未超过 `sender_resolve_timeout`。

解析失败时不阻塞整个监听器，保留 `sender=None` 并继续后续消息。

## 批次与可靠性

发送人解析发生在 batcher 去重与冻结之前。这样 `BridgeMessage` 中的 `sender/is_self` 会进入持久化 payload。

如果解析发送人很慢或失败，不应破坏现有可靠性语义：

- 已读到的消息仍然可以进入 batch。
- 回调成功后仍然标记 batch 为 `submitted`。
- 回调失败时 frozen batch 仍可下次重试。
- 发送人解析失败不能导致消息丢失。

## UI 影响

头像资料卡解析会点击微信聊天界面中的头像，并关闭资料卡，因此会打扰当前微信界面。

因此该功能默认关闭。调用方只有在确实需要发送人信息时才开启，例如群聊机器人场景。

## 测试策略

需要覆盖以下测试：

- 默认 `listen_conversation_batches` 不调用发送人解析逻辑。
- `resolve_senders="profile_card"` 时，会把 probe 消息转换为 `ChatMessage` 并调用解析函数。
- 解析成功后，batch 中的 `BridgeMessage.sender` 被填充。
- `is_self=True` 的消息不会尝试点击头像解析。
- `sender_resolve_limit` 生效，只解析限定数量。
- 解析失败或超时不会阻止 batch 产生。
- 现有去重、冻结、重试、`max_events` 行为不回退。

真实微信验证时，应使用一个包含多人消息的群聊，观察：

- 默认模式仍输出 `sender=None`。
- 开启 `resolve_senders="profile_card"` 后，非自己消息尽可能输出昵称。
- 自己发送的消息至少能标识 `is_self=True`，即使没有昵称。

## 验收标准

- 默认监听速度与 UI 干扰程度不发生明显变化。
- 开启发送人解析后，群聊中可见的非自己文本消息能尽可能填充 `sender`。
- 对无法解析的消息保留 `sender=None`，但不影响内容读取和 batch 回调。
- 全量测试通过。
- 后续 Hermes/OpenClaw 桥接服务可以直接消费包含 `sender/is_self/content` 的 batch event。
