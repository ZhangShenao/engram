# Engram — Harness 与微服务架构

> **产品名**：Engram  
> **版本**：Phase 1（海外 Web 纯文字角色扮演）  
> **读者**：产品负责人与实现者  
> **运行时**：Python 3.12 微服务 + Next.js Web。无 Kubernetes。

Engram 的 **Harness** 是我们自己的角色扮演编排服务，不是第三方产品。它负责组装 prompt、维持人设稳定与 token 预算、检索记忆、调用模型，并写回记忆与滚动摘要。角色卡、会话、记忆各自是它调用的独立服务。Web 只访问 Gateway。

---

## 1. 为什么是 Harness，再加上这些服务

Phase 1 的行为（人设不可被裁掉、槽位只取代 `user_name`、滚动摘要只吃被挤出的 turn、无密钥仍可演示）必须有一个明确的编排者。若把这些规则散落在 Web 的 API Route 里，裁剪顺序和记忆写入会跟路由绑死，也无法单独测试。

拆成五个进程，是为了把**谁拥有数据**和**谁做决定**分开：

| 服务 | 为什么单独存在 |
|------|----------------|
| **gateway** | Web 的唯一入口。鉴权以后可以只加在这里；现在它只做转发、CORS，以及启动时的种子引导。 |
| **character** | 角色卡是相对稳定的主数据，和某一轮聊天无关。 |
| **conversation** | 会话、原文消息、滚动摘要是时间线。摘要的文本归会话服务保存，但**何时追加**由 Harness 决定。 |
| **memory** | 提取、排序、槽位取代、用户编辑/删除都作用在记忆上。已删除行只留在这个库里，不会被别的服务“恢复”。 |
| **harness** | 唯一知道完整 prompt 长什么样的服务。它调用上面三者，再调用 OpenRouter 或脚本化 Provider。 |

共享包 `packages/engram_contracts` 只有 Pydantic 契约（角色卡、记忆、上下文层、常量）。算法留在拥有它的服务里。

---

## 2. 服务边界

每个服务是独立的 FastAPI 进程，有 `GET /health`，以及自己的 PostgreSQL 数据库。一台本地 Postgres，五个库，互不共享表。服务之间只走 HTTP（httpx），不共享数据库连接。

| 服务 | 端口 | 数据库 | 拥有的决策 | 不做什么 |
|------|------|--------|------------|----------|
| gateway | 18410 | `engram_gateway` | 对外路由、启动时种子引导、请求日志（不含正文、不含密钥） | 不组装 prompt，不写记忆 |
| character | 18411 | `engram_character` | 角色卡 CRUD、空库种子（Lyra、Zero、Mara） | 不保存消息 |
| conversation | 18412 | `engram_conversation` | 会话、消息、滚动摘要文本、最近会话列表 | 不决定裁掉哪些 turn |
| memory | 18413 | `engram_memory` | 提取、排序、槽位取代、用户改/删 | 不调用聊天模型生成回复 |
| harness | 18414 | `engram_harness` | 上下文分层与裁剪、prompt 模板、模型调用、检查器快照 | 不直接对外给浏览器 |
| web | 18415 | 无 | Character.AI 式交互的英文 UI | 不实现业务规则；请求打到 gateway |

内部 URL 用环境变量：`CHARACTER_URL`、`CONVERSATION_URL`、`MEMORY_URL`、`HARNESS_URL`，默认即上表的 `127.0.0.1` 端口。

### 2.1 Gateway（Web 唯一公开 API）

- `GET /api/characters`、`POST /api/characters`、`GET|PUT|DELETE /api/characters/{id}`
- `GET /api/chats` 最近会话
- `GET /api/chats/{characterId}` 会话与消息
- `POST /api/chats/{characterId}/stream` 新的一轮（SSE）
- `POST /api/chats/{characterId}/regenerate` 重写最后一条助手消息（SSE）
- `POST /api/chats/{characterId}/continue` 续写（SSE）
- `GET /api/memories/{characterId}`、`PATCH /api/memories/{memoryId}`、`DELETE /api/memories/{memoryId}`
- `GET /api/inspector/{characterId}` 最近一次检查器快照

用户 id 固定为 `local`。没有注册登录。

### 2.2 Character

`GET|POST /characters`，`GET|PUT|DELETE /characters/{id}`，`POST /internal/seed`（空库才插入三个种子角色）。

### 2.3 Conversation

- `POST /sessions/ensure`：按 `(character_id, user_id)` 取或建会话
- `GET /sessions/by-character/{characterId}`
- `GET|POST /sessions/{id}/messages`
- `DELETE /sessions/{id}/messages/last-assistant`：仅当存在用户消息时删除最后一条助手消息（供 regenerate）
- `GET /sessions/{id}/summary`、`POST /sessions/{id}/summary/append`
- `GET /sessions/recent`
- `POST /internal/ensure-greeting`：会话尚无消息时写入角色 greeting
- `DELETE /sessions/by-character/{characterId}`

