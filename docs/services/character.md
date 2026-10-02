# Character

角色卡的唯一所有者。不保存消息。

## 职责

- 角色卡 CRUD
- 空库种子：Archmage Lyra、Zero、Mara（`POST /internal/seed` 可重复调用）

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | |
| GET/POST | `/characters` | 列表 / 创建。响应 `{characters}` 或 `{character}` |
| GET/PUT/DELETE | `/characters/{id}` | |
| POST | `/internal/seed` | 仅当表为空时插入三个种子，然后返回全部角色 |

创建时 `name` 不能为空。示例对白以 JSON 存在 `example_dialogues`。

## 数据

数据库 `engram_character`（`CHARACTER_DATABASE_URL`，容器内为 `DATABASE_URL`）。表 `characters`：`name`, `tagline`, `description`, `personality`, `scenario`, `example_dialogues`, `greeting`, `speech_style`, `boundaries`, `created_at`, `updated_at`。空库时 `POST /internal/seed` 写入 Lyra、Zero、Mara。
