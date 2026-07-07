## 1. Upload And Conversion

- [x] 1.1 Add failing tests for Excel and CSV file-type detection.
- [x] 1.2 Implement Excel and CSV file-type detection without regressing existing supported types.
- [x] 1.3 Add failing tests for Excel/CSV origin conversion.
- [x] 1.4 Implement Excel/CSV converter support that returns `document.doc_url` without MinerU or converted uploads.

## 2. Splitter Interface And Markdown Compatibility

- [x] 2.1 Add failing tests that chunking delegates document loading to the selected splitter.
- [x] 2.2 Move Markdown converted-URL loading into `MarkdownHeaderParentTextSplitter` while preserving existing Markdown split behavior and errors.
- [x] 2.3 Update `chunk_document()` to call the async document-level splitter API.

## 3. Excel2HTML Chunking

- [x] 3.1 Add failing tests for RAGFlow-like compact HTML sections, `filename - sheetName` captions, repeated first-row headers, and fixed 12 data rows.
- [x] 3.2 Add failing tests for Excel2HTML parent/child behavior, empty/header-only sheet skipping, HTML escaping, multi-sheet handling, and CSV encoding fallback.
- [x] 3.3 Implement `Excel2HTMLParentTextSplitter` and register it for Excel and CSV.

## 4. Verification

- [x] 4.1 Add or update workflow/API tests for Excel/CSV upload-to-converted and chunk-to-vector-dispatch behavior.
- [x] 4.2 Run OpenSpec validation and targeted backend tests.