摘要追加时保留末尾约 4000 字符，与 Phase 1 一致。

### 2.4 Memory

- `GET /memories`：活跃记忆（无 `deleted_at`、无 `superseded_by_id`）
- `POST /memories/rank`：按 salience、新近度、词面相关度排序
- `POST /memories/extract`：从一轮对白提取候选，解析槽位，必要时取代，再插入
- `PATCH /memories/{id}`、`DELETE /memories/{id}`（软删）
- `DELETE /memories`：按角色清空（删角色时）

无 `OPENROUTER_API_KEY` 时用确定性提取器；有密钥时用 OpenRouter JSON 提取。提取失败返回空列表，不阻断聊天。

### 2.5 Harness

- `POST /turns/stream`：编排一整轮，SSE 事件 `inspector`、`chunk`、`done`、`error`
- `GET /inspections/{characterId}`：该角色最近一次检查器快照

Prompt 与裁剪代码：

- `services/harness/harness_service/persona/stability.py`
- `services/harness/harness_service/prompt/templates.py`、`builder.py`
- `services/harness/harness_service/context/assembler.py`、`tokens.py`
- `services/harness/harness_service/llm/`（OpenRouter 与脚本化 Provider）
- `services/harness/harness_service/orchestrator.py`

排序函数的实现位于 `services/memory/memory_service/domain/rank.py`。Harness 在组装时调用同一实现（保证单测与线上一致），检索到的记忆行本身来自 Memory 服务的 HTTP 接口。

---

## 3. 一轮聊天的同步请求路径

`mode=chat`。浏览器通过 Next 同源代理访问 Gateway，Gateway 把 SSE 原样转给浏览器。

```
Web  POST /gateway/api/chats/{characterId}/stream  { message }
 └─ Gateway  POST harness /turns/stream
      1. Character   GET  /characters/{id}
      2. Conversation POST /sessions/ensure
      3. Conversation POST /sessions/{id}/messages   （写入 user 消息）
      4. Conversation GET  /sessions/{id}/messages   （verbatim 不含刚写入的这条 user）
      5. Conversation GET  /sessions/{id}/summary
      6. Memory      POST /memories/rank            （query = 本轮 user 文本）
      7. Harness 本地 assemble_context
         （人设 / 记忆 / 摘要 / 最近 turn / reanchor / hint，超预算按第 7 节裁剪）
      8. 写入 engram_harness 检查器快照，先把 inspector 事件推下去
      9. OpenRouter 或脚本化 Provider 流式生成
     10. Conversation POST /sessions/{id}/messages  （写入 assistant）
     11. Memory       POST /memories/extract
     12. 若 evictedTurns 非空：
         Conversation POST /sessions/{id}/summary/append
         （只追加被挤出 verbatim 窗口的 turn 原文）
     13. SSE done
```

`regenerate`：不新增 user 消息。必须已有 user 消息，且最后一条是 assistant。verbatim 不含最后一条 user，也不含待替换的 assistant。新回复完整生成之后才删除旧 assistant；生成失败时旧回复还在。

`continue`：不落库续写指令，也不把该指令交给记忆提取。verbatim 为全部历史；发给模型的最后一条 user 是续写指令（不计入可裁剪窗口）。排序 query 用上一条真实 user 文本。新的 assistant 消息另起一条。

SSE 形状：

```
data: {"type":"inspector","inspector":{...}}
data: {"type":"chunk","text":"..."}
data: {"type":"done","messageId":"...","content":"...","sessionId":"...","provider":"scripted|openrouter"}
data: {"type":"error","message":"..."}
```

---

## 4. 数据归属

五个库在同一台 PostgreSQL 上，互不读取对方的表。连接串分别是 `CHARACTER_DATABASE_URL`、`CONVERSATION_DATABASE_URL`、`MEMORY_DATABASE_URL`、`HARNESS_DATABASE_URL`、`GATEWAY_DATABASE_URL`。容器里每个进程只拿到自己的 `DATABASE_URL`（主机名 `postgres`）。

### 4.1 `engram_character` · `characters`

`name`, `tagline`, `description`, `personality`, `scenario`, `example_dialogues`（JSON）, `greeting`, `speech_style`, `boundaries`, 时间戳。

### 4.2 `engram_conversation`

- `chat_sessions`：`(character_id, user_id)` 唯一
- `messages`：`role` = `user` | `assistant`
- `session_summaries`：滚动摘要正文

### 4.3 `engram_memory` · `memories`

| 字段 | 说明 |
|------|------|
| `type` | `fact` \| `relationship` \| `promise` \| `boundary` \| `plot` |
| `text` | 正文 |
| `salience` | 0–1 |
| `slot` | 可空。Phase 1 仅 `user_name` 会触发取代 |
| `source_turn_id` | 来源 assistant 消息 |
| `superseded_by_id` | 被同槽新记忆取代 |
| `deleted_at` | 软删。删除后不清除标记，检索永远跳过 |

