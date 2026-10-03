# 10. 接回 Engram

适配器还不是 Engram 里的一个开关。Harness 只会向 `OPENROUTER_BASE_URL/chat/completions` 发 OpenAI 风格的消息，并在 `OPENROUTER_API_KEY` 非空时才离开脚本化 Provider。本地模型要变成一个兼容这个请求的 HTTP 服务。

不要把系统提示词抄进 Gateway 或 Web。线上的句子继续由 `stability.py`、`builder.py` 和 `assembler.py` 生成。你的训练数据去对齐它们。

## 融合成一个模型

Engram 的请求体里没有适配器路径。它只送 `model` 和 `messages`。最稳的接法是把 LoRA 融进基座，服务器只加载这一份：

```bash
mlx_lm.fuse \
  --model mlx-community/Qwen2.5-14B-Instruct-4bit \
  --adapter-path ~/engram-tune/adapters/run1 \
  --save-path ~/engram-tune/fused
```

融合做的算术就是把低秩项加进基座：对每个挂了 LoRA 的投影，用还原后的权重加上 `scale · BA`，再按你选的精度存成新文件。之后的前向不再需要单独读 `A` 和 `B`。Engram 的请求体里没有适配器字段，所以服务器必须加载已经加好的那一份。只加载 4-bit 基座，等于 `BA` 没加上，评测看到的是微调之前的分布。

上游默认从 `adapters/` 读、写到 `fused_model/`。上面的两个路径把产物留在仓库外面。`--adapter-path` 和 `--save-path` 是 `mlx_lm.fuse` 的参数。

4-bit 基座上的 `W` 是分档存的。把一份很小的 `BA` 加进去再重新分档，有的增量会落进原来的档位，等于被吃掉。所以融合后要用第 8 章的同一条考题再生成一次，和 `--adapter-path` 的输出比。两段都应留在角色里。若只有适配器路径下的回复还在戏里，用 `--dequantize` 再融一次，得到未量化权重。14B 大约 30 GB。推理时这台 48 GB 的机器放得下短上下文，磁盘也要按这个大小留。不要用 GGUF 导出这条 Qwen 路线，mlx-lm 的 GGUF 导出目前写明只覆盖 Mistral、Mixtral 和 Llama 风格。

流式回复是一串 SSE 行。Harness 只取 `choices[0].delta.content` 里的增量文本，拼成气泡。非流式响应把整段放在 `message.content`，这条解析路径对不上，界面会是空的。curl 时先看 `stream: true` 的行里有没有 `delta`。

## 起服务

Engram 的开发脚本占用 18410–18415，并且不要使用 8080。mlx-lm 的默认端口就是 8080，所以显式改掉：

```bash
mlx_lm.server \
  --model ~/engram-tune/fused \
  --host 127.0.0.1 \
  --port 18420
```

先用一条不带 `stream` 的请求确认服务有回复，再打开 `stream: true`。Harness 的解析只认 SSE 行里的 `choices[0].delta.content`。

```bash
curl http://127.0.0.1:18420/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "engram-local",
    "messages": [
      {"role": "system", "content": "You are Nera, keeper of a lighthouse. Reply in character."},
      {"role": "user", "content": "Are you an AI?"}
    ],
    "max_tokens": 80,
    "stream": true
  }'
```

`mlx_lm.server` 的文档写明它只做了基本的安全检查，只绑定在本机。不要把它暴露到局域网。

## 让 Harness 指向它

`OpenRouterProvider` 在密钥为空时不会被创建。本地服务器不校验密钥，可以给一个占位值。在启动 Harness 的环境里设置：

```bash
export OPENROUTER_API_KEY=local
export OPENROUTER_BASE_URL=http://127.0.0.1:18420/v1
export OPENROUTER_MODEL=engram-local
```

`OPENROUTER_MODEL` 会原样放进请求。先用 curl 确认服务器接受这个字符串。有的版本忽略 `model` 字段、始终用启动时加载的那一份。以你本机 `mlx_lm.server --help` 和上面的 curl 为准。

不要把这些变量写进仓库里的 `.env` 再提交。`.env` 本来就被忽略。即便只在本机保存，也要注意下一节。

## 记忆提取会走同一套变量

`LLMMemoryExtractor` 同样读取 `OPENROUTER_API_KEY`、`OPENROUTER_BASE_URL` 和 `OPENROUTER_MODEL`。`scripts/dev.sh` 让五个服务继承同一份环境。密钥一旦非空，记忆提取也会打到 18420，并且请求里带 `response_format: json_object`，温度 0.2。

角色扮演适配器经常接不住这个 JSON。提取失败时服务返回空列表，聊天仍继续，记忆面板会悄悄停更。

第一轮对比声音时，用两种跑法里的一种：

- 只把上面三个变量设在单独启动 Harness 的 shell 里，Memory 进程不带密钥，继续用确定性提取器。
- 或者接受提取暂时变空，评测只看回复，不看新写入的记忆。

不要为了让提取变好，把 JSON 指令混进角色扮演训练集。那会把助手腔训回去。提取如果以后要换模型，是另一个小模型的任务。

## 怎么判断接上了

发一轮会诱导出戏的话。检查器里的 system 应仍含 `NOT a generic AI assistant`、边界和 re-anchor。Provider 名字在完成事件里会是 `openrouter`，因为代码把这条 HTTP 路径都叫这个名字，即便基地址已经是本机。用回复内容和日志里的目标 URL 确认流量进了 18420。

然后用第 8 章的表，比较本地融合模型和原来的线上模型。本地模型在格式和留在角色里上占优、事实不退步，才值得让日常开发默认指向它。

## 自问

1. 为什么服务器要加载融合后的目录，而不是只加载 4-bit 基座？
2. 端口为什么不用 8080？
3. 三个 `OPENROUTER_*` 变量设进 `dev.sh` 继承的环境之后，记忆服务会怎样？
