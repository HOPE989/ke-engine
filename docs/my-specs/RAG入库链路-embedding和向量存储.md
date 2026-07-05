# 入库链路 - embed and store

- 向量数据库选型：Elasticsearch

- 接入依赖：langchain-elasticsearch

通过之前的开发，文档已经到达了chunked状态，document表为chunked，其chunks均为init（这次任务我们把INIT改成STORED，KnowledgeSegment表的status=STORED/VECTOR_STORED）。

chunk完成后，理论上是要往kafka发一条消息的，然后embed and store worker收到消息就开始做embed and store。（但现在chunk流程先不发，用todo标注，我们先手动给个接口向Kafka发消息）。

向量模型，我们用langchain包装好的OpenAIEmbeddings，modelName = text-embedding-v4，baseurl和api-key还是用.env的

具体的我们可以

- 分页扫描全部document_id为docId且status为INIT的文档片段。OpenAIEmbeddings的chunk_size可以=64，我们一次分页最多拿64个
- 然后我们批量获取嵌入向量、存储嵌入向量、更新KnowledgeSegment表、继续下一页
- 需要对所有的segment做检查，确保所有的segment都已转换为vector
- 更新文档状态

---

初版简易方案：

**前置校验与状态检查**

- **获取文档**：根据 `docId` 查询 `KnowledgeDocument` 实体。
- **空值与状态判断**：如果文档不存在直接返回 `false`；如果文档已经是向量化完成状态 (`VECTOR_STORED`)，则直接返回 `true`（避免重复处理）。

**分页扫描待处理切片**

- **构建查询条件**：筛选属于该文档 (`docId`) 且满足以下条件的切片 (`KnowledgeSegment`)：
- 状态为初始化 (`INIT`，当前改为了`STORED`)。
- 没有关联的向量ID (`embeddingId` 为空)。
- 未被标记为跳过向量化 (`skipEmbedding == 0`)。
- **分页处理**：使用分页查询（每页 100 条）来防止一次性加载过多数据导致内存溢出。

**向量化循环处理**

代码进入一个 `while` 循环，直到处理完所有符合条件的切片页：

- **数据转换**：将数据库实体 `KnowledgeSegment` 转换为向量化模型所需的对象（包含文本内容和元数据）。
- **调用模型生成向量**：调用embedding模型批量获取文本的嵌入向量。
- **存储向量**：调用es的store将生成的向量存储到 Elasticsearch 中，并获取返回的 `embeddingId`。
- **更新切片状态**：遍历处理过的切片，将获取到的 `embeddingId` 回填，并将状态更新为 `VECTOR_STORED`，然后更新数据库。
- **翻页**：继续查询下一页数据，直到处理完毕。

**最终状态更新**

- **更新文档状态**：将主文档 `KnowledgeDocument` 的状态更新为 `VECTOR_STORED`，标志着整个文档的向量化流程结束。