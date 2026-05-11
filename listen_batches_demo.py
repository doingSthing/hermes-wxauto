from my_wxauto import WeChat

def on_batch(batch):
    print("会话:", batch.chat_name)
    print("消息数:", batch.message_count)
    for msg in batch.messages:
        print("-", msg.sender, msg.is_self, msg.content)
    print("-" * 40)

if __name__ == "__main__":
    wx = WeChat()
    # wx.listen_conversation_batches(
    #     on_batch,
    #     seconds=120,
    #     max_events=3,
    #     max_chats_per_drain=5,
    # )
    wx.listen_conversation_batches(
        on_batch,
        resolve_senders="profile_card",
        sender_resolve_limit=5,
        max_events=3,
    )