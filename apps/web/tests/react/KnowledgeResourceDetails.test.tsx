import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { KnowledgeResourceDetails } from "../../src/components/knowledge/KnowledgeResourceDetails.tsx";

const ORGANIZATION_ID = "00000000-0000-4000-8000-000000003001";
const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const RESOURCE_ID = "00000000-0000-4000-8000-000000005001";
const VERSION_ID = "00000000-0000-4000-8000-000000006001";
const resource = {
  id: RESOURCE_ID, title: "超长运行手册.pdf", sourceType: "uploaded_file",
  createdAt: "2026-09-05T10:00:00Z", updatedAt: "2026-09-05T10:10:00Z",
  latestVersion: {
    id: VERSION_ID, status: "failed", mediaType: "application/pdf", sizeBytes: 2048,
    sha256: "a".repeat(64), sourceType: "uploaded_file", createdAt: "2026-09-05T10:00:00Z",
    processingStartedAt: "2026-09-05T10:02:00Z", readyAt: null,
    errorCode: "unknown_private_parser_code", retryable: true,
  },
} as const;

function renderDetails(fetchImpl: typeof fetch, props: Partial<React.ComponentProps<typeof KnowledgeResourceDetails>> = {}) {
  vi.stubGlobal("fetch", fetchImpl);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onResourceMissing = vi.fn();
  const onRetrySucceeded = vi.fn(async () => undefined);
  const onDeleteSucceeded = vi.fn(async () => undefined);
  render(<QueryClientProvider client={client}>
    <KnowledgeResourceDetails id="resource-details" organizationId={ORGANIZATION_ID}
      projectId={PROJECT_ID} resourceId={RESOURCE_ID}
      csrfToken="csrf-current" canWrite sessionSignal={new AbortController().signal}
      onResourceMissing={onResourceMissing} onRetrySucceeded={onRetrySucceeded}
      onDeleteSucceeded={onDeleteSucceeded}
      {...props} />
  </QueryClientProvider>);
  return { client, onResourceMissing, onRetrySucceeded, onDeleteSucceeded };
}

afterEach(() => onlineManager.setOnline(true));

test("shows safe complete metadata and manual refresh for a failed resource", async () => {
  renderDetails(vi.fn(async () => Response.json(resource)));
  expect(screen.getByRole("status")).toHaveTextContent("正在读取资料详情");
  expect(await screen.findByText("未知处理错误，请刷新状态或联系管理员")).toBeVisible();
  expect(screen.queryByText("unknown_private_parser_code")).toBeNull();
  const panel = screen.getByRole("region", { name: `${resource.title} 资料详情` });
  expect(within(panel).getByText(resource.title)).toBeVisible();
  for (const value of ["上传文件", "PDF", "2.0 KB", "处理失败", "尚未就绪"]) {
    expect(within(panel).getByText(value)).toBeVisible();
  }
  const times = [...panel.querySelectorAll("time")];
  expect(times.map((time) => time.getAttribute("dateTime"))).toEqual([
    resource.createdAt,
    resource.updatedAt,
    resource.latestVersion.processingStartedAt,
  ]);
  expect(times.every((time) => (time.textContent ?? "").trim().length > 0)).toBe(true);
  expect(panel).not.toHaveTextContent(RESOURCE_ID);
  expect(panel).not.toHaveTextContent(VERSION_ID);
  expect(panel).not.toHaveTextContent("a".repeat(64));
  expect(screen.getByText("状态仅在手动刷新时更新。")) .toBeVisible();
  expect(screen.getByRole("button", { name: "刷新资料状态" })).toBeEnabled();
  expect(screen.queryByRole("link", { name: /下载/ })).toBeNull();
});

