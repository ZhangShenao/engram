# Harness

Engram 自己的角色扮演编排服务，不是第三方产品。它是唯一知道完整 prompt 的进程。

## 职责

- 向 Character、Conversation、Memory 取数
- 用 `context/assembler.py` 分层、估算 token、按固定顺序裁剪
- 调用 OpenRouter；没有 `OPENROUTER_API_KEY` 时用脚本化流式 Provider
- 写回 assistant 消息、在 SSE `done` 之后调用记忆提取、仅在 `evictedTurns` 非空时追加滚动摘要
- 把检查器快照写入数据库 `engram_harness`，一轮结束后补上分段耗时

人设核心、`boundaries`、re-anchor、生成提示不裁。示例对话至少留 1 条。最旧的 verbatim pair 最先被移出，并成为摘要的唯一来源。刚发送的 user 文本不在可裁剪窗口里。

默认模型 id：`anthropic/claude-sonnet-5`。请求带 `HTTP-Referer` 和 `X-Title: Engram`。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | |
| POST | `/turns/stream` | `{characterId, userId, mode, message}`。`mode` 为 `chat`、`regenerate`、`continue`。SSE：`inspector`、`chunk`、`done`、`error` |
| GET | `/inspections/{characterId}?userId=` | 最近一次快照，没有则为 `{inspector: null}` |

`regenerate` 在新回复生成完成之后，用 Conversation 的原子替换写入新回复并删掉旧 assistant。续写产生的最后一条 assistant 只替换自己，更早的 assistant 留在 prompt 里。替换成功后先按 `sourceTurnId` 软删旧记忆，SSE `done` 发出之后再提取新记忆。替换或清除失败时不提取，旧回复在替换失败时还在。记忆顺序来自 Memory 的 rank 响应，Harness 只按 token 预算装箱。`continue` 不把续写指令写进会话或记忆。

一轮请求的并行预取、连接复用和耗时字段见 [chat-turn.md](../chat-turn.md)。

## 数据

`inspections(id, character_id, user_id, session_id, payload_json, created_at)`。快照含分层正文、token 估算、裁剪日志，以及一轮结束后的 `timings`。不含 API 密钥。

Prompt 与裁剪代码：

- `harness_service/persona/stability.py`
- `harness_service/prompt/templates.py`、`builder.py`
- `harness_service/context/assembler.py`
- `harness_service/orchestrator.py`
