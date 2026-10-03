# Engram 开发规范

Engram 是五个 Python 服务加上一个 Next.js Web。Harness 是我们自己的角色扮演编排服务，不是第三方产品。

五个服务是 gateway、character、conversation、memory、harness。浏览器只访问 gateway。Web 把 `/gateway/*` 代理到 gateway。

## 开始一个新需求

先同步远程 `main`，再为这个需求单独建一个 git worktree。不要在当前工作区里直接改新需求。

在主仓库目录执行：

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git worktree add -b <branch> ../engram-<short-name> main
```

`<branch>` 从更新后的 `main` 拉出。`<short-name>` 用简短英文，目录放在仓库旁边，例如 `../engram-stream-latency`。

当前工作区有未提交改动、不能切到 `main` 时，不要把这些改动混进新需求。先 `git fetch origin`。只有本地 `main` 是 `origin/main` 的祖先时，才用 `git branch -f main origin/main` 把它快进。`main` 上有未推送的本地提交时停下来，不要强行覆盖。然后：

```bash
git worktree add -b <branch> ../engram-<short-name> main
```

之后的编辑、测试和提交都在新目录里做。一个需求一个 worktree。需求合并或放弃后：

```bash
git worktree remove ../engram-<short-name>
```

## 服务边界

- `character` 拥有角色卡。`conversation` 拥有会话、消息和摘要正文。`memory` 拥有提取、排序、槽位取代和用户编辑。`harness` 拥有 prompt 组装、token 预算、模型调用和检查器快照。`gateway` 只做对外入口、转发和启动时的种子引导。
- 服务之间走 HTTP。每个服务有自己的 Postgres 库：`engram_gateway`、`engram_character`、`engram_conversation`、`engram_memory`、`engram_harness`。它们在同一台本地 Postgres 上，不共享表，也不共享数据库连接。
- `packages/engram_contracts` 只放 Pydantic 形状和共享常量。不要把 prompt 或排序算法放进去。

## Prompt 放在哪里

- 人设前缀、示例锚点、输出形态、re-anchor：`services/harness/harness_service/persona/stability.py`
- 段落顺序：`services/harness/harness_service/prompt/templates.py`
- 记忆和摘要块：`services/harness/harness_service/prompt/builder.py`
- 裁剪顺序，以及真正发给模型的消息列表：`services/harness/harness_service/context/assembler.py`
- 模型调用：`services/harness/harness_service/llm/`
- 一轮聊天：`services/harness/harness_service/orchestrator.py`

不要把 system prompt 字符串写进 gateway 或 Web。

聊天流式请求必须带 `Accept: text/event-stream` 和 `Accept-Encoding: identity`。gzip 会把整段 SSE 攒到生成结束才解开。Gateway 向 Harness 拉流时同样不要压缩。

## 增加记忆槽位

1. 在 `services/memory/memory_service/domain/slots.py` 的 `MEMORY_SLOTS` 里加常量。
2. 让 `infer_memory_slot` 在对应的类型和正文上返回它，或者在提取候选上设置 `slot`。
3. `find_superseded_memory` 已经按槽位匹配。同一槽位取代；不同槽位并存。
4. 确定性提取器和 LLM 提取器的 prompt 都要认识这个槽位。
5. 加一条 pytest：同槽两条记忆会取代；一条无关事实不会。

Phase 1 只有一个槽位：`user_name`。

## 增加或更换模型

1. 把 `OPENROUTER_MODEL` 设成 `https://openrouter.ai/api/v1/models` 上存在的 id。
2. 产品默认写在 `packages/engram_contracts/engram_contracts/constants.py`，当前是 `anthropic/claude-sonnet-5`。只有确实要改产品默认时才改这个常量。
3. 聊天和记忆提取都保留 `HTTP-Referer` 和 `X-Title: Engram`。
4. 保留无密钥路径：Harness 用 `ScriptedLLMProvider`，Memory 用 `DeterministicMemoryExtractor`。

## 测试和本地运行

在仓库根目录、虚拟环境已激活时：

```bash
pytest
```

`OPENROUTER_API_KEY` 留空，这样走脚本化 Provider。CI 用 PostgreSQL 16 和五个服务库跑同一套 `pytest`，然后构建 `web/`。

```bash
./scripts/dev.sh
```

Web 在 http://127.0.0.1:18415。不要占用 3000、5173、8080 或 43123。

## Git

1. 分支从更新后的 `main` 拉出，放在独立 worktree 里。不要把提交直接推到 `main`。规则集禁止直接推送、强推和删除，没有旁路。
2. 开 pull request。模板要求摘要、如何测试，以及检查清单。
3. CI（`.github/workflows/ci.yml`）必须通过。必需检查的名字是 `ci`。分支要和 `main` 保持同步。工作流会取消被取代的运行，不需要密钥。
4. 不要提交 `.env`。
5. `ci` 变绿之后再合并。