test.each([
  ["archive_duplicate_path", "压缩包包含重复路径，无法安全处理。"],
  ["archive_encrypted", "加密压缩包暂不支持，请上传未加密文件。"],
  ["archive_limit_exceeded", "压缩包超过安全处理限制，请缩小或拆分后重新上传。"],
  ["archive_nested", "不支持嵌套压缩包，请解压后分别上传。"],
  ["archive_path_unsafe", "压缩包包含不安全路径，无法处理。"],
  ["database_unavailable", "数据库暂时不可用，请稍后刷新状态。"],
  ["embedding_dimension_mismatch", "向量模型配置不匹配，请联系管理员。"],
  ["embedding_unavailable", "向量服务暂时不可用，请稍后刷新状态。"],
  ["encrypted_pdf_unsupported", "加密 PDF 暂不支持，请上传未加密文件。"],
  ["file_too_large", "文件超过处理大小限制，请缩小或拆分后重新上传。"],
  ["ingestion_retry_exhausted", "自动处理重试已用尽，请联系管理员。"],
  ["lease_lost", "处理任务已中断并等待恢复，请稍后刷新状态。"],
  ["no_extractable_text", "未找到可提取的文字内容，请检查文件内容。"],
  ["object_store_unavailable", "文件存储暂时不可用，请稍后刷新状态。"],
  ["parser_failed", "文件解析失败，请刷新状态或联系管理员。"],
  ["unsupported_media_type", "文件类型不受支持，请转换格式后重新上传。"],
  ["upload_checksum_mismatch", "上传文件校验失败，请重新上传文件。"],
  ["upload_expired", "上传已过期，请重新上传文件。"],
  ["upload_media_type_mismatch", "上传文件类型与声明不一致，请重新上传正确文件。"],
  ["upload_object_missing", "找不到已上传文件，请重新上传文件。"],
  ["upload_size_mismatch", "上传文件大小与声明不一致，请重新上传文件。"],
])("maps the supported version failure code %s to safe Chinese guidance", async (
  errorCode,
  expectedMessage,
) => {
  renderDetails(vi.fn(async () => Response.json({
    ...resource,
    latestVersion: { ...resource.latestVersion, errorCode },
  })));

  expect(await screen.findByRole("alert")).toHaveTextContent(expectedMessage);
  expect(screen.queryByText(errorCode)).toBeNull();
});

test.each(["__proto__", "constructor"])(
  "uses the safe unknown-code fallback for the prototype key %s",
  async (errorCode) => {
    renderDetails(vi.fn(async () => Response.json({
      ...resource,
      latestVersion: { ...resource.latestVersion, errorCode },
    })));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "未知处理错误，请刷新状态或联系管理员",
    );
    expect(screen.queryByText(errorCode)).toBeNull();
  },
);

test("manual refresh performs a fresh read and reveals ready-only download", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(Response.json(resource))
    .mockResolvedValueOnce(Response.json({ ...resource, latestVersion: {
      ...resource.latestVersion, status: "ready", readyAt: "2026-09-05T10:11:00Z",
      errorCode: null, retryable: false,
    } }));
  renderDetails(fetchMock);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "刷新资料状态" }));
  const link = await screen.findByRole("link", { name: /下载资料.*新标签页/ });
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("a pending manual refresh hides previously authorized detail and download", async () => {
  let resolveRefresh!: (response: Response) => void;
  const refreshResponse = new Promise<Response>((resolve) => { resolveRefresh = resolve; });
  const readyResource = { ...resource, latestVersion: {
    ...resource.latestVersion,
    status: "ready" as const,
    readyAt: "2026-09-05T10:11:00Z",
    errorCode: null,
    retryable: false,
  } };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(Response.json(readyResource))
    .mockImplementationOnce(async () => refreshResponse);
  renderDetails(fetchMock);
  const user = userEvent.setup();
  await screen.findByRole("link", { name: /下载资料.*新标签页/ });

  await user.click(screen.getByRole("button", { name: "刷新资料状态" }));

  expect(screen.getByRole("status")).toHaveTextContent("正在读取资料详情");
  expect(screen.queryByRole("link", { name: /下载资料/ })).toBeNull();
  expect(screen.queryByText(resource.title)).toBeNull();
  await act(async () => resolveRefresh(Response.json(resource)));
  expect(await screen.findByText("未知处理错误，请刷新状态或联系管理员")).toBeVisible();
});

test("an offline paused manual refresh hides previously authorized detail and download", async () => {
  const readyResource = { ...resource, latestVersion: {
    ...resource.latestVersion,
    status: "ready" as const,
    readyAt: "2026-09-05T10:11:00Z",
    errorCode: null,
    retryable: false,
  } };
  const fetchMock = vi.fn(async () => Response.json(readyResource));
  renderDetails(fetchMock);
  const user = userEvent.setup();
  await screen.findByRole("link", { name: /下载资料.*新标签页/ });
  onlineManager.setOnline(false);

  await user.click(screen.getByRole("button", { name: "刷新资料状态" }));

  expect(screen.getByRole("status")).toHaveTextContent("网络连接恢复后将读取最新资料详情");
  expect(screen.queryByRole("link", { name: /下载资料/ })).toBeNull();
  expect(screen.queryByText(resource.title)).toBeNull();
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test.each([
  ["queued", { ...resource, latestVersion: { ...resource.latestVersion,
    status: "queued" as const, processingStartedAt: null } }, "等待处理"],
  ["without a version", { ...resource, sourceType: "zip_entry", latestVersion: null },
    "等待生成首个版本"],
])("renders %s detail without a download", async (_name, response, expectedStatus) => {
  renderDetails(vi.fn(async () => Response.json(response)));

  expect(await screen.findByText(expectedStatus)).toBeVisible();
  expect(screen.queryByRole("link", { name: /下载资料/ })).toBeNull();
  if (_name === "without a version") {
    expect(screen.getByText("ZIP 内文件")).toBeVisible();
  }
});

test("retryable detail failures preserve correlation and offer explicit read retry", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ code: "database_unavailable",
      message: "知识服务暂时不可用", traceId: "trace-detail-503" }),
    { status: 503, headers: { "Content-Type": "application/json" } }))
    .mockResolvedValueOnce(Response.json(resource));
  renderDetails(fetchMock);
  const user = userEvent.setup();
  expect(await screen.findByRole("alert")).toHaveTextContent("知识服务暂时不可用");
  expect(screen.getByText("请求编号：trace-detail-503")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "重试读取资料详情" }));
  expect(await screen.findByText("未知处理错误，请刷新状态或联系管理员")).toBeVisible();
});

