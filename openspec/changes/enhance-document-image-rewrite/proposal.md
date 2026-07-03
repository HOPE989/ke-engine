## Why

Converted PDF Markdown currently rewrites image links and fills every image alt text with the mock value `图片描述`. That makes preview usable, but it hides per-image failures and does not provide reliable image metadata for later multimodal retrieval.

This change makes image handling explicit: document conversion succeeds when the main Markdown is converted, image processing degrades per image, and chunk metadata records the images contained in each segment.

## What Changes

- Replace mock image alt text with model-generated descriptions during the asynchronous PDF conversion worker flow.
- Treat image upload, image URL rewrite, and image description generation as per-image best-effort work that MUST NOT fail the whole document conversion.
- Mark per-image failures in Markdown with alt text `图片解析错误`.
- Preserve successful image preview by rewriting image references to MinIO URLs when possible.
- Add chunk-level image metadata so each persisted segment records the Markdown images it contains.
- Keep chunking synchronous and free of model calls; it only extracts image information already present in converted Markdown.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `document-upload`: Change PDF image Markdown rewriting from first-version mock alt text to best-effort URL and model-description rewriting with per-image failure degradation.
- `document-chunking`: Add segment metadata for images contained in each chunk, enabling later multimodal retrieval assembly.

## Impact

- Affects PDF conversion helpers in `backend/app/modules/document/markdown.py`.
- Affects PDF conversion orchestration in `backend/app/modules/document/workflow.py` and worker resource injection where image description generation is called.
- Affects chunk metadata creation in `backend/app/modules/document/chunking.py`.
- Updates tests covering PDF conversion image rewriting, image failure degradation, and segment metadata.
- Does not add new document lifecycle states.
- Does not require chunking to call an LLM.
