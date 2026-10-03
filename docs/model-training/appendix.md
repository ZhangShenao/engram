# 附录

## 词汇

| 词 | 在这份材料里的意思 |
|----|--------------------|
| 参数 / 权重 | 训练可以改的数字。模型 = 固定计算 + 这组数字 |
| 样本 | 一对输入和标签。聊天里是前文和下一个 token |
| 标签 | 希望预测到的目标。监督微调里是写下的回复 |
| 损失 | 预测离标签有多远，一个数，训练要把它变小 |
| 梯度 | 每个参数上「损失往哪边变」的方向 |
| 学习率 | 沿梯度走的步长。第一轮 `1e-4` |
| 前向 / 反向 | 前向算出预测；反向把损失分回各参数 |
| 推理 | 只有前向，权重不动。线上聊天是推理 |
| 过拟合 | 训练损失下降，验证损失上升 |
| 张量 | 标量、向量、矩阵和更高维数组的统称 |
| 线性层 | `y = Wx + b`。没有弯折 |
| 激活函数 | 夹在线性层之间的弯曲。Qwen2.5 用 SiLU |
| 点积 | 两列等长数字逐个相乘再相加 |
| Softmax | 把 logits 变成加起来等于 1 的概率 |
| token | 分词器输出的整数，模型的输入单位 |
| 嵌入 | 词表里每个 id 对应的一行向量 |
| 隐藏维度 | 这一行的长度。Qwen2.5-14B 是 5120 |
| 因果掩码 | 挡住未来 token 的下三角 |
| logits | 进 softmax 之前的词表分数 |
| 交叉熵 | `-log(正确 token 的概率)` |
| SFT | 用标准回复做监督微调 |
| LoRA | 冻结大矩阵，训练低秩增量 `BA` |
| QLoRA | 大矩阵是 4-bit，增量仍用较高精度训练 |
| 秩 | 瘦矩阵的中间维，第一轮用 8 |
| 适配器 | 训练产物 `adapters.safetensors` |
| 融合 | 把适配器加进基座，得到一份普通权重 |

## 第一轮数字

这些数字分散在前面各章，集中放在这里方便对照。

| 项 | 值 |
|----|----|
| 芯片 | Apple M5 Pro，统一内存 48 GB，带宽 307 GB/s |
| 基座 | `mlx-community/Qwen2.5-14B-Instruct-4bit` |
| 层数 / 隐藏维 / 查询头 / 键值头 | 48 / 5120 / 40 / 8 |
| 词表 | 152064，嵌入不与输出层共享 |
| 训练类型 | QLoRA，`q_proj` 与 `v_proj`，最后 16 层 |
| 秩 / scale | 8 / 20 |
| 批大小 / 序列 / 学习率 | 1 / 2048 / `1e-4`（不稳则 `1e-5`） |
| 冒烟迭代 | 8，等于冒烟训练集行数 |
| 本地服务端口 | 18420 |

## 命令清单

```bash
python3 -m venv ~/.venvs/engram-mlx
source ~/.venvs/engram-mlx/bin/activate
python -m pip install -U pip
python -m pip install "mlx-lm[train]"

python docs/model-training/examples/build_rows.py
mlx_lm.lora --config docs/model-training/examples/lora.yaml --mask-prompt

mlx_lm.fuse \
  --model mlx-community/Qwen2.5-14B-Instruct-4bit \
  --adapter-path adapters/engram-smoke \
  --save-path ~/engram-tune/fused

mlx_lm.server --model ~/engram-tune/fused --host 127.0.0.1 --port 18420
```

正式数据不要用冒烟适配器的路径。融合前换成第 9 章评分通过的那一次 `adapter_path`。

## 延伸阅读

按这个顺序，够支撑你把上面的训练做完并知道自己在改什么。

1. Jay Alammar, *The Illustrated Transformer*。注意力的图示讲解。
2. Andrej Karpathy, *Let's build GPT*（视频）和 nanoGPT。用很少的代码把预训练循环走通。看的时候记住：你的 Mac 上做的是循环的后半，数据是对话。
3. Hu 等，*LoRA: Low-Rank Adaptation of Large Language Models*，arXiv:2106.09685。
4. Dettmers 等，*QLoRA: Efficient Finetuning of Quantized LLMs*，arXiv:2305.14314。
5. Rafailov 等，*Direct Preference Optimization*，arXiv:2305.18290。等评分表稳定后再读。
6. mlx-lm 仓库里的 `mlx_lm/LORA.md` 和 `mlx_lm/SERVER.md`。命令以你安装的版本的 `--help` 为准，文档更新时以仓库为准。
7. `Qwen/Qwen2.5-14B-Instruct` 的 model card 和 `config.json`。第 3 章的形状都来自这份配置。

论文读方法、实验设置和限制。不需要把证明推一遍才能开始第一轮 SFT。
