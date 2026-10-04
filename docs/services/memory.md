# memory-service

记忆的唯一所有者。内部 gRPC，端口 18413。库 `engram_memory`。

## 行为

- 类型：`fact`、`relationship`、`promise`、`boundary`、`plot`。同类型可以有多条。
- 槽位是点分路径。同路径取代，不同路径并存。`user_name` 是 `user.name` 的别名。
- 内置路径：`user.name`、`user.language`、`relationship.status`、`boundary.limit`、`promise.commitment`。
- 正文几乎相同的新候选不另插一行，而是强化已有记忆。
- 排序用衰减后的 salience（半衰期 30 天），权重 salience 0.45、recency 0.35、词面相关度 0.20。
- 创建超过 14 天且衰减后 salience 低于 0.2 的记忆标为 forgotten，不再进入列表和排序。
- `deleted_at` 一旦写上就不再检索。被替换的 turn 还会写入 `discarded_turns`，晚到的提取不再插入。
- 无 `OPENROUTER_API_KEY`：确定性提取器。
- 有密钥：经 llm-gateway 做 JSON 提取。提取由队列 `memory.extract` 触发，失败可重试，不打断聊天。

## RPC

`List`、`Rank`、`DiscardTurn`、`Update`、`Delete`、`DeleteByCharacter`。提取不在同步 RPC 上。

槽位逻辑在 `memory_service/domain/slots.py`，排序和衰减在 `domain/rank.py`，取代与重复合并在 `domain/supersede.py`。
