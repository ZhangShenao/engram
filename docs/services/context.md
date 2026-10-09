# context-service

内部 gRPC，端口 18411。库 `engram_context`。一轮聊天的编排在这里，不在 chat，也不在某个外部上下文产品里。

Compose 容器名是 `engram-context`，网络主机名是 `context`。它连 `memory:18413`、`llm-gateway:18414` 和 `kafka:19092`。`LLM_TARGET` 用服务名 `llm-gateway`，不用容器名 `engram-llm-gateway`。

## 拥有

- 会话、消息、滚动摘要
- regenerate 的替换事务：新回复写入且旧回复删除，失败则两边都保持原样
- prompt 组装、裁剪、检查器快照
- 会话上的 `(provider, model)` 钉，列是 `chat_sessions.llm_provider` 和 `llm_model`
- `done` 之后向 Kafka 发布 `memory.extract` 和 `memory.reinforce`

它不保存角色主数据。角色卡由 chat 在 `StreamTurn` 的请求里整份传入，context 不回头调用 chat。它也不直接给浏览器开 HTTP。

检查器保存这一轮实际发给模型的分层、token 估算、裁剪日志和被挤出的 turn，以及耗时。它不是第二份聊天记录。消息表仍是会话的原文。`extractMs` 在发布时还没有，要等 memory 调用 `StampExtract` 才写上。发布失败只记日志，因为 `done` 已经送出。

摘要追加留在这一轮的同步路径上，只吃 `evictedTurns`。不把摘要改成队列作业，是为了下一轮开始时读到的摘要已经包含刚刚挤出的对白。

## 回合里调用谁

| 方向 | RPC 或主题 | 何时 |
|------|------------|------|
| context → memory | `Rank` | 组装之前。`chat` 与确保会话并行；`regenerate` / `continue` 要等历史给出 query |
| context → memory | `DiscardTurn` | 仅 regenerate，事务成功之后、`done` 之前 |
| context → llm-gateway | `Complete` | 快照已经落库并推出 `inspector` 之后 |
| context → Kafka | `memory.extract`、`memory.reinforce` | `done` 已经 yield 之后 |
| memory → context | `StampExtract` | 提取完成之后，补检查器耗时 |

钉的默认值是 `openrouter` 与 `anthropic/claude-sonnet-5`。脚本化 Provider 不会改钉。备用模型只有在首字之前切换成功时才写回钉。

## 库里的表

会话行保存摘要和模型钉。消息行按会话追加，regenerate 的替换在一个事务里完成。检查器行按回合插入，`StampExtract` 和耗时更新都改同一行，不另建一张耗时表。删角色时 `DeleteByCharacter` 清掉这个角色的会话和消息。

## 代码

| 模块 | 职责 |
|------|------|
| `context_service/orchestrator.py` | 一轮的并行读取、落库、`done`、发布 |
| `context_service/persona/stability.py` | 人设前缀、示例锚点、输出形态、re-anchor |
| `context_service/prompt/templates.py` | 段落顺序 `PROMPT_SECTION_ORDER` |
| `context_service/prompt/builder.py` | 记忆块和摘要块怎么写进 prompt |
| `context_service/context/assembler.py` | 裁剪顺序，以及真正发给模型的消息列表 |
| `context_service/inspections.py` | 检查器快照和 `stamp_extract` |
| `context_service/transcript.py` | 会话、消息、摘要、钉 |
| `context_service/adapters.py` | 把上面这些接到 gRPC stub 和 Kafka `publish` |
| `context_service/server.py` | gRPC 服务，启动时建库并 `ensure_topics()` |

人设字符串、段落顺序和裁剪都不要写进 chat 或 Web。改 prompt 时改上表里的文件。队列记录的字段见 [queue.md](../queue.md)，一轮的时序见 [chat-turn.md](../chat-turn.md)。