### 4.4 `engram_harness` · `inspections`

每轮保存分层内容、token 估算、裁剪日志，供刷新后的 Context 面板读取。不保存 API 密钥。

### 4.5 `engram_gateway` · `request_log`

方法、路径、状态码、时间。不记录 body 与请求头。

---

## 5. 本地运行拓扑

不依赖旧的 Node 单体（端口 43123）。两种方式都先启动 **一台 PostgreSQL**，等到它接受连接，再启动**五个 Python 进程 + Web**。

```bash
./scripts/dev.sh
```

`scripts/dev.sh` 会加载仓库根目录的 `.env`。本机有可用的 Docker 时，它执行 `docker compose up -d postgres` 并等待健康检查。否则它启动本机 PostgreSQL 集群（需要时安装 `postgresql`），创建角色 `engram` 和五个库，再用 `pg_isready` 等到 `127.0.0.1:5432` 接受连接。

或：

```bash
docker compose up --build
```

Compose 里的 `postgres` 服务使用官方 `postgres:16` 镜像，`scripts/init-postgres.sql` 在首次初始化时创建五个库。应用服务 `depends_on` 该服务的 healthcheck（`pg_isready`）。

```
浏览器
  └─ Web :18415  （Next.js Route Handler 将 /gateway/* 转到 Gateway）
       └─ Gateway :18410          engram_gateway
            ├─ Character    :18411   engram_character
            ├─ Conversation :18412   engram_conversation
            ├─ Memory       :18413   engram_memory
            └─ Harness      :18414   engram_harness
                 └─ https://openrouter.ai/api/v1/chat/completions
                    （无 OPENROUTER_API_KEY 时不发出）

Postgres :5432
  engram_gateway / engram_character / engram_conversation / engram_memory / engram_harness
```

端口故意避开 3000、5173、8080、43123。

Gateway 启动时会重试调用 Character 的 `/internal/seed`，再为每个尚无消息的角色写入 greeting。因此第一次打开即可和 Lyra、Zero、Mara 聊天。

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

Phase 1 唯一内置槽位：`user_name`（`services/memory/memory_service/domain/slots.py`）。`infer_memory_slot` 只在 fact 且文本像姓名时返回该槽。

新增槽位：在 `MEMORY_SLOTS` 增加常量，在 `infer_memory_slot`（或提取器的 `slot` 字段）返回它。`find_superseded_memory` 已按槽匹配。补一条单测：同槽取代，不同槽并存。

排序权重：salience 0.45、recency 0.35、relevance 0.20。已删除与已取代的记忆不参与。

### 7.4 无密钥

`OPENROUTER_API_KEY` 为空时，Harness 使用脚本化流式 Provider，Memory 使用确定性提取器。UI、记忆面板、检查器仍然可用。

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

记忆提取在有密钥时走同一 base URL、同一模型与同一对产品头，`temperature` 0.2，要求 JSON。

---

## 9. 前端

`web/`：Next.js、TypeScript、Tailwind、shadcn/ui。英文文案。深色全高壳层。

- 左栏：Engram、新建角色、角色列表、最近会话。窄屏改为抽屉。
- 中间：名称与 tagline、流式气泡、钉在底部的输入框。
- 最后一条助手消息：Regenerate、Continue。
- 创建/编辑角色是独立的专注流程，不是聊天里的一块侧栏。
- 仅 Engram 提供的右侧滑层：记忆（编辑/删除）与上下文检查器（分层、token 估算、裁剪日志）。

Web 不直连四个内部服务。

---

## 10. 测试

本地：

```bash
pytest
```

覆盖裁剪顺序、人设保留、`evictedTurns`、记忆排序、槽位取代，以及 prompt 段落顺序。这些测试不启动进程、不需要 API 密钥。`OPENROUTER_API_KEY` 为空时走脚本化 Provider。

CI（`.github/workflows/ci.yml`）在 pull request 和推送到 `main` 时跑同一套 `pytest`。工作流启动 PostgreSQL 16，用 `scripts/init-postgres.sql` 创建 `engram_gateway`、`engram_character`、`engram_conversation`、`engram_memory`、`engram_harness`，并把五个服务的 `DATABASE_URL` 指到这些库。`OPENROUTER_API_KEY` 置空。随后在 `web/` 执行 `npm ci` 和 `npm run build`。不读取仓库密钥。新的提交会取消同一 ref 上尚未结束的运行。`main` 禁止直接推送、强推和删除，没有旁路。变更必须走 pull request，并且名为 `ci` 的检查通过后才能合并，分支还要和 `main` 保持同步。不要提交 `.env`。

---

*仓库内的规范以本文为准。*
