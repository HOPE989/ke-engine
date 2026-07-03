## Context

The document conversion flow currently accepts uploaded PDFs, runs MinerU in the conversion worker, extracts a ZIP, uploads images, rewrites Markdown image links to MinIO URLs, and stores the final Markdown at `documents/{doc_id}/converted/document.md`.

The image handling helper currently has overlapping responsibilities: one function rewrites image URLs while assigning `图片描述`, and another function rewrites all image alt text to the same mock value. This produces previewable Markdown but loses useful image semantics and treats image rewrite failures as full document conversion failures.

The chunking flow later downloads converted Markdown, splits it by headers and length, and persists `knowledge_segment.metadata` with document and LangChain splitter metadata. It does not currently record which images appear in each chunk.

## Goals / Non-Goals

**Goals:**

- Keep document conversion successful when the main Markdown is selected, rewritten as much as possible, and uploaded successfully.
- Make image processing per-image best-effort: image upload, URL rewrite, and description generation failures must not fail the whole document.
- Replace mock `图片描述` with model-generated image descriptions when generation succeeds.
- Use `图片解析错误` as the visible alt text for image references whose upload, URL rewrite, or description generation fails.
- Preserve converted Markdown preview by rewriting image URLs to MinIO URLs whenever image upload succeeds.
- Persist chunk-level image metadata by extracting image URL and alt text from converted Markdown chunks.
- Keep chunking synchronous and deterministic: chunking extracts image metadata from converted Markdown and does not call the image description model.

**Assumptions:**

- Image description runtime configuration is present and valid before conversion work starts. Missing credentials such as `OPENAI_API_KEY` or provider construction misconfiguration are treated as deployment setup failures, not acceptance scenarios for this change.
- Description generation has two business outcomes: success with text whose `strip()` is non-empty, or generic failure that produces `图片解析错误`. Provider-specific setup failures, timeout categories, and response-shape details are not separately specified.
- MinerU output is expected to use stable relative image references and non-conflicting image paths for a single conversion.
- User-uploaded Markdown documents do not include sidecar image assets; external image URLs in Markdown are not fetched or described.

**Non-Goals:**

- Add a new document lifecycle state for partial image failures.
- Add vector storage, embeddings, or retrieval-time multimodal assembly.
- Add a retry queue for failed per-image processing.
- Fetch or describe arbitrary external image URLs.
- Guarantee every converted image has a real model description.
- Implement a complete CommonMark image parser or support uncommon image syntax outside MinerU-style inline image references.
- Resolve conflicting MinerU image outputs that contain different directories with the same image basename.

## Decisions

### Decision 1: Main Markdown success defines conversion success

PDF conversion should fail only when the main conversion artifact cannot be produced: MinerU request failure, invalid ZIP, unsafe ZIP, no usable Markdown, unreadable Markdown, or final converted Markdown upload failure. Per-image failures should be visible in the Markdown but must not roll the document back to `UPLOADED`.

Alternative considered: fail conversion when any image fails. That made `CONVERTED` stronger, but it blocks usable text documents because of one bad image and does not match the preview-first upload flow.

### Decision 2: Convert worker performs URL rewrite and image description

The HTTP upload endpoint already returns after original file storage and conversion event dispatch. The conversion worker is the correct place to do image description because it is asynchronous from the client's perspective and already has access to extracted image files.

Chunking should not call the image model. It is a synchronous endpoint and should remain bounded to Markdown download, splitting, and persistence.

Alternative considered: generate descriptions during chunking. That gives direct chunk context but blocks a synchronous request and duplicates work when the same image appears in multiple chunks.

### Decision 3: Use a shared bounded Markdown image parser

Replace the duplicate `rewrite_markdown_image_links` and `backfill_markdown_image_descriptions` parsing behavior with one shared parser for supported Markdown image references. Conversion and chunking should each consume the parsed image references for their own outputs instead of sharing one large conversion/chunk metadata helper.

The conversion rewrite operation should parse Markdown image references once per conversion. For each match:

1. Preserve the original target unless a MinIO URL is available.
2. Use model-generated description when URL/image processing and description generation both succeed with text whose `strip()` is non-empty.
3. Use `图片解析错误` when local image upload, URL rewrite, or description generation generically fails.
4. Leave already-absolute external URLs unchanged and preserve their original alt unless the system has a local extracted image match.

Alternative considered: keep URL rewrite and alt backfill as separate passes. That preserves the current structure but repeats responsibilities and makes it harder to distinguish successful image description from fallback text.

### Decision 4: Extract chunk images from converted Markdown

The chunking stage should parse each split chunk's Markdown text and add `metadata.images` with the images found in that chunk. This does require another Markdown image scan, but it keeps chunk-image ownership tied to the actual final chunk content. It also avoids coupling conversion to current chunking rules.

Each image metadata entry should include the final Markdown URL and alt text. If the URL belongs to configured document storage, the implementation may also include an object key to allow later retrieval-time download without relying on public URL access.

Alternative considered: compute chunk image ownership during conversion. That would avoid a second scan but would couple conversion to chunk split parameters, which are request-time inputs.

## Risks / Trade-offs

- Model calls can slow conversion worker throughput -> make description best-effort and avoid failing the document on per-image errors.
- Per-image failures become less visible to operators if only Markdown alt changes -> log per-image failures with doc id and image target while keeping secrets and raw provider errors out of user responses.
- `图片解析错误` may overwrite a useful original alt on model failure -> this is intentional for local extracted images because the user asked for explicit image processing failure visibility.
- External absolute image URLs cannot be safely described without fetching arbitrary remote content -> leave their URL unchanged and keep the original alt unless a local image match exists.
- A bounded parser will not support every CommonMark image form -> acceptable because conversion input is MinerU output, and centralizing the parser keeps conversion and chunking on the same supported syntax.

## Migration Plan

This is an additive behavior change for future conversions and chunking runs. Existing converted Markdown objects and existing `knowledge_segment` rows are not migrated.

Rollback is to restore the previous conversion behavior that writes `图片描述` and to stop adding `metadata.images` during chunking. Existing rows with `metadata.images` remain valid JSONB metadata.

## Open Questions

- The exact image description provider interface and prompt can be selected during implementation, but it must support a mocked test implementation and must not be called from chunking.
