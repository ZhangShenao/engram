# Engram — 上下文编排与服务边界

> **产品名**：Engram
> **读者**：产品负责人与实现者
> **运行时**：Python 3.12。chat-service 对外 HTTP，其余内部服务 gRPC。无 Kubernetes。

浏览器只访问 chat-service。Web 把 `/gateway/*` 代理到它。context-service 拥有聊天记录、prompt 和检查器。llm-gateway 是唯一出站到模型的进程。memory-service 拥有记忆。提取和强化通过 Kafka 异步完成，设计见 [queue.md](queue.md)。

---

## 1. 四个服务

| 服务 | 端口 | 数据库 | 拥有 | 不做什么 |
|------|------|--------|------|----------|
| chat | 18410 HTTP | `engram_chat` | 对外路由、CORS、角色卡、请求日志、启动种子 | 不保存消息，不组装 prompt |
| context | 18411 gRPC | `engram_context` | 会话、消息、滚动摘要、裁剪、prompt、检查器快照、regenerate 替换事务、会话上的模型钉 | 不保存角色主数据，不直接给浏览器 |
| memory | 18413 gRPC | `engram_memory` | 提取、排序、层级槽位、衰减、遗忘、冲突解决、用户改删 | 不生成聊天回复 |
| llm-gateway | 18414 gRPC | 无 | OpenRouter 与脚本化 Provider、首字前的失败切换 | 不保存会话 |
| web | 18415 | 无 | 英文 UI | 不实现业务规则 |

三个 Postgres 库各属一个服务，互不共享表，也不共享连接。消息队列是单独的 Kafka broker，不属于任何一个业务库。context 发布，memory 消费。以前用于队列的 `engram_mq` 库已经不再创建。

角色卡由 chat 在每次回合请求里交给 context。context 不回调 chat 取角色，避免回合路径上的反向依赖。chat 删除角色时的顺序是：先让 memory 按角色清空，再让 context 删会话，最后删自己的角色卡。中途失败会留下已经清掉的下游数据，角色卡仍在，调用方可以重试删除。

## 2. 通信

同步用 gRPC，异步用 Kafka。内部服务不对浏览器暴露 HTTP。chat 的 `/health` 是给 Compose 和本机脚本用的 HTTP 探针。context、memory、llm-gateway 的进程健康检查是各自的 `Check` RPC，不另开 HTTP 端口。

gRPC 通道在进程里复用。chat 到 context 的回合流不压缩。压缩会把 SSE 攒到生成结束才交给浏览器。llm-gateway 访问 OpenRouter 时同样发送 `Accept-Encoding: identity`。

| 调用 | 方式 |
|------|------|
| chat → context 一轮聊天 | 服务端流 |
| chat → context 读历史、greeting、删会话、检查器 | 一元 RPC |
| chat → memory 列表、改、删、按角色清空 | 一元 RPC |
| context → memory 排序、按 turn 丢弃 | 一元 RPC |
| context → llm-gateway 补全 | 服务端流 |
| memory → llm-gateway JSON 提取 | 一元 RPC |
| 回合结束后的提取、被装进 prompt 的记忆强化 | Kafka `memory.extract`、`memory.reinforce` |
| 第五次仍失败的作业 | Kafka `memory.dead`，不再执行 |
| 摘要追加 | 仍在同步路径里，context 自己写自己的库 |
| 遗忘扫描 | memory 消费循环的空闲周期，不是一条消息 |

提取失败只在 Kafka 里重试，不另发 SSE。`done` 的 `extractMs` 仍为空。memory 提取结束后调用 context 的 `StampExtract`，检查器快照才补上耗时。发布本身失败只记日志：`done` 已经写出，不能再把这一轮改成错误事件。重试、死信、分区和至少一次的语义见 [queue.md](queue.md)。

被 regenerate 替换掉的 turn 会写入 `discarded_turns`。之后才到达的提取看到这个墓碑就不再插入，因此提取不必挡在 `done` 前面。

启动顺序跟着依赖走。llm-gateway 没有数据库，也没有队列。memory 要等 Postgres 和 Kafka 都健康，因为它既有记忆库，又要开始消费。context 要等 memory 和 llm-gateway，因为它在回合里同步调用排序，并在回合末尾发布作业。chat 最后等 context。Web 只等 chat 的 `/health`。本机 `scripts/dev.sh local` 用同样的顺序拉起进程，差别是 Postgres 和 Kafka 可以来自 Compose，业务进程在宿主机。

