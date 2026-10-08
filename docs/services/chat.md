# chat-service

浏览器和 Next.js 唯一访问的 HTTP 服务，端口 18410。库 `engram_chat`。Web 把 `/gateway/*` 代理到这里，聊天页面本身由 Next 在 18415 提供。

Compose 容器名是 `engram-chat`。同一网络里的主机名是服务名 `chat`，所以 `engram-web` 的 `GATEWAY_URL` 是 `http://chat:18410`，不是 `http://engram-chat:18410`。

## 拥有

- 角色卡：名称、tagline、人设、场景、示例、greeting、说话风格、boundaries、时间戳
- 请求日志：方法、路径、状态码。不含正文，不含密钥，也不记录模型返回的文本
- CORS，允许的来源来自 `WEB_ORIGIN`，默认是本机 18415
- 空库时的种子角色 Lyra、Zero、Mara。种子写入后会让 context 把 greeting 存成第一条 assistant 消息。greeting 失败会删掉刚建的角色卡，避免列表里出现一个没有开场的角色

创建角色走同样的 greeting 路径。删除角色时先调用 memory 的 `DeleteByCharacter`，再调用 context 的 `DeleteByCharacter`，最后删角色卡。下游已经清掉但角色卡删除失败时，卡还在，可以再删一次。

chat 不连接 Kafka。它不知道 `memory.extract` 是否已经写完。回合的 HTTP 响应在 context 的流结束时结束，而那次流在发布 Kafka 之后就结束，不等提取。

## 路由

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/health` | Compose 和 `scripts/dev.sh` 的探针 |
| GET/POST | `/api/characters` | 列表、创建 |
| GET/PUT/DELETE | `/api/characters/{id}` | 读取、更新、删除 |
| GET | `/api/chats` | 最近会话，附带角色卡上的名称 |
| GET | `/api/chats/{characterId}` | 会话、消息、摘要 |
| POST | `/api/chats/{characterId}/stream` | 新的一轮，正文 `{ "message": "..." }` |
| POST | `/api/chats/{characterId}/regenerate` | 替换最后一条助手回复 |
| POST | `/api/chats/{characterId}/continue` | 顺着上一句往下写 |
| GET/PATCH/DELETE | `/api/memories/...` | 转给 memory |
| GET | `/api/inspector/{characterId}` | 转给 context，读最近一次检查器快照 |

流式响应的媒体类型是 `text/event-stream`，并带 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`。chat 自己的日志记 `headers_ms`、`first_byte_ms` 和 `total_ms`。`total_ms` 包含 context 发布 Kafka 的等待，不包含记忆提取。

角色不存在时，stream、regenerate 和 continue 在打开 gRPC 之前返回 JSON 404。context 在第一帧之前失败时，chat 也返回 JSON。第一帧之后的失败是 SSE `error`。

## 不拥有

消息、摘要、检查器、prompt、模型调用、记忆行。这些向 context 或 memory 读，或把角色卡交给 context 的 `StreamTurn`。系统提示词不要写在这个服务里，也不要写进 `web/`。

用户 id 在本期固定为 `local`。没有注册和登录。CORS 只放行配置里的 Web 来源，内部 gRPC 端口不对该来源开放。
