# 入库链路 - 文档切分

我们已经能够上传一类文档了：`pdf` 或者 `plain_text`

而pdf会convert成md,txt可以看作无标题的md,所以目前应用支持的文档在status = converted时，一定是markdown文档。

因此我们的文档切分，目前只针对markdown文档一种情况讨论。

我们自定义一个`Splitter`（继承自langchain），基于langchain的MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter，进行先标题再长度的切分。

因为mineru默认解析出来的markdown没有标题级别，默认是一级标题，（分标题级别需要基于大模型，没必要）

我们在MarkdownHeaderTextSplitter 切分后，一定会有一级标题和一级标题间的空内容块，我们的选择是丢弃这些空分片，因为标题某种程度上本来就是内容的高度总结，所以丢标题基本不会丢语义信息，而且有助于之后召回不检索到空内容导致召回效果不理想。 默认 `strip_headers=True` 默认会丢掉空chunk

对应MarkdownHeaderTextSplitter 分片后的分片，我们再进行一次RecursiveCharacterTextSplitter基于长度的分片。

未超出 chunkSize，保持原分片不变。

超出 chunkSize，需要二次切割，首先保留完整父分片，元数据标记为跳过embedding。RecursiveCharacterTextSplitter进一步拆分出多个子分片，复制元数据并进行更新。子分片的元数据保存父分片的chunkId（chunkId都是雪花算法）。

最后得到了基于MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter的父子分片的结果。我们把这些分片批量存入**knowledge_segment（知识片段表）**

**knowledge_segment（知识片段表）**

**用途**：存储文档分片后的文本片段，是 RAG 检索的基本单元。一篇文档会被拆分为多个片段。

|                  |               |                                                              |
| ---------------- | ------------- | ------------------------------------------------------------ |
| 字段             | 类型          | 说明                                                         |
| `id`             | BIGINT        | 片段ID，自增主键，雪花算法                                   |
| `chunk_id`       | VARCHAR(255)  | 分片唯一标识（用于向量化存储关联），雪花算法                 |
| `text`           | LONGTEXT      | 文本内容                                                     |
| `document_id`    | BIGINT        | 所属文档ID（外键关联 knowledge_document.doc_id）             |
| `chunk_order`    | INT           | 分片顺序（文档内排序）                                       |
| `embedding_id`   | VARCHAR(255)  | 嵌入向量ID（Elasticsearch 中的向量ID），暂未，后续存入Elasticsearch 后回填 |
| `status`         | VARCHAR(255)  | 分片状态：INIT(初始化)、VECTOR_STORED(已向量化)              |
| `metadata`       | VARCHAR(2048) | 元数据JSON（包含 parent_chunk_id、brother_chunk_id 等关联信息） |
| `skip_embedding` | INT           | 是否跳过嵌入向量生成                                         |

**关联关系**：knowledge_document 一对多 knowledge_segment。一个文档包含多个知识片段，片段通过 `document_id` 关联到文档。

knowledge_document 推进到CHUNKED。发布Chunked消息（todo，等写完embeddingAndStore，不然没人消费）。返回segmentCount。