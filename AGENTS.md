# Engram 开发规范

Engram 是四个 Python 服务加上一个 Next.js Web。上下文编排在 context-service 里，不是第三方产品。

四个服务是 chat、context、memory、llm-gateway。浏览器只访问 chat。Web 把 `/gateway/*` 代理到 chat。

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

- `chat` 拥有角色卡和对外 HTTP（CORS、请求日志、种子引导）。`context` 拥有会话、消息、滚动摘要、裁剪、prompt、检查器快照。`memory` 拥有提取、排序、层级槽位、衰减、遗忘、冲突解决和用户编辑。`llm-gateway` 拥有模型接入、会话钉和首字前的失败切换。
- 浏览器只访问 chat-service 的 HTTP。内部服务走 gRPC。记忆提取和强化走 Kafka，主题是 `memory.extract` 和 `memory.reinforce`，消费组是 `engram-memory`。第五次仍失败的作业写入 `memory.dead`，不再执行。遗忘不是队列消息，而是 memory 消费循环在空闲时做的扫描。每个服务有自己的 Postgres 库：`engram_chat`、`engram_context`、`engram_memory`。它们在同一台本地 Postgres 上，互不共享表，也不共享数据库连接。不要再创建 `engram_mq`。队列的监听、记录格式和至少一次语义写在 `docs/queue.md`。宿主机和 CI 用 `KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092`，Compose 网络里的 context 和 memory 用 `kafka:19092`。
- `packages/engram_contracts` 只放 Pydantic 形状和共享常量。不要把 prompt 或排序算法放进去。

## Prompt 放在哪里

- 人设前缀、示例锚点、输出形态、re-anchor：`services/context/context_service/persona/stability.py`
- 段落顺序：`services/context/context_service/prompt/templates.py`
- 记忆和摘要块：`services/context/context_service/prompt/builder.py`
- 裁剪顺序，以及真正发给模型的消息列表：`services/context/context_service/context/assembler.py`
- 模型调用：`services/llm_gateway/llm_gateway_service/`
- 一轮聊天：`services/context/context_service/orchestrator.py`

不要把 system prompt 字符串写进 chat 或 Web。

聊天流式请求必须带 `Accept: text/event-stream` 和 `Accept-Encoding: identity`。gzip 会把整段 SSE 攒到生成结束才解开。llm-gateway 访问 OpenRouter 时同样不要压缩。chat 到 context 的内部流走 gRPC，不启用压缩。

## 增加记忆槽位

1. 在 `services/memory/memory_service/domain/slots.py` 的 `MEMORY_SLOTS` 里加常量。
2. 让 `infer_memory_slot` 在对应的类型和正文上返回它，或者在提取候选上设置 `slot`。
3. `find_superseded_memory` 已经按槽位匹配。同一槽位取代；不同槽位并存。
4. 确定性提取器和 LLM 提取器的 prompt 都要认识这个槽位。
5. 加一条 pytest：同槽两条记忆会取代；一条无关事实不会。

槽位是点分路径。同路径取代，父子和兄弟并存。姓名槽是 `user.name`（`user_name` 仍作为别名）。另外有 `user.language`、`relationship.status`、`boundary.limit`、`promise.commitment`。排序使用时间衰减后的 salience。超过遗忘窗口且衰减后过低的记忆标为 forgotten，不再参与排序。

## 增加或更换模型

1. 把 `OPENROUTER_MODEL` 设成 `https://openrouter.ai/api/v1/models` 上存在的 id。
2. 产品默认写在 `packages/engram_contracts/engram_contracts/constants.py`，当前是 `anthropic/claude-sonnet-5`。只有确实要改产品默认时才改这个常量。
3. 聊天和记忆提取都保留 `HTTP-Referer` 和 `X-Title: Engram`。
4. 保留无密钥路径：llm-gateway 用 `ScriptedLLMProvider`，Memory 用 `DeterministicMemoryExtractor`。脚本化 Provider 不是故障切换的目标。