## 3. 一轮 chat

1. chat 读本地角色卡，把角色卡 JSON 和用户文本交给 context `StreamTurn`。
2. context 并行：确保会话，按本轮用户文本向 memory 排序。会话 id 到手后开始读摘要，与排序重叠；排序结束后写入用户消息并读历史。
3. 本地 `assemble_context`。检查器快照先落库再推出 `inspector`。快照是这一轮发给模型的打包结果（分层、token、裁剪日志、被挤出的 turn），不是第二份完整消息表。
4. 用会话上的 `(provider, model)` 钉调用 llm-gateway。无密钥时网关直接走脚本化 Provider，不改会话钉。
5. 有密钥且首字尚未吐出时，网关可以按备用链整轮换一家。已经有 token 之后失败就结束这一轮，不接半句话。换成功后 context 把会话钉改成实际用的那一家。本期备用链只有 OpenRouter。
6. 写入 assistant。有 `evictedTurns` 时追加滚动摘要。推出 `done`。
7. 发布提取和强化消息。两条记录都得到 broker 确认后，这一轮的 gRPC 流结束。提取在 memory 进程里继续，不挡输入框。

`regenerate` 与 `continue` 的 prompt 规则不变。替换仍是 context 里的一个事务：写入新回复并删除旧回复。成功后、`done` 之前，按旧回复 id 丢弃记忆。

## 4. 模型钉

钉存在 `chat_sessions.llm_provider` 和 `llm_model`，默认 `openrouter` + `anthropic/claude-sonnet-5`。llm-gateway 不存会话。同一次会话默认打到同一个 Provider 和模型。

## 5. 记忆

槽位是点分路径。同路径取代，不同路径并存。`user_name` 是 `user.name` 的别名。

内置路径：`user.name`、`user.language`、`relationship.status`、`boundary.limit`、`promise.commitment`。

排序用衰减后的 salience。衰减锚点是 `last_reinforced_at`，没有强化过则用 `created_at`。半衰期 30 天，也就是年龄每增加 30 天，有效 salience 乘 0.5。排序权重仍是有效 salience 0.45、recency 0.35、词面 relevance 0.20。recency 在 30 天时线性降到 0。relevance 是查询词和记忆正文的词面重叠，没有向量。

创建已超过 14 天、且衰减后 salience 低于 0.2 的活跃记忆会被标成 forgotten，不再参与排序和列表。这条扫描由 memory 的消费循环在空闲时执行，大约每 60 秒一次空轮询之后跑一轮，不是 Kafka 主题。

被装进 prompt 的记忆通过 `memory.reinforce` 强化：salience 增加 0.05，封顶 1，并刷新 `last_reinforced_at`，同时清掉 forgotten 标记。正文几乎相同的新候选不另插一行，而是强化已有行。同一槽位的新事实会取代旧行；不同槽位并存。

---

## 6. 不在范围内

- 用户注册 / 登录、多租户、云同步
- 语音、图片生成、角色立绘
- 社交动态、关注、公开广场
- 原生 iOS / Android
- 向量库 / Embedding（相关度只有词面重叠）
- 多人 / 群聊
- Kubernetes、服务网格、集中式内容审核管线（只有角色卡 `boundaries` 约束模型）
- 付费与多模型路由（环境变量指定单一 OpenRouter 模型）

---

## 7. 必须保留的 Phase 1 行为

### 7.1 人设稳定

稳定前缀始终包含身份、边界、至少一条示例对话、输出形态（`*动作*` + 台词）。Re-anchor 与生成提示不裁。实现：`persona/stability.py`，由 `context/assembler.py` 调用。

### 7.2 上下文层与裁剪顺序

默认预算 `4096`。估算 `ceil(字符数 / 4)`。

| 层 | 裁剪 |
|----|------|
| persona | 最后才减少示例条数，且 ≥ 1。核心人设与 boundaries 永不丢 |
| memories | 可丢低分记忆 |
| summary | 可截断 |
| recent | **最先**丢最旧的 turn pair，并记入 `evictedTurns` |
| reanchor、hint | 不丢 |

超预算顺序：

