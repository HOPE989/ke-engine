# 入库链路 - 文档上传

## 链路

先以pdf为例，我们需要把一份PDF最终转化成向量数据库中的向量，需要经过以下步骤：

1、pdf文件上传

2、pdf文件存储在minio

3、将文件解析成markdown

4、基于markdown做分块

5、将分块后的数据做embedding

6、将向量和文本块保存在向量数据库

## 相关表

**knowledge_document（知识文档表）**

**用途**：存储上传到知识库的文档元数据信息，作为文档实体。

|                     |               |                                |
| ------------------- | ------------- | ------------------------------ |
| 字段                | 类型          | 说明                           |
| `doc_id`            | BIGINT        | 文档ID，自增主键               |
| `doc_title`         | VARCHAR(1024) | 文档标题                       |
| `upload_user`       | VARCHAR(255)  | 上传用户                       |
| `doc_url`           | VARCHAR(2048) | 文档存储URL                    |
| `converted_doc_url` | VARCHAR(2048) | 解析后文档存储URL              |
| `status`            | VARCHAR(32)   | 文档状态                       |
| `accessible_by`     | VARCHAR(1024) | 可见范围权限控制（如角色名称） |

**状态流转**：

```Text
INIT（初始状态） → UPLOADED（上传成功后状态） → CONVERTED（PDF转成markdown后的状态） → CHUNKED（已经分段后的状态） → VECTOR_STORED（已经存储到向量库以后的状态）
```

有一些数据是不需要保存在向量数据库的，比如父子分段中的父分段，比如需要通过数据查询而不是文档搜索的数据。（这两个后面都会讲），那么状态流转就是这样的：

```Text
INIT（初始状态） → UPLOADED（上传成功后状态） → CONVERTED（PDF转成markdown后的状态） → CHUNKED（已经分段后的状态） → STORED（已经存储到关系型数据库以后的状态）
```

**knowledge_segment（知识片段表）**

**用途**：存储文档分片后的文本片段，是 RAG 检索的基本单元。一篇文档会被拆分为多个片段。

|                  |               |                                                              |
| ---------------- | ------------- | ------------------------------------------------------------ |
| 字段             | 类型          | 说明                                                         |
| `id`             | BIGINT        | 片段ID，自增主键                                             |
| `chunk_id`       | VARCHAR(255)  | 分片唯一标识（用于向量化存储关联）                           |
| `text`           | LONGTEXT      | 文本内容                                                     |
| `document_id`    | BIGINT        | 所属文档ID（外键关联 knowledge_document.doc_id）             |
| `chunk_order`    | INT           | 分片顺序（文档内排序）                                       |
| `embedding_id`   | VARCHAR(255)  | 嵌入向量ID（Elasticsearch 中的向量ID）                       |
| `status`         | VARCHAR(255)  | 分片状态：INIT(初始化)、VECTOR_STORED(已向量化)              |
| `metadata`       | VARCHAR(2048) | 元数据JSON（包含 parent_chunk_id、brother_chunk_id 等关联信息） |
| `skip_embedding` | INT           | 是否跳过嵌入向量生成                                         |

**关联关系**：knowledge_document 一对多 knowledge_segment。一个文档包含多个知识片段，片段通过 `document_id` 关联到文档。

## 文档上传

提供一个接口，传入三个参数，一个是要上传的文件、一个上传者、一个是可见范围。

> 可见范围我们根据角色设定的，主要是用于控制权限的。

先调用minio的服务上传文件

然后创建一个KnowledgeDocument，保存在数据库中，这时候的状态是UPLOADED。

然后根据文件类型判断是不是pdf，如果是的话，则需要做文档的转换。如果不是的话，直接把状态推进到CONVERTED。并记录上传地址到convertedUrl上。

> 文档类型的判断可以通过apache tika

## PDF解析

我们使用minerU进行pdf的解析。我们使用minerU提供的api接口

我会本地部署一个minerU，并通过

````bash
mineru-api --host 0.0.0.0 --port 8000
````

命令启动。

我们使用minerU的同步解析接口：`POST /file_parse`

这个方法支持的参数列表如下：

