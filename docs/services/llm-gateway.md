# llm-gateway

内部 gRPC，端口 18414。不保存会话，也不访问业务库。

聊天补全是流。记忆提取是一次 JSON 补全。两边都带 `HTTP-Referer` 和 `X-Title: Engram`，流式请求带 `Accept-Encoding: identity`。

本期 Provider 是 OpenRouter。没有 `OPENROUTER_API_KEY` 时，聊天一开始就走脚本化 Provider，这不是故障切换。有密钥时，会话钉住的 Provider 和模型优先。备用链上的下一家只在还没有吐出第一个 token 时启用。已经输出过文本之后，这一轮失败，钉保持原样。
