## 1. Markdown Image Parsing Contract

- [x] 1.1 Add `backend/tests/test_document_markdown.py` coverage for the supported parser contract: `![](images/page-1.png)`, `![alt](images/page-1.png)`, and `![alt](https://example.com/image.png)` capture alt text and target.
- [x] 1.2 Add parser tests documenting the bounded scope: title syntax, angle-bracket destinations, escaped delimiters, and nested parentheses are not required by this change.
- [x] 1.3 Refactor `backend/app/modules/document/markdown.py` so conversion and chunking can share one Markdown image reference parser instead of duplicating URL rewrite and alt backfill parsing.
- [x] 1.4 Replace first-version `图片描述` placeholder behavior with rewrite output driven by parsed image references and per-image rewrite results.
- [x] 1.5 Verify from `backend/` with `python -m pytest tests/test_document_markdown.py -q`; expected red before implementation is missing parser API or old placeholder output, expected green is all supported parser cases passing.

## 2. PDF Conversion Image Rewrite

- [x] 2.1 Update `backend/tests/test_document_pdf_conversion.py::test_pdf_conversion_uploads_markdown_and_rewritten_images` to inject a deterministic image describer and expect generated alt text instead of `图片描述`.
- [x] 2.2 Add `backend/tests/test_document_pdf_conversion.py` cases for generic description failure and whitespace-only description output; both MUST produce `图片解析错误` while preserving the rewritten MinIO URL.
- [x] 2.3 Add `backend/tests/test_document_pdf_conversion.py` cases for missing image and asset upload failure; both MUST produce `图片解析错误`, preserve the original target when no URL is available, and still upload final Markdown.
- [x] 2.4 Update existing opposite expectations in `backend/tests/test_document_pdf_failures.py::test_pdf_conversion_failures_restore_uploaded` and `backend/tests/test_document_conversion_worker.py::test_worker_rolls_back_to_uploaded_when_pdf_conversion_fails` so asset image failures no longer roll the document back to `UPLOADED`.
- [x] 2.5 Add an injectable image description dependency to the conversion worker path, with a deterministic fake in tests. The dependency only needs to model success, generic failure, and whitespace-only output.
- [x] 2.6 Update PDF conversion orchestration so per-image read/upload/rewrite/description failures are caught per image, logged with document id and image target, and do not raise `DocumentConversionFailed`; MinerU request, ZIP extraction, Markdown selection/read, and final Markdown upload remain whole-conversion failures.
- [x] 2.7 Verify from `backend/` with `python -m pytest tests/test_document_pdf_conversion.py tests/test_document_pdf_failures.py tests/test_document_conversion_worker.py -q`; expected red before implementation is old rollback or `图片描述` behavior, expected green is degraded image handling with final conversion success.

## 3. Chunk Image Metadata

- [x] 3.1 Add `backend/tests/test_document_chunking_splitter.py` or a focused `backend/tests/test_document_chunking_metadata.py` test for `build_segment_drafts` proving chunks with supported Markdown image references persist `metadata.images` entries with `url`, `alt`, and `source`.
- [x] 3.2 Add a focused metadata test proving chunks without supported Markdown image references persist `metadata.images` as an empty list.
- [x] 3.3 Add a focused metadata test proving configured-storage image URLs include `objectKey` under `documents/{doc_id}/`.
- [x] 3.4 Add a focused metadata test proving external image URLs remain as metadata `url` values without derived `objectKey`.
- [x] 3.5 Update `backend/app/modules/document/chunking.py` to extract supported Markdown image references from each split chunk and persist `url`, `alt`, `source`, and optional `objectKey`.
- [x] 3.6 Verify from `backend/` with `python -m pytest tests/test_document_chunking_splitter.py tests/test_document_chunking_workflow.py -q`; expected red before implementation is missing `metadata.images`, expected green is complete image metadata on persisted drafts.

## 4. Verification

- [x] 4.1 Run focused Markdown parser tests: from `backend/`, `python -m pytest tests/test_document_markdown.py -q`.
- [x] 4.2 Run focused document PDF conversion and failure tests: from `backend/`, `python -m pytest tests/test_document_pdf_conversion.py tests/test_document_pdf_failures.py tests/test_document_conversion_worker.py -q`.
- [x] 4.3 Run focused document chunking tests: from `backend/`, `python -m pytest tests/test_document_chunking_splitter.py tests/test_document_chunking_workflow.py -q`.
- [x] 4.4 Run OpenSpec validation from the repo root: `openspec validate enhance-document-image-rewrite --type change --strict`.
- [x] 4.5 Run the full backend test suite from `backend/` with `python -m pytest` if focused tests pass.
