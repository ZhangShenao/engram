# Conversation

会话时间线的所有者：会话、原文消息、滚动摘要正文。它不决定哪些 turn 被裁掉。是否追加摘要由 Harness 根据 `evictedTurns` 决定。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | |
| POST | `/sessions/ensure` | `{characterId, userId}` → `{sessionId, created}`。`(character_id, user_id)` 唯一 |
| GET | `/sessions/by-character/{characterId}` | 取或建会话 |
| GET | `/sessions/recent?userId=` | 按最后一条消息时间排序 |
| GET/POST | `/sessions/{id}/messages` | 列表 / 追加。`role` 为 `user` 或 `assistant` |
| DELETE | `/sessions/{id}/messages/{messageId}` | 删除一条（regenerate 成功后由 Harness 调用） |
| GET | `/sessions/{id}/summary` | `{summary}` |
| POST | `/sessions/{id}/summary/append` | `{text}`。与旧摘要用换行拼接，保留末尾 4000 字符 |
| DELETE | `/sessions/by-character/{characterId}` | 删除该角色的会话、消息、摘要 |
| POST | `/internal/ensure-greeting` | 会话还没有消息时写入 greeting |

## 数据

`data/conversation.db`：`chat_sessions`、`messages`、`session_summaries`。
