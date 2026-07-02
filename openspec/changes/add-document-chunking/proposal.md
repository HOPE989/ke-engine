## Why

RAG ingestion currently stops when an uploaded document has been converted to Markdown. Users need a controlled way to split a converted document into retrievable knowledge segments before later embedding and Elasticsearch storage can build on stable segment records.

This change adds a first document chunking capability with user-provided chunk parameters, explicit parent-child chunk metadata, and durable relational persistence.

## What Changes

- Add a synchronous HTTP chunking endpoint for converted documents:
  - `POST /api/v1/document/{doc_id}/chunk`
  - request body includes `chunk_size` and `overlap`
  - response returns `doc_id`, `status`, and `segment_count`
- Add `knowledge_segment` persistence for Markdown-derived chunks.
- Extend document lifecycle with `CHUNKING` and `CHUNKED`.
- Use Redis distributed locking for per-document chunking concurrency control.
- Use one database transaction to persist all generated segments and complete the document state transition.
- Use `MarkdownHeaderTextSplitter` followed by `RecursiveCharacterTextSplitter` from `langchain-text-splitters`.
- Preserve LangChain splitter metadata and document metadata in each segment metadata payload for later Elasticsearch ingestion.
- Keep embedding, vector storage, automatic background chunking, chunk versioning, document versioning, and retry/repair jobs out of scope.

## Capabilities

### New Capabilities

- `document-chunking`: Manual parameterized chunking of converted Markdown documents into durable knowledge segments.

### Modified Capabilities

- `document-upload`: Extend document lifecycle states after conversion to include chunking states.

## Impact

- Backend API: adds a document chunking endpoint under the document module.
- Database: adds `knowledge_segment` and extends `knowledge_document.status` constraints.
- Dependencies: adds `langchain-text-splitters`.
- Infrastructure: reuses Redis lock infrastructure with a new per-document chunking lock key.
- Tests: adds API validation, splitter behavior, metadata, persistence, locking, transaction, and migration coverage.
