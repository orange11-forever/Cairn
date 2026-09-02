import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { createAppQueryClient } from "../../src/app/queryClient.ts";
import { DocumentsPanel } from "../../src/components/DocumentsPanel.tsx";

const USER_A = "00000000-0000-4000-8000-000000001001";
const USER_B = "00000000-0000-4000-8000-000000001002";

const DOCUMENTS = [
  {
    id: "00000000-0000-4000-8000-000000000001",
    title: "产品需求文档",
    status: "completed",
  },
  {
    id: "00000000-0000-4000-8000-000000000002",
    title: "API 接口设计",
    status: "processing",
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    title: "测试报告 v2",
    status: "completed",
  },
  {
    id: "00000000-0000-4000-8000-000000000004",
    title: "部署手册",
    status: "failed",
  },
] as const;

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function stubDocumentFetch() {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(DOCUMENTS)));
}

function renderDocuments(queryClient: QueryClient, userId: string) {
  return render(
    <QueryClientProvider client={queryClient}>
      <DocumentsPanel userId={userId} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("a second user does not receive the first user's cached documents", async () => {
  stubDocumentFetch();
  const queryClient = createAppQueryClient();
  const user = userEvent.setup();

  const first = renderDocuments(queryClient, USER_A);
  await user.click(screen.getByRole("button", { name: "加载文档" }));
  expect(await screen.findAllByRole("listitem")).toHaveLength(4);
  first.unmount();

  renderDocuments(queryClient, USER_B);
  expect(document.querySelectorAll("#document-list li")).toHaveLength(0);
  expect(screen.getByText("点击「加载文档」开始")).toBeInTheDocument();
});

test("cancel aborts the current query and returns to idle", async () => {
  let capturedSignal: AbortSignal | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          capturedSignal = init?.signal ?? undefined;
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    ),
  );

  const user = userEvent.setup();
  renderDocuments(createAppQueryClient(), USER_A);
  await user.click(screen.getByRole("button", { name: "加载文档" }));
  await user.click(screen.getByRole("button", { name: "取消" }));

  await waitFor(() => expect(capturedSignal?.aborted).toBe(true));
  expect(await screen.findByText("点击「加载文档」开始")).toBeInTheDocument();
});

test("keeps the document list primary and upload in a secondary work area", () => {
  renderDocuments(createAppQueryClient(), USER_A);

  expect(screen.getByRole("region", { name: "知识文档" })).toHaveClass("documents-panel");
  expect(screen.getByRole("list", { name: "文档列表" })).toBeInTheDocument();
  expect(screen.getByRole("form", { name: "文档上传" })).toBeInTheDocument();
  expect(screen.getByRole("complementary", { name: "工作区提示" })).toBeInTheDocument();
});

test("uses the mascot workspace status when no documents are available", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
  const user = userEvent.setup();
  renderDocuments(createAppQueryClient(), USER_A);

  await user.click(screen.getByRole("button", { name: "加载文档" }));

  const aside = screen.getByRole("complementary", { name: "工作区提示" });
  expect(await within(aside).findByRole("heading", { name: "建立知识空间" })).toBeInTheDocument();
  expect(within(aside).getByRole("img", { name: "岑宁，Cairn 知识向导" })).toBeInTheDocument();
});

test("keeps recovery copy when an active status filter has no matches", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([DOCUMENTS[0]])));
  const user = userEvent.setup();
  renderDocuments(createAppQueryClient(), USER_A);

  await user.click(screen.getByRole("button", { name: "加载文档" }));
  await user.click(await screen.findByRole("radio", { name: "处理中 0" }));

  expect(screen.getByRole("status", { name: "筛选结果" })).toHaveTextContent(
    "当前筛选下没有文档",
  );
});
