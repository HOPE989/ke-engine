## 1. Markdown Image Parsing Contract

- [ ] 1.1 Add focused tests for parsing Markdown image references with alt text and target capture.
- [ ] 1.2 Add tests proving absolute image URLs preserve target and original alt when no local image description is available.
- [ ] 1.3 Refactor document Markdown helpers to use one shared image parsing/rewrite path instead of separate URL rewrite and alt backfill passes.
- [ ] 1.4 Remove the first-version mock `图片描述` placeholder behavior from PDF image rewriting.

## 2. PDF Conversion Image Rewrite

- [ ] 2.1 Add tests for successful relative image upload, URL rewrite, and generated alt text insertion.
- [ ] 2.2 Add tests for image description failure producing `图片解析错误` while preserving the rewritten MinIO URL.
- [ ] 2.3 Add tests for missing, unreadable, or upload-failed images producing `图片解析错误` while preserving the original image target.
- [ ] 2.4 Update PDF conversion orchestration so per-image upload, URL rewrite, and description generation failures do not raise `DocumentConversionFailed`.
- [ ] 2.5 Add an injectable image description dependency for the conversion worker path with a deterministic test fake.
- [ ] 2.6 Log per-image processing failures with document id and image target without exposing provider secrets or raw stack traces to API responses.

## 3. Chunk Image Metadata

- [ ] 3.1 Add tests proving persisted segment metadata includes `images` for chunks containing Markdown image references.
- [ ] 3.2 Add tests proving chunks without image references persist `metadata.images` as an empty list.
- [ ] 3.3 Add tests proving configured-storage image URLs include `objectKey` under `documents/{doc_id}/`.
- [ ] 3.4 Add tests proving external image URLs remain as metadata `url` values without derived `objectKey`.
- [ ] 3.5 Update chunk metadata construction to extract Markdown image references from each split chunk and persist `url`, `alt`, `source`, and optional `objectKey`.

## 4. Verification

- [ ] 4.1 Run focused document PDF conversion and failure tests.
- [ ] 4.2 Run focused document chunking splitter, segment draft, and workflow tests.
- [ ] 4.3 Run `openspec validate --change enhance-document-image-rewrite`.
- [ ] 4.4 Run the full backend test suite if focused tests pass.
