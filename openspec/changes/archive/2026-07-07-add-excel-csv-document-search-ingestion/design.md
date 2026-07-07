## Context

The document pipeline already stores originals, converts documents asynchronously, chunks converted documents into `knowledge_segment`, and dispatches vector storage after successful chunking. Excel is currently recognized only as an unsupported type, CSV has no business file type, and `ExcelConverter` is an explicit placeholder that fails conversion.

Chunking currently loads `converted_doc_url` as UTF-8 Markdown before choosing a splitter. That works for PDF/Word/MinerU Markdown and plain text, but it cannot work for Excel origin files because `.xlsx` and `.xls` are binary. This change keeps the existing factory pattern but moves content loading into the type-specific splitter.

## Goals / Non-Goals

**Goals:**

- Accept Excel and CSV files for the `DOCUMENT_SEARCH` document-ingestion path.
- Convert Excel and CSV by reusing the original document URL, without MinerU or an intermediate converted Markdown object.
- Let splitters load the appropriate content shape for their file type.
- Add RAGFlow-like Excel2HTML chunking with compact table sections and fixed 12-row data chunks.
- Preserve existing segment persistence, parent-child metadata, and vector-storage dispatch behavior.

**Non-Goals:**

- No `DATA_QUERY` implementation, database table creation, SQL querying, or structured-data ingestion.
- No frontend changes.
- No Excel image/chart/style extraction, merged-cell expansion, table-object detection, or formula recalculation.
- No retrieval/reranking changes or parent de-duplication behavior.

## Decisions

### 1. Keep the splitter factory, upgrade the splitter business interface

`chunk_document()` should no longer call `load_converted_markdown()` before selecting a splitter. Instead, it selects the splitter by `document.file_type` and calls an async document-level `split_chunks(document, storage, id_generator)` entrypoint.

Markdown-backed splitters download `converted_doc_url`, decode UTF-8, and delegate to the existing Markdown header parent/child algorithm. Excel/CSV splitters download the same `converted_doc_url`, which points to the origin file, and parse spreadsheet bytes.

Alternative considered: add file-type branches in `workflow.chunk_document()`. That would keep the current pure-text splitter contract but would move type-specific loading into workflow and make new file types expand workflow branching.

### 2. Reuse the original URL for spreadsheet conversion

`ExcelConverter` should support both `excel` and `csv` and return `document.doc_url`. It should not download bytes, call MinerU, or upload a converted object. This matches plain text's lightweight conversion semantics while keeping parsing in chunking where chunk shape is decided.

### 3. Generate RAGFlow-like compact HTML table sections

Excel2HTML should parse each sheet independently. The first physical row is the repeated header row. Data rows are grouped by a hard-coded `chunk_rows = 12`; each group becomes one compact section:

```html
<table><caption>{file_name} - {sheet_name}</caption>{header_tr}{data_tr...}</table>\n
```

This intentionally differs from RAGFlow by adding the file name to `<caption>` because business spreadsheet filenames often carry essential context, such as month or report type. CSV is treated as one sheet named `Data`.

### 4. Apply the same parent-child rule as Markdown

Each Excel2HTML section is the first-pass section. If its length is within `chunk_size`, it becomes a normal embeddable chunk. If it exceeds `chunk_size`, the complete HTML section becomes a skipped parent and `RecursiveCharacterTextSplitter` creates embeddable children. Children do not receive extra caption/header text and are allowed to be partial HTML because retrieval can recover the complete parent through `parentChunkId`.

### 5. Keep parsing dependencies minimal and explicit

Use `openpyxl` for `.xlsx`, `xlrd` for `.xls`, and Python's standard `csv` module for `.csv`. CSV decoding should try `utf-8-sig` first, then `gb18030`, so common Chinese CSV exports work without adding a detector dependency.

## Risks / Trade-offs

- Excel2HTML does not identify multiple logical tables inside one sheet → It preserves physical row order and RAGFlow-like sectioning; true table-boundary detection can be added later.
- Repeated headers and captions create similar vectors → This is accepted because the repeated context improves recall for table chunks; retrieval-stage de-duplication can be added later.
- `.xls` support adds an extra dependency → Keep it narrowly scoped to reading cell values for document search.
- Very large spreadsheets can produce many sections → Existing chunk persistence and vector-storage batching handle many segments; no new asynchronous chunking model is introduced.

## Migration Plan

1. Add spreadsheet parser dependencies to backend dependencies and lock file.
2. Add delta specs and tasks for upload/conversion and chunking.
3. Implement tests first for file detection, conversion, workflow dispatch, and Excel2HTML splitting.
4. Implement code changes behind the existing upload/chunk APIs without changing route contracts.
5. Run OpenSpec validation and targeted backend tests.
