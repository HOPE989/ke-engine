"use client";

import { FormEvent, useMemo, useState } from "react";

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T | null;
};

type DocumentMetadata = {
  doc_id: number;
  doc_title: string;
  upload_user: string;
  accessible_by: string;
  doc_url: string | null;
  converted_doc_url: string | null;
  status: string;
};

const uploadEndpoint = "/api/v1/document/upload";

function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [uploadUser, setUploadUser] = useState("local-tester");
  const [accessibleBy, setAccessibleBy] = useState("local");
  const [isUploading, setIsUploading] = useState(false);
  const [response, setResponse] = useState<ApiResponse<DocumentMetadata> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedFileLabel = useMemo(() => {
    if (!file) {
      return "未选择文件";
    }
    return `${file.name} · ${formatFileSize(file.size)}`;
  }, [file]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    setError(null);
    setResponse(null);

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
      const payload = (await result.json()) as ApiResponse<DocumentMetadata>;

      setResponse(payload);
      if (!result.ok) {
        setError(payload.message || `上传失败，HTTP ${result.status}`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传请求失败。");
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <main className="min-h-screen px-5 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
        <header className="flex flex-col gap-2">
          <p className="text-sm font-medium uppercase tracking-[0.18em] text-sky-700">
            KE Engine
          </p>
          <h1 className="text-3xl font-semibold text-gray-950 sm:text-4xl">
            文档上传测试页
          </h1>
          <p className="max-w-2xl text-sm leading-6 text-gray-600">
            页面会提交 multipart 表单到 <code className="rounded bg-white/80 px-1.5 py-0.5 text-gray-900">{uploadEndpoint}</code>，
            Next.js 本地开发环境默认转发到 <code className="rounded bg-white/80 px-1.5 py-0.5 text-gray-900">http://localhost:8000</code>。
          </p>
        </header>

        <section className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <form
            onSubmit={handleSubmit}
            className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
          >
            <div className="space-y-5">
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
                {isUploading ? "上传中..." : "上传并转换"}
              </button>
            </div>
          </form>

          <aside className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm">
            <h2 className="text-base font-semibold text-gray-950">响应结果</h2>
            <div className="mt-4 min-h-64 rounded-md border border-gray-200 bg-gray-950 p-4 text-xs leading-5 text-gray-100">
              {error ? (
                <pre className="whitespace-pre-wrap break-words text-red-200">
                  {error}
                </pre>
              ) : null}
              {response ? (
                <pre className="mt-3 whitespace-pre-wrap break-words">
                  {JSON.stringify(response, null, 2)}
                </pre>
              ) : null}
              {!error && !response ? (
                <p className="text-gray-400">上传后这里会显示后端 APIResponse。</p>
              ) : null}
            </div>
          </aside>
        </section>
      </div>
    </main>
  );
}
