# chat-service

浏览器和 Next.js 唯一访问的 HTTP 服务，端口 18410。

## 拥有

- 角色卡，库 `engram_chat`
- 请求日志：方法、路径、状态码。不含正文，不含密钥
- CORS，以及空库时的 Lyra、Zero、Mara 种子

创建角色后调用 context 写入 greeting。greeting 失败会删掉刚建的角色卡。删除角色时先清 memory，再清 context 的会话，最后删角色卡。

## 不拥有

消息、摘要、检查器、prompt、模型调用。这些向 context、memory 读，或把角色卡交给 context 的 `StreamTurn`。
