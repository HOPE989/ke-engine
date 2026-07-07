## Why

Excel and CSV files are currently blocked or unimplemented in the document ingestion path, which prevents users from adding table-heavy business documents to `DOCUMENT_SEARCH` knowledge bases. The project already has upload, conversion, chunking, segment persistence, and vector-storage dispatch primitives, so this change extends those primitives to spreadsheet-like document search without introducing the separate structured-data `DATA_QUERY` path.

## What Changes

- Accept Excel and CSV files in the document upload file-type detection path.
- Treat Excel and CSV conversion like plain text conversion: the converted URL reuses the original document URL.
- Move document-content loading into type-specific splitters so Markdown-like documents and spreadsheet documents can load different content shapes through the same splitter factory.
- Add an Excel2HTML splitter that emits RAGFlow-like compact HTML table sections, with the deliberate caption enhancement `filename - sheetName`.
- Split oversized Excel2HTML sections using the same parent/child recursive behavior as existing Markdown chunks.
- Keep `DATA_QUERY`, structured table creation, structured SQL querying, and frontend changes out of scope.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `document-upload`: Support Excel and CSV uploads as document-search files and convert them by reusing the original URL.
- `document-chunking`: Let splitters load document content by file type and add Excel2HTML chunking for spreadsheet files.

## Impact

- Backend document file-type detection, converter registration, splitter factory, and chunking workflow.
- Backend dependencies for spreadsheet parsing.
- Unit and workflow tests for Excel/CSV detection, conversion, RAGFlow-like HTML section generation, and chunking dispatch behavior.
