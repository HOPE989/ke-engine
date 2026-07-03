"use client";

import { FormEvent, useMemo, useState } from "react";

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T | null;
};

type DocumentMetadata = {
  doc_id: string;
  doc_title: string;
  upload_user: string;
  accessible_by: string;
  doc_url: string | null;
  converted_doc_url: string | null;
  status: string;
};

type DocumentChunkResponse = {
  doc_id: string;
  status: string;
  segment_count: number;
};

type RequestLog = {
  label: string;
  endpoint: string;
  payload: unknown;
};

const uploadEndpoint = "/api/v1/document/upload";

function documentEndpoint(docId: string) {
  return `/api/v1/document/${docId}`;
}

function chunkEndpoint(docId: string) {
  return `/api/v1/document/${docId}/chunk`;
}

function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function numberFromInput(value: string) {
  return value === "" ? 0 : Number(value);
}

async function readApiResponse<T>(response: Response): Promise<ApiResponse<T>> {
  try {
    return (await response.json()) as ApiResponse<T>;
  } catch {
    return {
      code: response.status,
      message: `响应不是合法 JSON，HTTP ${response.status}`,
      data: null
    };
  }
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [uploadUser, setUploadUser] = useState("local-tester");
  const [accessibleBy, setAccessibleBy] = useState("local");
  const [docId, setDocId] = useState("");
  const [chunkSize, setChunkSize] = useState(1000);
  const [overlap, setOverlap] = useState(100);
  const [isUploading, setIsUploading] = useState(false);
  const [isQuerying, setIsQuerying] = useState(false);
  const [isChunking, setIsChunking] = useState(false);
  const [response, setResponse] = useState<ApiResponse<
    DocumentMetadata | DocumentChunkResponse
  > | null>(null);
  const [requestLog, setRequestLog] = useState<RequestLog | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedFileLabel = useMemo(() => {
    if (!file) {
      return "未选择文件";
    }
    return `${file.name} · ${formatFileSize(file.size)}`;
  }, [file]);

  const normalizedDocId = docId.trim();
  const canQueryDocument = normalizedDocId.length > 0 && !isQuerying;
  const canChunkDocument =
    normalizedDocId.length > 0 &&
    Number.isInteger(chunkSize) &&
    Number.isInteger(overlap) &&
    chunkSize > 0 &&
    overlap >= 0 &&
    overlap < chunkSize &&
    !isChunking;

  function showResult<T>(
    label: string,
    endpoint: string,
    payload: unknown,
    result: ApiResponse<T>,
    ok: boolean,
    status: number
  ) {
    setRequestLog({ label, endpoint, payload });
    setResponse(result as ApiResponse<DocumentMetadata | DocumentChunkResponse>);
    if (!ok) {
      setError(result.message || `请求失败，HTTP ${status}`);
      return;
    }
    setError(null);
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError(null);
    setResponse(null);
    setRequestLog(null);

    if (!file) {
      setError("请选择要上传的 PDF、Markdown 或文本文件。");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("upload_user", uploadUser);
    formData.append("accessible_by", accessibleBy);

    setIsUploading(true);
    try {
      const result = await fetch(uploadEndpoint, {
        method: "POST",
        body: formData
      });
      const payload = await readApiResponse<DocumentMetadata>(result);

      showResult(
        "上传文档",
        uploadEndpoint,
        {
          file: file.name,
          upload_user: uploadUser,
          accessible_by: accessibleBy
        },
        payload,
        result.ok,
        result.status
      );
      if (payload.data?.doc_id) {
        setDocId(payload.data.doc_id);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传请求失败。");
    } finally {
      setIsUploading(false);
    }
  }

  async function handleQueryDocument() {
    if (!normalizedDocId) {
      setError("请先填写 doc_id。");
      return;
    }

    const endpoint = documentEndpoint(normalizedDocId);
    setIsQuerying(true);
    try {
      const result = await fetch(endpoint);
      const payload = await readApiResponse<DocumentMetadata>(result);
      showResult("查询文档状态", endpoint, null, payload, result.ok, result.status);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "查询请求失败。");
    } finally {
      setIsQuerying(false);
    }
  }

  async function handleChunkDocument() {
    if (!normalizedDocId) {
      setError("请先填写 doc_id。");
      return;
    }
    if (!canChunkDocument) {
      setError("切分参数要求 chunk_size > 0，并且 0 <= overlap < chunk_size。");
      return;
    }

    const endpoint = chunkEndpoint(normalizedDocId);
    const body = {
      chunk_size: chunkSize,
      overlap
    };

    setIsChunking(true);
    try {
      const result = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });
      const payload = await readApiResponse<DocumentChunkResponse>(result);
      showResult("触发文档切分", endpoint, body, payload, result.ok, result.status);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "切分请求失败。");
    } finally {
      setIsChunking(false);
    }
  }

  return (
    <main className="min-h-screen px-5 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <header className="flex flex-col gap-2">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-sky-700">
            KE Engine
          </p>
          <h1 className="text-3xl font-semibold text-gray-950 sm:text-4xl">
            文档端到端测试入口
          </h1>
          <p className="max-w-3xl text-sm leading-6 text-gray-600">
            这页用于串起上传、状态查询和新增切分接口。同源{" "}
            <code className="rounded bg-white/80 px-1.5 py-0.5 text-gray-900">
              /api/v1/*
            </code>{" "}
            请求会通过 Next.js rewrite 转发到本地 FastAPI。
          </p>
        </header>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(360px,460px)]">
          <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-1">
            <form
              onSubmit={handleUpload}
              className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-950">
                    1. 上传文档
                  </h2>
                  <p className="mt-1 text-xs text-gray-500">{uploadEndpoint}</p>
                </div>
                <span className="rounded-md bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700">
                  POST
                </span>
              </div>

              <div className="mt-5 space-y-5">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-gray-800">
                    上传文件
                  </span>
                  <input
                    className="block w-full cursor-pointer rounded-md border border-gray-300 bg-white text-sm text-gray-700 file:mr-4 file:border-0 file:bg-gray-900 file:px-4 file:py-2.5 file:text-sm file:font-medium file:text-white hover:file:bg-gray-700"
                    type="file"
                    accept=".pdf,.md,.markdown,.txt,application/pdf,text/plain,text/markdown"
                    onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  />
                  <span className="mt-2 block text-xs text-gray-500">
                    {selectedFileLabel}
                  </span>
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-gray-800">
                    upload_user
                  </span>
                  <input
                    className="w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
                    value={uploadUser}
                    onChange={(event) => setUploadUser(event.target.value)}
                    placeholder="local-tester"
                    required
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-gray-800">
                    accessible_by
                  </span>
                  <input
                    className="w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
                    value={accessibleBy}
                    onChange={(event) => setAccessibleBy(event.target.value)}
                    placeholder="local"
                    required
                  />
                </label>

                <button
                  className="inline-flex h-11 w-full items-center justify-center rounded-md bg-gray-950 px-4 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400 sm:w-auto"
                  type="submit"
                  disabled={isUploading}
                >
                  {isUploading ? "上传中..." : "上传并生成 doc_id"}
                </button>
              </div>
            </form>

            <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-950">
                    2. 查询转换状态
                  </h2>
                  <p className="mt-1 text-xs text-gray-500">
                    /api/v1/document/{"{doc_id}"}
                  </p>
                </div>
                <span className="rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700">
                  GET
                </span>
              </div>

              <div className="mt-5 space-y-5">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-gray-800">
                    doc_id
                  </span>
                  <input
                    className="w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
                    value={docId}
                    onChange={(event) => setDocId(event.target.value)}
                    placeholder="上传成功后自动填入，也可手动输入"
                  />
                </label>

                <button
                  className="inline-flex h-11 w-full items-center justify-center rounded-md border border-gray-300 bg-white px-4 text-sm font-semibold text-gray-900 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:bg-gray-100 disabled:text-gray-400 sm:w-auto"
                  type="button"
                  onClick={handleQueryDocument}
                  disabled={!canQueryDocument}
                >
                  {isQuerying ? "查询中..." : "查询当前状态"}
                </button>
              </div>
            </section>

            <section className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm lg:col-span-2 xl:col-span-1">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-950">
                    3. 调用新增切分接口
                  </h2>
                  <p className="mt-1 text-xs text-gray-500">
                    /api/v1/document/{"{doc_id}"}/chunk
                  </p>
                </div>
                <span className="rounded-md bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700">
                  POST
                </span>
              </div>

              <div className="mt-5 grid gap-5 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-gray-800">
                    chunk_size
                  </span>
                  <input
                    className="w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
                    type="number"
                    min={1}
                    step={1}
                    value={chunkSize}
                    onChange={(event) => setChunkSize(numberFromInput(event.target.value))}
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-gray-800">
                    overlap
                  </span>
                  <input
                    className="w-full rounded-md border border-gray-300 px-3 py-2.5 text-sm outline-none transition focus:border-sky-500 focus:ring-2 focus:ring-sky-100"
                    type="number"
                    min={0}
                    step={1}
                    value={overlap}
                    onChange={(event) => setOverlap(numberFromInput(event.target.value))}
                  />
                </label>
              </div>

              <div className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-center">
                <button
                  className="inline-flex h-11 w-full items-center justify-center rounded-md bg-gray-950 px-4 text-sm font-semibold text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:bg-gray-400 sm:w-auto"
                  type="button"
                  onClick={handleChunkDocument}
                  disabled={!canChunkDocument}
                >
                  {isChunking ? "切分中..." : "触发切分"}
                </button>
                <p className="text-xs leading-5 text-gray-500">
                  后端要求文档状态为 CONVERTED；如果返回 409，先等待转换 worker 完成后再查询重试。
                </p>
              </div>
            </section>
          </div>

          <aside className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-base font-semibold text-gray-950">端到端响应</h2>
            <div className="mt-4 space-y-3">
              {requestLog ? (
                <div className="rounded-md border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700">
                  <div className="font-semibold text-gray-950">{requestLog.label}</div>
                  <div className="mt-1 break-all font-mono">{requestLog.endpoint}</div>
                </div>
              ) : null}

              <div className="min-h-80 rounded-md border border-gray-200 bg-gray-950 p-4 text-xs leading-5 text-gray-100">
                {error ? (
                  <pre className="whitespace-pre-wrap break-words text-red-200">
                    {error}
                  </pre>
                ) : null}
                {requestLog?.payload ? (
                  <pre className="mt-3 whitespace-pre-wrap break-words text-sky-100">
                    {JSON.stringify({ request: requestLog.payload }, null, 2)}
                  </pre>
                ) : null}
                {response ? (
                  <pre className="mt-3 whitespace-pre-wrap break-words">
                    {JSON.stringify(response, null, 2)}
                  </pre>
                ) : null}
                {!error && !response ? (
                  <p className="text-gray-400">
                    执行上传、查询或切分后，这里会显示后端 APIResponse。
                  </p>
                ) : null}
              </div>
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
