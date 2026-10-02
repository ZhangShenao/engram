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
| POST | `/sessions/{id}/messages/{messageId}/replace` | 同一事务写入新消息并删除旧消息。插入失败时旧消息还在 |
| DELETE | `/sessions/{id}/messages/{messageId}` | 删除一条 |
| GET | `/sessions/{id}/summary` | `{summary}` |
| POST | `/sessions/{id}/summary/append` | `{text}`。与旧摘要用换行拼接，保留末尾 4000 字符 |
| DELETE | `/sessions/by-character/{characterId}` | 删除该角色的会话、消息、摘要 |
| POST | `/internal/ensure-greeting` | 会话还没有消息时写入 greeting |

`POST /sessions/ensure` 在 `(character_id, user_id)` 唯一约束冲突时重新读取已有会话，而不是返回 500。

## 数据

数据库 `engram_conversation`（`CONVERSATION_DATABASE_URL`）。表 `chat_sessions`、`messages`（`seq` 保证同时间戳下的顺序）、`session_summaries`。摘要追加保留末尾 4000 字符。被挤出 verbatim 窗口的 turn 才写入滚动摘要。