## 依赖和测试

后端依赖用 uv 管理。运行时依赖写在 `pyproject.toml` 的 `[project].dependencies`，pytest、ruff、pre-commit 这类开发工具写在 `dev` 依赖组。`uv.lock` 锁定全部版本，必须提交。不要再加 `requirements.txt`，也不要用 `pip install`。

```bash
uv sync                  # 按 uv.lock 建或更新 .venv
uv add <package>         # 加运行时依赖
uv add --dev <package>   # 加开发工具
```

改了依赖就把 `pyproject.toml` 和 `uv.lock` 一起提交。CI 和 Docker 镜像都用 `uv sync --frozen`，锁文件过期会直接失败。

在仓库根目录：

```bash
uv run pytest
```

`OPENROUTER_API_KEY` 留空，这样走脚本化 Provider。CI 用 PostgreSQL 16 和五个服务库跑 lint 和质量检查，然后构建 `web/`。

质量检查是 `uv run python scripts/quality_report.py`。它跑全部 pytest，并加上三道门禁：语句覆盖率不低于 65%，代码重复率不高于 5%，`ruff check` 和 `ruff format --check` 没有问题。覆盖率统计五个服务和 `engram_contracts`。重复率用 jscpd，扫 `services/`、`packages/` 和 `web/src`，至少 8 行、50 个 token 才计一处。报告写在 `reports/quality.md`，这个目录不提交。

## Lint 和格式化

Python 用 ruff 做 lint 和格式化，配置在 `pyproject.toml`：行宽 100，目标 Python 3.12，含 import 排序。Web 用现有的 ESLint 配置。

`git commit` 前由 pre-commit 自动检查，配置在 `.pre-commit-config.yaml`。每个克隆装一次钩子，所有 worktree 共用：

```bash
uv run pre-commit install
```

钩子会修尾随空格和文件末尾换行，检查 YAML、TOML、JSON，检查 `uv.lock` 和 `pyproject.toml` 一致，对暂存的 Python 文件跑 `ruff check --fix` 和 `ruff format`，`web/src` 有改动时跑 ESLint。钩子改了文件，提交会中止；检查改动后重新 `git add` 再提交。不要用 `--no-verify` 跳过。

```bash
uv run pre-commit run --all-files   # 和 CI 一样跑全部钩子
```

CI 的 `ci` 任务先跑同一套 pre-commit 钩子，质量报告里也有一行“代码规范”。任一处不过，`ci` 失败。

## 本地运行

```bash
./scripts/dev.sh
```

有 Docker 时它用 Docker Compose 构建并启动整套服务，等所有容器健康后返回；`./scripts/dev.sh logs` 看日志，`./scripts/dev.sh down` 停止。没有 Docker，或用 `./scripts/dev.sh local`，则在本机进程里跑，这时需要先装好 uv，脚本会执行 `uv sync --frozen`。本机 5432 已被占用时，设置 `POSTGRES_PORT` 换一个宿主端口。

Web 在 http://127.0.0.1:18415。不要占用 3000、5173、8080 或 43123。

## Git

1. 分支从更新后的 `main` 拉出，放在独立 worktree 里。不要把提交直接推到 `main`。规则集禁止直接推送、强推和删除，没有旁路。
2. 开 pull request。模板要求摘要、如何测试，以及检查清单。
3. CI（`.github/workflows/ci.yml`）必须通过。必需检查的名字是 `ci`。分支要和 `main` 保持同步。工作流会取消被取代的运行，不需要仓库密钥；评论用自带的 `GITHUB_TOKEN`。每次检查结束后，在对应的 pull request 上更新一条工程质量报告。推送到 `main` 时，报告写到产生这次推送的 pull request 上；没有关联的 pull request 时，报告留在该次 Actions 的摘要里。门禁不过，`ci` 失败。
4. 不要提交 `.env`。
5. `ci` 变绿之后再合并。
