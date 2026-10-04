# context-service

内部 gRPC，端口 18411。库 `engram_context`。

## 拥有

- 会话、消息、滚动摘要
- regenerate 的替换事务
- prompt 组装、裁剪、检查器快照
- 会话上的 `(provider, model)` 钉

检查器保存这一轮实际发给模型的分层、token 估算、裁剪日志和被挤出的 turn，以及耗时。它不是第二份聊天记录。

## 代码

- `context_service/persona/stability.py`
- `context_service/prompt/templates.py`、`builder.py`
- `context_service/context/assembler.py`
- `context_service/orchestrator.py`

回合结束后向 `engram_mq` 发布 `memory.extract` 和 `memory.reinforce`。摘要追加留在这一轮的同步路径上。
