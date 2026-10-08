# 消息队列

记忆提取和强化不走同步 RPC。context 在一轮聊天的 `done` 已经写出之后，把两份作业交给 Kafka。memory 用独立的消费循环处理它们。聊天是否结束不取决于提取是否写完。

Postgres 仍保存角色卡、会话和记忆。它不再充当队列。以前的 `engram_mq` 库和 `mq_messages` 表已经去掉。

## 1. 谁发布，谁消费

| 角色 | 进程 | 做什么 |
|------|------|--------|
| 生产者 | context-service | `done` 之后发布 `memory.extract` 和 `memory.reinforce` |
| 消费者 | memory-service | 消费组 `engram-memory`，处理成功后提交偏移 |
| 不参与 | chat、llm-gateway、web | 不连接 broker |

发布失败只记日志。此时 SSE `done` 已经发给浏览器，不能再把这一轮变成 `error`。Kafka 在 `done` 之后不可用时，这一轮的提取和强化会丢掉，下一轮聊天仍然可以进行。

遗忘不是一条消息。memory 的消费循环在连续大约 300 次空轮询（约 60 秒没有作业）时调用 `forget_stale`，把过期且衰减后过低的记忆标成 forgotten。作业一直有的时候，这次扫描会推迟到下一段空闲。

## 2. Broker

本地和 CI 都是单节点 KRaft，不另起 ZooKeeper。镜像是 `apache/kafka:4.2.2`。副本数是 1，每个业务主题 1 个分区，因此同一主题里的作业按写入顺序被同一个消费者读到。

Compose 里的 broker 开了两路监听：

| 监听 | 地址 | 谁用 |
|------|------|------|
| `PLAINTEXT_HOST` | `127.0.0.1:9092` | 宿主机上的进程、pytest、GitHub Actions |
| `PLAINTEXT` | `kafka:19092` | 同一个 Compose 网络里的 context 和 memory |

客户端必须使用自己能解析的那一个地址。容器里如果去连 `127.0.0.1:9092`，连到的是容器自己，不是 broker。宿主机如果只拿到内网广告地址 `kafka:19092`，名字解析也会失败。`KAFKA_BOOTSTRAP_SERVERS` 就是用来选这一路的。

默认值：

| 变量 | 默认 | 何处 |
|------|------|------|
| `KAFKA_BOOTSTRAP_SERVERS` | `127.0.0.1:9092` | 宿主机与 CI |
| 同上 | `kafka:19092` | Compose 里的 context、memory |
| `KAFKA_GROUP_ID` | `engram-memory` | 只有测试会改成一次性的组，避免和正在跑的服务抢分区 |

认证没有打开。broker 和四个服务处在同一台机器的信任边界里，和以前本机 Postgres 的假设相同。不要把 9092 暴露到公网。

数据目录在 Compose 卷 `engram-kafka`。`scripts/dev.sh down` 不会删这个卷。队列里还没消费的作业会留到下次启动。这和 `engram-pg` 里的业务库是分开的。

## 3. 主题

| 主题 | 分区 | 谁写 | 谁读 | 含义 |
|------|------|------|------|------|
| `memory.extract` | 1 | context | memory | 从这一轮对白里提取记忆，并回写 `extractMs` |
| `memory.reinforce` | 1 | context | memory | 给刚刚装进 prompt 的记忆增加 salience |
| `memory.dead` | 1 | memory | 不消费 | 第五次仍失败的作业 |

主题在 context 和 memory 启动时由 `ensure_topics()` 创建。测试可以再要一个 `test.<uuid>` 主题，用独立消费组读它。死信主题只生产，不加入 `engram-memory` 的订阅，避免失败作业被立刻再次执行。

## 4. 记录格式

值是 UTF-8 JSON。键是消息 id，便于在日志里对照。单分区时键不影响顺序。

```json
{
  "id": "8d0c1b2e-7c2a-4c1d-9b2e-6a1f0e5d4c3b",
  "payload": {},
  "attempts": 0,
  "availableAtMs": 1760000000000
}
```

`attempts` 是已经交给处理函数的次数，第一次发布时是 0。`availableAtMs` 是 Unix 毫秒。还没到这个时间的记录不会返回给处理函数。

`memory.extract` 的 payload：

| 字段 | 来源 |
|------|------|
| `characterId` | 这一轮的角色 |
| `userId` | 固定本地用户 `local`，除非调用方传入别的 |
| `userMessage` | `chat` 用排序查询；`continue` 是空串，避免把续写指令写进记忆 |
| `assistantMessage` | 刚刚落库的回复 |
| `turnId` | assistant 消息 id |
| `inspectionId` | 检查器快照 id，提取完成后用来补 `extractMs` |

