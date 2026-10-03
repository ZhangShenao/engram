# 从零到本机微调：Engram 专属聊天模型

这份材料写给已经会做 Agent 编排、还没有训练过模型的工程师。读完以后，你应该能解释一个 14B 聊天模型里参数在算什么，能判断哪些东西该放进权重、哪些必须留在 Harness 里，并在自己的 MacBook Pro（Apple M5 Pro，48 GB 统一内存）上，用 MLX 的 QLoRA 跑通一次监督微调。

机器前提：Apple M5 Pro，48 GB。带宽 307 GB/s。这条路径是 4-bit 基座加 LoRA，全参数微调不在这台机器的内存里。

## 怎么读

按章节顺序读。每一章末尾有几个自问。答不上来就停在那一章，不要跳到训练命令。

图是为这份材料画的示意。图里的 token id 不是 Qwen 的真实编号。矩阵尺寸、层数、头数、内存量级来自 [Qwen2.5-14B-Instruct 的配置](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct/blob/main/config.json) 和公开的 MLX 训练说明，正文里会标明哪些是数量级。

| 章 | 你带走的判断 |
|----|----------------|
| [1. 模型在算什么](01-next-token.md) | 它是条件概率，不是一个会记住用户的服务 |
| [2. Token 与向量](02-tokens.md) | 文本进模型之前先被切成整数，再查表变成向量 |
| [3. Transformer](03-transformer.md) | 一层里注意力和前馈各自干什么，14B 的参数堆在哪 |
| [4. 三段训练](04-three-stages.md) | 预训练、监督微调、偏好对齐分别写入什么先验 |
| [5. 损失与梯度](05-loss.md) | 训练只是在降低“下一个 token 猜错”的分数 |
| [6. LoRA 与 QLoRA](06-lora.md) | 48 GB 上能训练的是低秩增量，基座冻结 |
| [7. 给 Engram 准备的数据](07-data.md) | 一条样本是一轮对话，损失只落在最后一条回复 |
| [8. 评测](08-eval.md) | 先有评分表，再看 loss |
| [9. 在 M5 Pro 上训练](09-practice.md) | 可执行的安装、配置和第一条命令 |
| [10. 接回 Engram](10-engram.md) | 本地 OpenAI 兼容服务怎么接到现有 Harness |
| [11. 失败时长什么样](11-failures.md) | 过拟合、出戏、内存不够时先看哪里 |
| [附录](appendix.md) | 词汇、命令、延伸阅读 |

配套文件：

- `examples/build_rows.py` 生成冒烟数据
- `examples/train.jsonl`、`examples/valid.jsonl`
- `examples/lora.yaml` 第一轮配置

冒烟数据是原创的短剧，用来证明管道能跑。它训不出一个能上线的角色模型。

## 和 Engram 代码的对应

读原理时可以同时打开这些文件，不必改它们：

- 人设、示例、输出形态、re-anchor：`services/harness/harness_service/persona/stability.py`
- 段落顺序：`services/harness/harness_service/prompt/templates.py`
- 记忆和摘要怎么拼进系统消息：`services/harness/harness_service/prompt/builder.py`
- 真正发给模型的 `messages`：`services/harness/harness_service/context/assembler.py`
- 模型调用：`services/harness/harness_service/llm/openrouter.py`
- 记忆提取走同一套 OpenRouter 环境变量：`services/memory/memory_service/domain/extractor.py`

## 这份材料不做什么

不从零预训练。不在云端这台 Linux 上替你跑 MLX（MLX 只在 Apple Silicon 上训练）。不把用户事实写进权重。不替换 Engram 现在的提示词组装。
