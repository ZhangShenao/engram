# llm-gateway

内部 gRPC，端口 18414。不保存会话，不访问业务库，也不连接 Kafka。一次调用的全部状态都在请求里：钉、消息、温度。会话钉存在 context 的会话行上，网关只在响应里报告实际用过的 provider 和 model，由 context 决定要不要写回去。

## 两种调用

聊天补全是 `Complete`，服务端流。context 在组装完 prompt 之后调用它，温度 0.8。每个文本增量一条消息，流结束即这一轮的模型部分结束。

记忆提取是一次非流式 JSON 补全，温度 0.2。只有 memory 在有 `OPENROUTER_API_KEY` 时才会打到这里。没有密钥时 memory 根本不调用网关，直接用确定性提取器。因此空密钥不是“网关里的一次失败切换”。

两边都带：

- `Authorization: Bearer <OPENROUTER_API_KEY>`，仅在有密钥时
- `HTTP-Referer: https://github.com/ZhangShenao/engram`
- `X-Title: Engram`

流式请求另外带 `Accept: text/event-stream` 和 `Accept-Encoding: identity`。gzip 会把 OpenRouter 的 SSE 攒到生成结束才解开，首字延迟会变成整段延迟。网关访问 OpenRouter 时不要开启压缩。

## 钉和失败切换

本期 Provider 是 OpenRouter。默认模型 id 是 `anthropic/claude-sonnet-5`，写在 `packages/engram_contracts/engram_contracts/constants.py`。换产品默认才改这个常量；只改某一个环境时，设置 `OPENROUTER_MODEL`。这个 id 需要在 OpenRouter 的公开模型列表里存在。

没有密钥时，聊天从第一条增量开始就走 `ScriptedLLMProvider`。脚本化 Provider 不是备用链上的一员，不能被当成故障切换的目标。有密钥时，请求里的钉优先。备用链上的下一家只在还没有吐出第一个 token 时启用。已经输出过文本之后，这一轮失败，钉保持原样，context 不会把半句话接到另一家模型后面。

切换成功时，流里的 `served` 字段变成实际的 provider 和 model。context 发现它和会话钉不同、且不是脚本化 Provider，就把会话钉改掉。同一会话之后的回合默认打到这一家。

## 不做什么

- 不拼 prompt，不裁剪，不读记忆
- 不重试一次已经吐出 token 的失败流
- 不把提取失败写进 Kafka。提取的重试在 memory 的消费者里，网关只对这一次补全返回成功或错误
- 不保存 API 密钥以外的配置到磁盘。密钥只来自环境变量 `OPENROUTER_API_KEY`

健康检查是 `Check` RPC。`llm_gateway_service.healthcheck` 给 Compose 和 `scripts/dev.sh` 用，确认端口已经在听。