test("a local 404 hides details and asks the list boundary to reauthorize", async () => {
  const { onResourceMissing } = renderDetails(vi.fn(async () => new Response(JSON.stringify({
    code: "not_found", message: "资料不存在", traceId: "trace-detail-404",
  }), { status: 404, headers: { "Content-Type": "application/json" } })));
  expect(await screen.findByText("该资料已不可用，正在重新检查项目知识访问权限。")) .toBeVisible();
  expect(onResourceMissing).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "刷新资料状态" })).toBeNull();
});

test("contract failures do not offer an ineffective retry", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  renderDetails(vi.fn(async () => Response.json({ ...resource,
    id: "00000000-0000-4000-8000-000000005099" })));
  expect(await screen.findByRole("alert")).toHaveTextContent("服务器返回的数据格式不正确");
  expect(screen.queryByRole("button", { name: /重试/ })).toBeNull();
});

test("read-only detail never exposes retry or delete actions", async () => {
  renderDetails(vi.fn(async () => Response.json(resource)), { canWrite: false });

  await screen.findByRole("region", { name: `${resource.title} 资料详情` });
  expect(screen.queryByRole("button", { name: "重新处理失败版本" })).toBeNull();
  expect(screen.queryByRole("button", { name: "删除资料" })).toBeNull();
});

test("a writer can explicitly retry the exact server-declared retryable failed version", async () => {
  const queued = { ...resource, updatedAt: "2026-09-05T10:12:00Z", latestVersion: {
    ...resource.latestVersion,
    status: "queued" as const,
    processingStartedAt: null,
    errorCode: null,
    retryable: false,
  } };
  const requests: Request[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    return request.method === "POST" ? Response.json(queued) : Response.json(resource);
  });
  const { onRetrySucceeded } = renderDetails(fetchMock);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));

  expect(await screen.findByText("等待处理")).toBeVisible();
  expect(onRetrySucceeded).toHaveBeenCalledWith(queued);
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
  expect(screen.queryByRole("button", { name: "重新处理失败版本" })).toBeNull();
});

test("delete cancellation names the resource, sends no DELETE, and returns focus", async () => {
  const requests: Request[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(resource);
  });
  renderDetails(fetchMock);
  const user = userEvent.setup();

  const deleteButton = await screen.findByRole("button", { name: "删除资料" });
  await user.click(deleteButton);
  const confirmation = screen.getByRole("group", { name: "确认删除资料" });
  expect(confirmation).toHaveTextContent(resource.title);
  expect(confirmation).toHaveTextContent("后端保留数据不会立即物理清除");
  await user.click(within(confirmation).getByRole("button", { name: "取消删除" }));

  expect(requests.filter((request) => request.method === "DELETE")).toHaveLength(0);
  expect(screen.queryByRole("group", { name: "确认删除资料" })).toBeNull();
  await waitFor(() => expect(deleteButton).toHaveFocus());
});

test("a synchronous double confirm sends one DELETE and waits for page-owned cleanup", async () => {
  let resolveDelete!: (response: Response) => void;
  const pendingDelete = new Promise<Response>((resolve) => { resolveDelete = resolve; });
  const requests: Request[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "DELETE") return await pendingDelete;
    return Response.json(resource);
  });
  const { onDeleteSucceeded } = renderDetails(fetchMock);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "删除资料" }));
  const confirm = screen.getByRole("button", { name: "确认删除资料" });

  fireEvent.click(confirm);
  fireEvent.click(confirm);

  await waitFor(() => {
    expect(requests.filter((request) => request.method === "DELETE")).toHaveLength(1);
  });
  expect(screen.getByRole("button", { name: "正在删除资料" })).toBeDisabled();
  await act(async () => resolveDelete(new Response(null, { status: 204 })));
  expect(onDeleteSucceeded).toHaveBeenCalledWith(resource);
});