`memory.reinforce` 的 payload 只有 `memoryIds`，即这一轮实际装进 prompt 的记忆 id。没有装入任何记忆时仍然会发一条空列表，消费者把空列表当成成功。

## 5. 投递

生产者 `acks=all`，并打开幂等生产，避免 broker 超时重试时把同一条记录写两遍。`publish` 会等到 broker 确认，所以 `done` 之后的发布是同步的那一小段时间；提取本身不在这条路径上。

消费者关闭自动提交。处理成功调用 `ack`，提交的是这条记录的下一个偏移。处理抛错调用 `nack`：

1. `attempts` 小于 5：把同一条 id 再写回原主题，`availableAtMs` 推迟 `min(30, attempts * 2)` 秒，然后提交旧偏移。
2. `attempts` 达到 5：把记录写入 `memory.dead`，提交旧偏移，不再执行。

推迟期间，该分区在本进程里暂停。同一分区上更晚的记录要等这条被确认、或者再次被取走之后才会读到。`memory.extract` 和 `memory.reinforce` 是不同主题、不同分区，一边在退避时另一边仍可以消费。

这是至少一次。进程在 `ack` 之前崩溃，未提交的记录会在消费者重新加入组之后再投递一次。提取侧靠两件事减少重复伤害：被 regenerate 丢掉的 turn 已经写进 `discarded_turns`，晚到的提取不再插入；正文几乎相同的候选会强化已有行，而不是再插一行。强化每次成功会把 salience 加上 `0.05` 并封顶 1，因此同一条强化作业被投递两次时，salience 会多涨一档。这和崩溃前已经执行完但还没提交偏移是同一类窗口。

`max_poll_interval_ms` 设为 10 分钟。提取要调用模型时，消费者在这段时间里不轮询，心跳仍在后台发送。超过这个间隔还没回到 `claim`，组会把分区让出去，未提交的作业会被重新投递。

## 6. 和聊天回合的接缝

```text
context 写出 done
    -> publish memory.extract
    -> publish memory.reinforce
    -> gRPC 流结束
memory 取到 extract
    -> extract_and_store
    -> StampExtract(inspectionId, extractMs)
memory 取到 reinforce
    -> reinforce_memories
```

`done` 里的 `extractMs` 仍是空的。检查器要等 `StampExtract` 之后才有这段耗时。浏览器在流结束后会再读一次检查器；如果消费者还没跑完，这次读到的快照里提取耗时可以仍是空的。下一次打开检查器或下一轮刷新才会看到。

生成失败、空回复、替换失败、丢弃记忆失败都不会发布。发布发生在 `done` 已经 yield 之后，所以发布异常不会再产生一条 SSE `error`。

## 7. 代码

| 行为 | 位置 |
|------|------|
| 生产、领取、确认、否定、建主题 | `packages/engram_queue/engram_queue/queue.py` |
| `done` 之后的两次发布 | `services/context/context_service/orchestrator.py` |
| 消费循环、提取、强化、空闲遗忘 | `services/memory/memory_service/consumer.py` |
| 启动时建主题 | context 与 memory 的 `server.py` |

`claim` / `ack` / `nack` 是同步函数，内部把协程提交到单独的事件循环线程。context 的发布因此可以留在同步调用点上，不必把测试里的假队列改成协程。memory 用 `asyncio.to_thread` 调用它们，避免挡住 gRPC 的事件循环。

集成测试在 `packages/engram_queue/tests/test_queue.py`。它们需要一个已经能连上的 broker，覆盖领取后的互斥、退避后的再次投递、第五次失败进入死信，以及坏 JSON 被提交后跳过。不需要 Postgres，也不需要 API 密钥。

## 8. 本地与 CI

`./scripts/dev.sh` 在 Compose 里把 Kafka 和 Postgres 一起拉起，并等健康检查通过。`./scripts/dev.sh local` 在有 Docker 时只额外启动 Postgres 和 Kafka 两个容器，业务进程仍在宿主机。没有 Docker 时，脚本要求 `127.0.0.1:9092` 上已经有 broker，否则直接退出并说明要设置 `KAFKA_BOOTSTRAP_SERVERS`。

CI（`.github/workflows/ci.yml`）用 service container 启动同一个 `apache/kafka:4.2.2` 镜像，主机名设为 `kafka`，广告地址是 `127.0.0.1:9092`。作业里的 pytest 使用这个地址。Postgres 仍负责三个业务库，不再创建 `engram_mq`。