|                     |                  |          |                                                            |
| ------------------- | ---------------- | -------- | ---------------------------------------------------------- |
| 参数名              | 类型             | 默认值   | 说明                                                       |
| files               | List[UploadFile] | 必填     | 支持 PDF 和部分图片格式（如 jpg、png），不支持 Office 文件 |
| output_dir          | str              | ./output | 输出目录                                                   |
| lang_list           | List[str]        | ["ch"]   | 语言列表，长度与文件数一致，不一致时用第一个或 "ch" 补齐   |
| backend             | str              |          | 解析后端，影响输出目录和命名                               |
| parse_method        | str              | auto     | 解析方法                                                   |
| formula_enable      | bool             | True     | 是否启用公式识别                                           |
| table_enable        | bool             | True     | 是否启用表格识别                                           |
| server_url          | Optional[str]    | None     | 可选，远程服务地址                                         |
| return_md           | bool             | True     | 是否返回 Markdown 内容                                     |
| return_middle_json  | bool             | False    | 是否返回中间 JSON                                          |
| return_model_output | bool             | False    | 是否返回模型输出                                           |
| return_content_list | bool             | False    | 是否返回内容列表                                           |
| return_images       | bool             | False    | 是否返回图片                                               |
| response_format_zip | bool             | False    | 是否以 zip 文件打包返回                                    |
| start_page_id       | int              | 0        | 起始页码                                                   |
| end_page_id         | int              | 99999    | 结束页码                                                   |

通过curl可请求：

```
 curl -X POST http://xxx.xx.xx.xx:8000/file_parse \
 -H "Accept: application/json" \
 -F "files=@/Users/hollis/Downloads/sample.pdf" \
 -F "backend=pipeline"  -F "response_format_zip=true" \
 -F "return_images=true" \
 -o result.zip
```

具体的可查看minerU docs。

进入转换阶段，设置状态为中间状态CONVERTING。

得到转换后的内容保存到 MinIO，并把状态推进到CONVERTED，失败则回退到UPLOADED。

## PDF图片问题

minerU要想返回图片，需要设置关键参数：`response_format_zip=true` 、`return_images=true`

这样就能得到一个压缩包，一个md文件，和一个包含了图片的文件夹。

我们在响应体中把内容读取成byte[]（java中的类型），就能拿到一个zip的压缩包了。

我们把zip下载下来后，解压缩，然后把pdf、图片分别上传到minio上。

为什么解压缩？而不是把压缩文件上传到minio？

1. 这个环节的文档处理之后，就要针对文档分段了，如果分段的时候再下载zip，解压操作，不太合适，这个动作按照职责来说，放到这个文档处理阶段更合适。
2. 压缩包中的图片，后面我们还是要用的，比如如果用户问问题的额时候，我们是可以把图片返回给用户查看的。所以图片后面还是需要再上传的，那么如果这里直接上传压缩包，图片后期再传一次，就要保存两份了，浪费资源。
3. 除了解压，图片上传以外，我们还是要针对markdown中的图片做一些图书处理的。比如转换后的markdown中的图片用的是相对地址，我们需要把图片替换为上传后的网络地址，这样用户才能看得到，还有就是为了让图片可以做检索，我们还要给他生成描述信息。所以这些工作还是要做，那不如在这一起就都干了。

## markdown中的图片处理

总体流程：

```text
处理文档转换为 ZIP 格式
1. 调用文档解析接口获取 ZIP（包含 Markdown 和图片）
2. 保存 ZIP 到本地磁盘
3. 解压 ZIP 文件
4. 上传解压后的 md 和图片到 MinIO
5. 替换 md 中的图片地址为 MinIO 地址
6. 调用 LLM 生成图片描述并更新 md（可以先固定mock成“图片描述”）
7. 保存 md 的 MinIO 地址到 convertedUrl
8. 异步清理本地临时文件
```

关于图片，主要干了两件事：

1、把`![](images/xxx.jpg)` 替换成`![](http:xxx.xx.xx/xxx.jpg)`

2、把`![](http:xxx.xx.xx/xxx.jpg)`替换成`![图片描述](http:xxx.xx.xx/xxx.jpg)` 

## 总结

最终，pdf和非pdf都从INIT -> CONVERTED。这个需求就先到CONVERTED结束。