test.each([
  [403, "csrf_failed", "请求来源验证失败"],
  [422, "validation_error", "请求参数无效"],
  [500, "internal_error", "服务器内部错误"],
  [503, "database_unavailable", "知识服务暂时不可用"],
])("delete HTTP %i preserves resource facts, error trace, and a manual retry path", async (
  status,
  code,
  message,
) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method === "DELETE") return Response.json({
      code,
      message,
      traceId: `trace-delete-${status}`,
    }, { status });
    return Response.json(resource);
  });
  const { onDeleteSucceeded } = renderDetails(fetchMock);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "删除资料" }));
  await user.click(screen.getByRole("button", { name: "确认删除资料" }));

  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.getByText(`请求编号：trace-delete-${status}`)).toBeVisible();
  expect(screen.getAllByText(resource.title).length).toBeGreaterThan(0);
  expect(onDeleteSucceeded).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "确认删除资料" })).toBeEnabled();
});

test("an unknown thrown delete failure is normalized without leaking its value", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    if ((input as Request).method === "DELETE") throw { privateCause: "delete-secret" };
    return Response.json(resource);
  });
  const { onDeleteSucceeded } = renderDetails(fetchMock);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "删除资料" }));
  await user.click(screen.getByRole("button", { name: "确认删除资料" }));

  expect(await screen.findByText("无法连接服务器，请检查网络")).toBeVisible();
  expect(screen.queryByText(/delete-secret/)).toBeNull();
  expect(onDeleteSucceeded).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "确认删除资料" })).toBeEnabled();
});

test("collapsing aborts an in-flight command and late completion cannot run cleanup", async () => {
  let operationSignal: AbortSignal | null = null;
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    if (request.method !== "DELETE") return Response.json(resource);
    operationSignal = request.signal;
    return await new Promise<Response>((_resolve, reject) => {
      request.signal.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  const onDeleteSucceeded = vi.fn(async () => undefined);
  const { unmount } = render(<QueryClientProvider client={new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })}>
    <KnowledgeResourceDetails id="resource-details" organizationId={ORGANIZATION_ID}
      projectId={PROJECT_ID} resourceId={RESOURCE_ID} csrfToken="csrf-current" canWrite
      sessionSignal={new AbortController().signal} onResourceMissing={vi.fn()}
      onRetrySucceeded={vi.fn(async () => undefined)} onDeleteSucceeded={onDeleteSucceeded} />
  </QueryClientProvider>);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "删除资料" }));
  await user.click(screen.getByRole("button", { name: "确认删除资料" }));

  unmount();

  expect(operationSignal).not.toBeNull();
  expect(operationSignal!.aborted).toBe(true);
  expect(onDeleteSucceeded).not.toHaveBeenCalled();
});

test("an offline retry attempts once immediately and is never queued for reconnect replay", async () => {
  const requests: Request[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const request = input as Request;
    requests.push(request);
    if (request.method === "POST") throw new TypeError("offline");
    return Response.json(resource);
  });
  renderDetails(fetchMock);
  const user = userEvent.setup();
  const retry = await screen.findByRole("button", { name: "重新处理失败版本" });
  onlineManager.setOnline(false);

  await user.click(retry);

  expect(await screen.findByText("无法连接服务器，请检查网络")).toBeVisible();
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
  onlineManager.setOnline(true);
  await act(async () => { await Promise.resolve(); });
  expect(requests.filter((request) => request.method === "POST")).toHaveLength(1);
});

test.each(["retry", "delete"] as const)(
  "a %s contract failure requires a fresh detail read before commands return",
  async (operation) => {
    const requests: Request[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const request = input as Request;
      requests.push(request);
      if (request.method === "POST") return new Response("{broken", { status: 200 });
      if (request.method === "DELETE") return new Response("unexpected", { status: 202 });
      return Response.json(resource);
    });
    renderDetails(fetchMock);
    const user = userEvent.setup();
    if (operation === "retry") {
      await user.click(await screen.findByRole("button", { name: "重新处理失败版本" }));
    } else {
      await user.click(await screen.findByRole("button", { name: "删除资料" }));
      await user.click(screen.getByRole("button", { name: "确认删除资料" }));
    }

    expect(await screen.findByText("服务器返回的数据格式不正确，请联系管理员")).toBeVisible();
    expect(screen.queryByRole("button", { name: "重新处理失败版本" })).toBeNull();
    expect(screen.queryByRole("button", { name: "删除资料" })).toBeNull();
    expect(requests.filter((request) =>
      request.method === (operation === "retry" ? "POST" : "DELETE")
    )).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "刷新资料状态" }));

    expect(await screen.findByRole("button", { name: "重新处理失败版本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "删除资料" })).toBeEnabled();
    expect(requests.filter((request) => request.method === "GET")).toHaveLength(2);
  },
);
