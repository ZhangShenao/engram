# memory-service

记忆的唯一所有者。内部 gRPC，端口 18413。库 `engram_memory`。它也是 Kafka 消费组 `engram-memory` 的唯一成员。不要再起第二个 memory 进程去抢这一个分区：主题都是单分区，第二个成员会空转，第一个成员才处理作业。

## 拥有

- 记忆行：正文、类型、槽位、salience、来源 turn、取代、删除、遗忘
- 被 regenerate 丢掉的 turn 墓碑 `discarded_turns`
- 提取、排序、衰减、强化、遗忘和用户改删
- 从 `memory.extract`、`memory.reinforce` 取作业，并把第五次失败写入 `memory.dead`

它不生成聊天回复，不保存会话，也不决定 prompt 的段落顺序。排序只按调用方给的 query 返回记忆，context 再决定装进哪一层。

## 行为

类型是 `fact`、`relationship`、`promise`、`boundary`、`plot`。同类型可以有多条。槽位才决定取代。

槽位是点分路径。同路径取代，父子和兄弟并存。`user_name` 仍是 `user.name` 的别名，读到旧数据时归一成点分路径。

内置路径：

| 槽位 | 什么时候推断 |
|------|----------------|
| `user.name` | `fact`，正文像在报姓名 |
| `user.language` | `fact`，正文像在报语言 |
| `relationship.status` | `relationship`，正文像在说双方关系 |
| `boundary.limit` | `boundary` |
| `promise.commitment` | `promise` |

推断在 `memory_service/domain/slots.py`。提取器也可以直接给候选写 `slot`。`find_superseded_memory` 只按槽位匹配，调用方不用再写一遍比较。

正文几乎相同的新候选不另插一行，而是强化已有记忆。比较在 `domain/supersede.py`。

排序在 `domain/rank.py`。有效 salience 以 `last_reinforced_at` 为锚，没有则用 `created_at`，半衰期 30 天。权重是有效 salience 0.45、recency 0.35、词面相关度 0.20。recency 30 天线性到 0。相关度是词面重叠占查询词的比例，短于 3 个字符的词不计。已删除、已取代、已遗忘的行不进排序，也不进列表。

遗忘条件是创建超过 14 天，且衰减后 salience 低于 0.2。打上 `forgotten_at` 之后不再参与排序和列表。扫描不是队列消息：消费循环连续约 300 次空轮询（大约 60 秒没有作业）时调用 `forget_stale`。一直有提取或强化时，扫描会推迟。

`deleted_at` 一旦写上就不再检索，强化也会跳过它。`DiscardTurn` 按 `source_turn_id` 软删，并写入 `discarded_turns`。晚到的 `memory.extract` 看到这行墓碑就直接返回，不再插入。因此提取可以排在 `done` 之后，不必为了 regenerate 去挡住聊天。

无 `OPENROUTER_API_KEY` 时用确定性提取器，规则覆盖姓名、承诺、边界、关系和剧情句。有密钥时，提取经 llm-gateway 做一次 JSON 补全，`temperature` 0.2，请求头与聊天相同。提取失败由 Kafka 重试，不打断已经结束的那一轮聊天。第五次仍失败的记录在 `memory.dead`，订阅组不会再读它。

强化把 salience 加 0.05，封顶 1，刷新 `last_reinforced_at`，并清掉 forgotten 标记。同一条作业因至少一次投递被处理两次时，salience 会多涨一档。空的 `memoryIds` 算成功，不改任何行。

## RPC

| RPC | 调用方 | 作用 |
|-----|--------|------|
| `Check` | 健康检查 | 进程还在 |
| `List` | chat | 记忆面板 |
| `Rank` | context | 回合开始时的排序 |
| `DiscardTurn` | context | regenerate 替换成功之后 |
| `Update` | chat | 用户改正文、类型或 salience |
| `Delete` | chat | 用户删除一条 |
| `DeleteByCharacter` | chat | 删除角色时清空 |

`Update` 拒绝未知类型，以及不在 0 到 1 之间的 salience。提取和强化没有同步 RPC。队列上的字段和退避见 [queue.md](../queue.md)。

## 代码

| 模块 | 职责 |
|------|------|
| `memory_service/server.py` | gRPC，启动时建库、建主题，并拉起消费任务 |
| `memory_service/consumer.py` | 领取、分发、确认、否定，以及空闲遗忘 |
| `memory_service/store.py` | 记忆表、提取落库、强化、遗忘、墓碑 |
| `memory_service/domain/slots.py` | 槽位常量与推断 |
| `memory_service/domain/rank.py` | 衰减、遗忘条件和排序 |
| `memory_service/domain/supersede.py` | 同槽取代与近重复强化 |
| `memory_service/domain/extractor.py` | 确定性提取器与 JSON 解析 |
| `memory_service/llm_client.py` | 有密钥时经 llm-gateway 提取 |
