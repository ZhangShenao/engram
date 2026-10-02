# Memory

记忆的唯一所有者。负责提取、排序、槽位取代，以及用户编辑和软删。

## 行为

- 类型：`fact`、`relationship`、`promise`、`boundary`、`plot`。同类型可以有多条。
- 取代只发生在显式 `supersedesMemoryId`，或同一 `slot`。Phase 1 只有 `user_name`。模型返回的其它 `slot` 会丢掉，再按类型和正文推断。
- `deleted_at` 一旦写上就不再检索。软删不会被改回。
- 无 `OPENROUTER_API_KEY`：确定性提取器（姓名、承诺、边界、关系、情节的规则）。
- 有密钥：OpenRouter JSON 提取，失败时返回空列表，不打断聊天。
- 排序权重：salience 0.45、recency 0.35、词面相关度 0.20。已删除和已取代的不参与。

姓名规则跑在小写文本上，因此 “My name is Alex” 会存成 “The user's name is alex.”。这是 Phase 1 的同一条正则。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | |
| GET | `/memories?characterId&userId` | 只返回活跃记忆 |
| POST | `/memories/rank` | `{characterId, userId, query}` → 带 `score` 的排序结果 |
| POST | `/memories/extract` | 从一轮对白提取并落库，必要时取代 |
| POST | `/memories/discard-turn` | `{sourceTurnId}` 软删该轮产生的记忆 |
| PATCH | `/memories/{id}` | `{text?, type?, salience?}`。不改 slot |
| DELETE | `/memories/{id}` | 软删 |
| DELETE | `/memories?characterId=` | 角色被删时清掉该角色的行 |

## 数据

数据库 `engram_memory`（`MEMORY_DATABASE_URL`）表 `memories`。槽位取代只针对 `user_name`。`deleted_at` 是软删。槽位逻辑在 `memory_service/domain/slots.py`，排序在 `domain/rank.py`，取代在 `domain/supersede.py`。
