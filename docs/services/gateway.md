# Gateway

浏览器唯一能调用的进程。它不组装 prompt，也不保存角色、消息或记忆。

## 职责

- 转发角色、会话、记忆、检查器请求
- 把聊天 SSE 原样转给 Web
- 启动时调用 Character `/internal/seed`，再为尚无消息的角色写入 greeting
- 在数据库 `engram_gateway` 记录方法、路径、状态码。不记录 body 和请求头

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | `{status, service}` |
| GET/POST | `/api/characters` | 列表 / 创建。greeting 不是 2xx 时失败，并删掉刚创建的角色 |
| GET/PUT/DELETE | `/api/characters/{id}` | 读、改、删。记忆或会话清理返回 4xx/5xx 时不删角色 |
| GET | `/api/chats` | 最近会话，带角色名 |
| GET | `/api/chats/{characterId}` | 会话、消息、摘要、角色卡 |
| POST | `/api/chats/{characterId}/stream` | 新一轮，SSE |
| POST | `/api/chats/{characterId}/regenerate` | 重写最后一条助手消息 |
| POST | `/api/chats/{characterId}/continue` | 续写 |
| GET | `/api/memories/{characterId}` | 活跃记忆 |
| PATCH/DELETE | `/api/memories/{memoryId}` | 用户编辑 / 软删 |
| GET | `/api/inspector/{characterId}` | 最近一次检查器快照 |

用户 id 固定为 `local`。

## 数据

`request_log(id, method, path, status_code, created_at)`。