1. 移除最旧 verbatim turn pair → `evictedTurns`
2. 缩短 rolling summary
3. 减少已装入的记忆
4. 减少示例对话（仍 ≥ 1）
5. 永不丢弃：人设核心、`boundaries`、reanchor、hint

刚发送的 user 文本不在 verbatim 窗口里，因此不会被写进摘要。滚动摘要**只**追加 `evictedTurns`。

### 7.3 记忆

同类型多条可以并存。取代仅当候选带 `supersedesMemoryId`，或与某条活跃记忆同属一个槽位。

槽位路径见第 5 节（`services/memory/memory_service/domain/slots.py`）。`user.name` 在 fact 且文本像姓名时推断出来。

新增槽位：在 `MEMORY_SLOTS` 增加常量，在 `infer_memory_slot`（或提取器的 `slot` 字段）返回它。`find_superseded_memory` 已按槽匹配。补一条单测：同槽取代，不同槽并存。

排序权重：衰减后的 salience 0.45、recency 0.35、relevance 0.20。已删除、已取代、已遗忘的记忆不参与。

### 7.4 无密钥

`OPENROUTER_API_KEY` 为空时，llm-gateway 使用脚本化流式 Provider，Memory 使用确定性提取器。UI、记忆面板、检查器仍然可用。

### 7.5 Prompt 段落顺序

`PROMPT_SECTION_ORDER`：`persona_identity`、`boundaries`、`style_anchors`、`output_shape`、`memories`、`rolling_summary`、`reanchor`、`recent_turns`、`generation_hint`。

---

## 8. 模型

Chat Completions：`https://openrouter.ai/api/v1/chat/completions`。

默认模型 id 为 **`anthropic/claude-sonnet-5`**。该 id 已对照 OpenRouter 公开模型列表确认存在，因此作为 `OPENROUTER_MODEL` 的默认值，而不是改写成别的 Sonnet。

请求头：

- `Authorization: Bearer <OPENROUTER_API_KEY>`
- `HTTP-Referer: https://github.com/ZhangShenao/engram`
- `X-Title: Engram`

记忆提取在有密钥时经 llm-gateway 走同一模型与同一对产品头，`temperature` 0.2，要求 JSON。

---

## 9. 前端

`web/`：Next.js、TypeScript、Tailwind、shadcn/ui。英文文案。深色全高壳层。

- 左栏：Engram、新建角色、角色列表、最近会话。窄屏改为抽屉。
- 中间：名称与 tagline、流式气泡、钉在底部的输入框。
- 最后一条助手消息：Regenerate、Continue。
- 创建/编辑角色是独立的专注流程，不是聊天里的一块侧栏。
- 仅 Engram 提供的右侧滑层：记忆（编辑/删除）与上下文检查器（分层、token 估算、裁剪日志）。

Web 不直连 context、memory、llm-gateway。

---

## 10. 测试

本地：

```bash
pytest
```

覆盖裁剪顺序、人设保留、`evictedTurns`、记忆排序、槽位取代，以及 prompt 段落顺序。这些测试不启动进程、不需要 API 密钥。`OPENROUTER_API_KEY` 为空时走脚本化 Provider。

CI（`.github/workflows/ci.yml`）在 pull request 和推送到 `main` 时跑 `scripts/quality_report.py`，再构建 `web/`。质量检查包含全部 `pytest`、语句覆盖率（不低于 65%）和代码重复率（不高于 5%）。工作流启动 PostgreSQL 16，用 `scripts/init-postgres.sql` 创建 `engram_chat`、`engram_context`、`engram_memory`，并启动单节点 Kafka 4.2.2。队列测试连 `127.0.0.1:9092`。`OPENROUTER_API_KEY` 置空。检查结束后，在对应的 pull request 上更新一条工程质量报告。不读取仓库密钥；评论使用 Actions 自带的 `GITHUB_TOKEN`。新的提交会取消同一 ref 上尚未结束的运行。`main` 禁止直接推送、强推和删除，没有旁路。变更必须走 pull request，并且名为 `ci` 的检查通过后才能合并，分支还要和 `main` 保持同步。不要提交 `.env`。

队列的集成测试在 `packages/engram_queue/tests`。它们检查领取互斥、退避后再次投递、第五次失败进入 `memory.dead`，以及坏记录被跳过。其余测试不启动 Kafka 客户端。没有密钥时，模型调用走脚本化 Provider，记忆提取走确定性提取器。

---

*仓库内的规范以本文为准。*
