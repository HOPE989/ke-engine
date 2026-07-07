"""knowledge_document 的持久化 repository。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.document.errors import (
    ChunkPersistenceFailed,
    DataQueryIngestionFailed,
    DataQueryTableNameConflict,
    DocumentStateConflict,
)
from app.modules.document.data_query_identifiers import quote_generated_identifier
from app.modules.document.data_query_spreadsheet import build_insert_sql_and_params
from app.modules.document.models import DocumentStatus, KnowledgeDocument, KnowledgeSegment, TableMeta


def _status_value(status: DocumentStatus | str) -> str:
    """把状态枚举或字符串统一转换为数据库存储值。"""

    if isinstance(status, DocumentStatus):
        return status.value
    return status


def _quoted_generated_identifier(identifier: str) -> str:
    """校验并 quote 后端生成的 PostgreSQL identifier。

    repository 里只有 override drop 这种 DDL 场景需要直接拼表名；如果 metadata 中的
    physicalTableName 不符合当前规则，说明已有数据不可信，按状态冲突处理。
    """

    try:
        return quote_generated_identifier(identifier)
    except ValueError as exc:
        raise DocumentStateConflict() from exc


def _physical_table_name_from_meta(table_meta: TableMeta) -> str | None:
    """从 table_meta.columns_info 中读取已导入表的物理表名。

    上传占位阶段 columns_info 为空，因此返回 None 表示没有可 drop 的旧物理表。
    """

    columns_info = table_meta.columns_info
    if not isinstance(columns_info, dict):
        return None
    physical_table_name = columns_info.get("physicalTableName")
    if not physical_table_name:
        return None
    return str(physical_table_name)


async def _execute_update_with_expected_status(
    session: AsyncSession,
    *,
    doc_id: int,
    expected_status: DocumentStatus | str,
    values: dict[str, str],
) -> None:
    """执行带 expected-status 条件的生命周期更新。"""

    # WHERE 同时约束 doc_id 和当前状态，实现轻量并发保护。
    statement = (
        update(KnowledgeDocument)
        .where(
            KnowledgeDocument.doc_id == doc_id,
            KnowledgeDocument.status == _status_value(expected_status),
        )
        .values(**values, updated_at=func.now())
    )
    result = await session.execute(statement)
    if result.rowcount == 0:
        raise DocumentStateConflict()
    # 状态更新单独提交，避免跨 MinIO/MinerU 外部调用持有事务。
    await session.commit()


class DocumentRepository:
    """使用 session_factory 管理短生命周期数据库会话的文档 repository。"""

    def __init__(self, session_factory) -> None:
        """保存启动期创建的 session_factory。"""

        self._session_factory = session_factory

    def session(self):
        """打开一个由调用方控制事务边界的数据库 session。

        普通上传/转换方法在 repository 内部提交事务；向量存储 workflow 需要一个跨多批
        segment 更新和文档完成更新的长事务，所以暴露 session context 给 workflow 管理。
        """

        return self._session_factory()

    async def create_init_document(
        self,
        *,
        doc_id: int,
        doc_title: str,
        upload_user: str,
        accessible_by: str,
        description: str,
        knowledge_base_type: str,
        file_type: str,
        extension: dict | None = None,
    ) -> KnowledgeDocument:
        """创建并提交 INIT 状态的文档行，返回带 doc_id 的模型。"""

        document = KnowledgeDocument(
            doc_id=doc_id,
            doc_title=doc_title,
            upload_user=upload_user,
            accessible_by=accessible_by,
            description=description,
            knowledge_base_type=knowledge_base_type,
            extension=extension or {},
            file_type=file_type,
            status=DocumentStatus.INIT.value,
        )
        async with self._session_factory() as session:
            session.add(document)
            await session.commit()
        return document

    async def create_data_query_document_with_table_reservation(
        self,
        *,
        doc_id: int,
        table_meta_id: int,
        doc_title: str,
        upload_user: str,
        accessible_by: str,
        description: str,
        knowledge_base_type: str,
        file_type: str,
        namespace: str,
        table_name: str,
        is_override: bool,
        extension: dict,
    ) -> KnowledgeDocument:
        """原子创建 DATA_QUERY 文档并预留逻辑表名。

        上传阶段必须先抢占 `(namespace, table_name)`，否则两个并发上传可能都被接受，
        最后在 worker 阶段才暴露冲突。这里把文档 INIT 行和 table_meta 占位放在同一
        数据库事务中：
        1. 查找同 namespace 下是否已有同名表；
        2. 未 override 时直接抛业务冲突；
        3. override 时先删除旧物理表和旧 table_meta；
        4. 写入新文档和新 table_meta 占位。
        """

        document = KnowledgeDocument(
            doc_id=doc_id,
            doc_title=doc_title,
            upload_user=upload_user,
            accessible_by=accessible_by,
            description=description,
            knowledge_base_type=knowledge_base_type,
            extension=extension,
            file_type=file_type,
            status=DocumentStatus.INIT.value,
        )
        table_meta = TableMeta(
            id=table_meta_id,
            namespace=namespace,
            document_id=doc_id,
            table_name=table_name,
            description=description,
            create_sql=None,
            columns_info=None,
        )
        async with self._session_factory() as session:
            try:
                async with session.begin():
                    # 1. 数据库唯一约束是最终防线；这里先查是为了区分普通冲突和 override。
                    existing_result = await session.execute(
                        select(TableMeta).where(
                            TableMeta.namespace == namespace,
                            TableMeta.table_name == table_name,
                        )
                    )
                    existing_meta = existing_result.scalar_one_or_none()
                    if existing_meta is not None:
                        if not is_override:
                            raise DataQueryTableNameConflict()
                        # 2. override 是显式破坏性操作：旧物理表存在时先 drop，再删旧 meta。
                        physical_table_name = _physical_table_name_from_meta(existing_meta)
                        if physical_table_name is not None:
                            await session.execute(
                                text(
                                    "DROP TABLE IF EXISTS "
                                    f"{_quoted_generated_identifier(physical_table_name)}"
                                )
                            )
                        await session.delete(existing_meta)

                    # 3. 新 document 和 table_meta 作为一个占位整体提交，供异步 worker 消费。
                    session.add(document)
                    session.add(table_meta)
            except IntegrityError as exc:
                raise DataQueryTableNameConflict() from exc
        return document

    async def delete_data_query_reservation(self, *, document_id: int) -> None:
        """按 document_id 删除 DATA_QUERY 表名占位。

        该方法用于原始文件写入对象存储失败后的补偿。override 删除的旧数据不恢复，
        这里只清理本次新建但尚未成功上传的占位记录。
        """

        async with self._session_factory() as session:
            await session.execute(delete(TableMeta).where(TableMeta.document_id == document_id))
            await session.commit()

    async def get_table_meta_by_document(self, *, document_id: int) -> TableMeta | None:
        """按 document_id 读取 DATA_QUERY table_meta。

        worker 导入时只接受属于当前文档的 table_meta，避免不同 doc_id 误用同一逻辑表。
        """

        async with self._session_factory() as session:
            result = await session.execute(
                select(TableMeta).where(TableMeta.document_id == document_id)
            )
            return result.scalar_one_or_none()

    async def import_data_query_table(
        self,
        *,
        document_id: int,
        physical_table_name: str,
        create_sql: str,
        columns_info: dict,
        column_names: list[str],
        rows: list[list[str]],
    ) -> None:
        """在一个数据库事务中导入 DATA_QUERY 动态表并把文档标记为 STORED。

        事务包含动态表 DDL、行数据 DML、table_meta 更新和 document 状态推进。
        PostgreSQL 支持事务性 DDL，因此任一步失败都会回滚物理表、已插入行和元数据。
        这里不做 drop/rebuild；如果目标物理表已存在，说明状态不一致，需要失败后人工处理。
        """

        async with self._session_factory() as session:
            try:
                async with session.begin():
                    # 1. 重新读取占位，确认 table_meta 仍归当前文档所有。
                    meta_result = await session.execute(
                        select(TableMeta).where(TableMeta.document_id == document_id)
                    )
                    table_meta = meta_result.scalar_one_or_none()
                    if table_meta is None or table_meta.document_id != document_id:
                        raise DataQueryIngestionFailed()

                    # 2. worker 不进行破坏性重建；已有物理表表示导入前置状态异常。
                    exists_result = await session.execute(
                        text("SELECT to_regclass(:table_name)"),
                        {"table_name": physical_table_name},
                    )
                    if exists_result.scalar_one_or_none() is not None:
                        raise DataQueryIngestionFailed()

                    # 3. 建表和逐行插入都处于同一个 PostgreSQL 事务内。
                    await session.execute(text(create_sql))
                    for row in rows:
                        insert_sql, params = build_insert_sql_and_params(
                            physical_table_name=physical_table_name,
                            column_names=column_names,
                            row=row,
                        )
                        await session.execute(text(insert_sql), params)

                    # 4. 物理表写入成功后，才把 DDL 和 columns_info 固化到 table_meta。
                    meta_update = (
                        update(TableMeta)
                        .where(TableMeta.document_id == document_id)
                        .values(
                            create_sql=create_sql,
                            columns_info=columns_info,
                            updated_at=func.now(),
                        )
                    )
                    meta_update_result = await session.execute(meta_update)
                    if meta_update_result.rowcount != 1:
                        raise DataQueryIngestionFailed()

                    # 5. 最后推进文档到 STORED；状态不符合预期则回滚整个导入事务。
                    document_update = (
                        update(KnowledgeDocument)
                        .where(
                            KnowledgeDocument.doc_id == document_id,
                            KnowledgeDocument.status == DocumentStatus.UPLOADED.value,
                        )
                        .values(status=DocumentStatus.STORED.value, updated_at=func.now())
                    )
                    document_update_result = await session.execute(document_update)
                    if document_update_result.rowcount != 1:
                        raise DataQueryIngestionFailed()
            except DataQueryIngestionFailed:
                raise
            except Exception as exc:
                raise DataQueryIngestionFailed() from exc

    async def get_document(self, doc_id: int) -> KnowledgeDocument | None:
        """按 doc_id 读取文档元数据，找不到时返回 None。"""

        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.doc_id == doc_id)
            )
            return result.scalar_one_or_none()

    async def list_stale_chunked_document_ids(self, *, older_than: timedelta) -> list[int]:
        """Return stale CHUNKED document IDs ordered for deterministic compensation."""

        cutoff = datetime.now(UTC) - older_than
        async with self._session_factory() as session:
            result = await session.execute(
                select(KnowledgeDocument.doc_id)
                .where(
                    KnowledgeDocument.status == DocumentStatus.CHUNKED.value,
                    KnowledgeDocument.updated_at < cutoff,
                )
                .order_by(KnowledgeDocument.updated_at.asc(), KnowledgeDocument.doc_id.asc())
            )
            return list(result.scalars().all())

    async def count_embeddable_segments(self, *, doc_id: int) -> int:
        """统计指定文档需要 embedding 的分段数量。"""

        async with self._session_factory() as session:
            result = await session.execute(
                select(func.count())
                .select_from(KnowledgeSegment)
                .where(
                    KnowledgeSegment.document_id == doc_id,
                    KnowledgeSegment.skip_embedding.is_(False),
                )
            )
            return int(result.scalar_one())

    async def list_pending_embeddable_segments(
        self,
        *,
        session: AsyncSession,
        doc_id: int,
        limit: int = 100,
    ) -> list[KnowledgeSegment]:
        """在已有事务中按固定第一页读取待向量化 segment。

        查询条件只选择仍在 DB 中、尚未写入向量的子分段：
        - `status = STORED`
        - `skip_embedding = false`
        - `embedding_id IS NULL`

        每次都按 `chunk_order, id` 读取第一页，不使用 offset。因为成功处理一批后状态会变
        为 `VECTOR_STORED`，offset pagination 会跳过原本排在后一页的剩余行。
        """

        result = await session.execute(
            # 固定第一页扫描：每批更新后再查第一页，直到没有剩余待处理行。
            select(KnowledgeSegment)
            .where(
                KnowledgeSegment.document_id == doc_id,
                KnowledgeSegment.status == "STORED",
                KnowledgeSegment.skip_embedding.is_(False),
                KnowledgeSegment.embedding_id.is_(None),
            )
            .order_by(KnowledgeSegment.chunk_order.asc(), KnowledgeSegment.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_segments_vector_stored(
        self,
        *,
        session: AsyncSession,
        segment_embedding_ids: dict[int, str],
    ) -> None:
        """在已有事务中写回 Elasticsearch ID，并推进 segment 到 `VECTOR_STORED`。

        这里不调用 `commit()`，由向量存储 workflow 的外层事务统一提交或回滚。任一 segment
        未按预期更新到一行，都视为并发状态冲突并让整个文档级事务失败。
        """

        for segment_id, embedding_id in segment_embedding_ids.items():
            # 逐行更新便于精确校验 rowcount，保证每个返回的 vector ID 都落到一个 segment。
            result = await session.execute(
                update(KnowledgeSegment)
                .where(KnowledgeSegment.id == segment_id)
                .values(
                    embedding_id=embedding_id,
                    status=DocumentStatus.VECTOR_STORED.value,
                )
            )
            if result.rowcount != 1:
                raise DocumentStateConflict()

    async def count_pending_embeddable_segments(
        self,
        *,
        session: AsyncSession,
        doc_id: int,
    ) -> int:
        """在已有事务中 double-check 仍待向量化的 segment 数量。

        这是文档完成前的最后一道 gate。只有返回 0，workflow 才允许把 document 状态推进到
        `VECTOR_STORED`；否则事务回滚，Kafka 消息保持可重试。
        """

        result = await session.execute(
            select(func.count())
            .select_from(KnowledgeSegment)
            .where(
                KnowledgeSegment.document_id == doc_id,
                KnowledgeSegment.status == "STORED",
                KnowledgeSegment.skip_embedding.is_(False),
                KnowledgeSegment.embedding_id.is_(None),
            )
        )
        return int(result.scalar_one())

    async def mark_document_vector_stored(
        self,
        *,
        session: AsyncSession,
        doc_id: int,
    ) -> None:
        """在已有事务中将 `CHUNKED` 文档推进到 `VECTOR_STORED`。

        WHERE 同时约束 `doc_id` 和当前状态，避免并发或陈旧状态把非 CHUNKED 文档错误推进。
        该方法也不提交事务，由 workflow 在 segment 写回和 double-check 全部完成后统一提交。
        """

        result = await session.execute(
            update(KnowledgeDocument)
            .where(
                KnowledgeDocument.doc_id == doc_id,
                KnowledgeDocument.status == DocumentStatus.CHUNKED.value,
            )
            .values(status=DocumentStatus.VECTOR_STORED.value, updated_at=func.now())
        )
        if result.rowcount != 1:
            raise DocumentStateConflict()

    async def _update_with_expected_status(
        self,
        *,
        doc_id: int,
        expected_status: DocumentStatus | str,
        values: dict[str, str],
    ) -> None:
        """用短 session 执行带 expected-status 条件的生命周期更新。"""

        async with self._session_factory() as session:
            await _execute_update_with_expected_status(
                session,
                doc_id=doc_id,
                expected_status=expected_status,
                values=values,
            )

    async def mark_uploaded(
        self,
        *,
        doc_id: int,
        doc_url: str,
    ) -> None:
        """记录原文 URL，并将 INIT 文档推进到 UPLOADED。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=DocumentStatus.INIT,
            values={
                "doc_url": doc_url,
                "status": DocumentStatus.UPLOADED.value,
            },
        )

    async def start_converting(self, *, doc_id: int) -> None:
        """将 UPLOADED 文档推进到 CONVERTING。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=DocumentStatus.UPLOADED,
            values={"status": DocumentStatus.CONVERTING.value},
        )

    async def mark_converted(
        self,
        *,
        doc_id: int,
        converted_doc_url: str,
        expected_status: DocumentStatus | str,
    ) -> None:
        """记录转换后 URL，并将文档推进到 CONVERTED。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=expected_status,
            values={
                "converted_doc_url": converted_doc_url,
                "status": DocumentStatus.CONVERTED.value,
            },
        )

    async def rollback_to_uploaded(self, *, doc_id: int) -> None:
        """PDF 转换失败后将 CONVERTING 文档回滚到 UPLOADED。"""

        await self._update_with_expected_status(
            doc_id=doc_id,
            expected_status=DocumentStatus.CONVERTING,
            values={"status": DocumentStatus.UPLOADED.value},
        )

    async def complete_chunking(self, *, doc_id: int, segment_drafts: list) -> None:
        """在一个事务中写入 segment 并将 CONVERTED 文档推进到 CHUNKED。"""

        async with self._session_factory() as session:
            try:
                async with session.begin():
                    session.add_all(
                        [
                            KnowledgeSegment(
                                id=draft.id,
                                chunk_id=draft.chunk_id,
                                text=draft.text,
                                document_id=draft.document_id,
                                chunk_order=draft.chunk_order,
                                embedding_id=draft.embedding_id,
                                status=draft.status,
                                metadata_=draft.metadata,
                                skip_embedding=draft.skip_embedding,
                            )
                            for draft in segment_drafts
                        ]
                    )
                    statement = (
                        update(KnowledgeDocument)
                        .where(
                            KnowledgeDocument.doc_id == doc_id,
                            KnowledgeDocument.status == DocumentStatus.CONVERTED.value,
                        )
                        .values(status=DocumentStatus.CHUNKED.value, updated_at=func.now())
                    )
                    result = await session.execute(statement)
                    if result.rowcount == 0:
                        raise ChunkPersistenceFailed()
            except ChunkPersistenceFailed:
                raise
            except Exception as exc:
                raise ChunkPersistenceFailed() from exc
