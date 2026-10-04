import { QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  useState,
  type ComponentProps,
  type Dispatch,
  type SetStateAction,
} from "react";
import { beforeEach, expect, test, vi } from "vitest";

import { ApiError } from "../../src/api/errors.ts";
import { createAppQueryClient } from "../../src/app/queryClient.ts";
import type { KnowledgeBatchDetail } from "../../src/api/knowledgeUploads.ts";
import { KnowledgeUploadBatch } from "../../src/components/knowledge/KnowledgeUploadBatch.tsx";
import {
  type KnowledgeUploadBatchController,
  type KnowledgeUploadBatchState,
  type KnowledgeUploadFilePhase,
  type KnowledgeUploadFileState,
  type KnowledgeUploadDependencies,
  useKnowledgeUploadBatch,
} from "../../src/hooks/useKnowledgeUploadBatch.ts";
import {
  KNOWLEDGE_UPLOAD_ACCEPT,
  prepareKnowledgeFiles,
  validateKnowledgeFiles,
} from "../../src/lib/knowledgeUpload.ts";

vi.mock("../../src/hooks/useKnowledgeUploadBatch.ts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/hooks/useKnowledgeUploadBatch.ts")>();
  return { ...actual, useKnowledgeUploadBatch: vi.fn() };
});

const ORGANIZATION_ID = "00000000-0000-4000-8000-000000002001";
const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const BATCH_ID = "00000000-0000-4000-8000-000000008001";
const ROOT_ITEM_ID = "00000000-0000-4000-8000-000000009001";
const CHILD_1_ID = "00000000-0000-4000-8000-000000009002";
const CHILD_2_ID = "00000000-0000-4000-8000-000000009003";

const EMPTY_STATE: KnowledgeUploadBatchState = {
  files: [],
  issues: [],
  batchId: null,
  startedAt: null,
  pending: false,
  error: null,
  batchError: null,
  batch: null,
  batchTrackingStopped: false,
  batchPollingTimedOut: false,
  lastFinalSummary: null,
};

let initialState: KnowledgeUploadBatchState;
let setFakeUploadState: Dispatch<SetStateAction<KnowledgeUploadBatchState>> | null;
const actionSpies = {
  select: vi.fn(),
  start: vi.fn<() => Promise<void>>(),
  cancel: vi.fn(),
  retryFailed: vi.fn<() => Promise<void>>(),
  clear: vi.fn(),
  refreshBatch: vi.fn<() => Promise<void>>(),
};

function selectedFile(
  file: File,
  phase: KnowledgeUploadFilePhase = "selected",
  overrides: Partial<KnowledgeUploadFileState> = {},
): KnowledgeUploadFileState {
  return {
    file,
    phase,
    progress: null,
    error: null,
    failureStage: null,
    itemId: null,
    ...overrides,
  };
}

function useFakeKnowledgeUploadBatch(): KnowledgeUploadBatchController {
  const [state, setState] = useState(initialState);
  setFakeUploadState = setState;
  return {
    ...state,
    select(files) {
      actionSpies.select(files);
      setState({
        ...EMPTY_STATE,
        files: files.map((file) => selectedFile(file)),
        issues: validateKnowledgeFiles(files),
      });
    },
    async start() {
      await actionSpies.start();
    },
    cancel() {
      actionSpies.cancel();
    },
    async retryFailed() {
      await actionSpies.retryFailed();
    },
    clear() {
      actionSpies.clear();
      setState(EMPTY_STATE);
    },
    async refreshBatch() {
      await actionSpies.refreshBatch();
    },
  };
}

function renderUploadBatch() {
  const props: ComponentProps<typeof KnowledgeUploadBatch> = {
    organizationId: ORGANIZATION_ID,
    projectId: PROJECT_ID,
    csrfToken: "csrf-upload-test",
    sessionSignal: new AbortController().signal,
    onAccessUnavailable: vi.fn(),
  };
  return render(<KnowledgeUploadBatch {...props} />);
}

function fileRow(name: string): HTMLElement {
  const row = screen.getByText(name).closest("li");
  if (row === null) throw new Error(`Missing file row for ${name}`);
  return row;
}

function batchDetail(
  items: KnowledgeBatchDetail["items"],
  status: KnowledgeBatchDetail["status"] = "processing",
): KnowledgeBatchDetail {
  return {
    id: BATCH_ID,
    status,
    itemCount: items.length,
    readyCount: items.filter((item) => item.status === "ready").length,
    failedCount: items.filter((item) => item.status === "failed").length,
    createdAt: "2026-09-04T09:00:00Z",
    completedAt: status === "processing" ? null : "2026-09-04T09:01:00Z",
    items,
  };
}

function batchItem({
  id,
  parentItemId = null,
  normalizedPath,
  status = "processing",
  errorDetail = null,
}: {
  id: string;
  parentItemId?: string | null;
  normalizedPath: string;
  status?: KnowledgeBatchDetail["items"][number]["status"];
  errorDetail?: string | null;
}): KnowledgeBatchDetail["items"][number] {
  return {
    id,
    parentItemId,
    normalizedPath,
    mediaType: "text/markdown",
    sizeBytes: 128,
    status,
    resourceId: status === "ready" ? "00000000-0000-4000-8000-000000007001" : null,
    resourceVersionId: status === "ready"
      ? "00000000-0000-4000-8000-000000007002"
      : null,
    errorCode: status === "failed" ? "parse_failed_internal" : null,
    errorDetail,
    createdAt: "2026-09-04T09:00:00Z",
    completedAt: status === "processing" ? null : "2026-09-04T09:01:00Z",
  };
}

beforeEach(() => {
  initialState = EMPTY_STATE;
  setFakeUploadState = null;
  for (const spy of Object.values(actionSpies)) spy.mockReset();
  actionSpies.start.mockResolvedValue(undefined);
  actionSpies.retryFailed.mockResolvedValue(undefined);
  actionSpies.refreshBatch.mockResolvedValue(undefined);
  vi.mocked(useKnowledgeUploadBatch).mockImplementation(useFakeKnowledgeUploadBatch);
});

test("uses one native multi-file input and renders immediate file and batch validation", async () => {
  const user = userEvent.setup({ applyAccept: false });
  renderUploadBatch();
  const input = screen.getByLabelText("上传知识资料");

  expect(input).toHaveAttribute("type", "file");
  expect(input).toHaveAttribute("multiple");
  expect(input).toHaveAttribute("accept", KNOWLEDGE_UPLOAD_ACCEPT);
  await user.upload(input, [
    new File(["ok"], "可用资料.pdf", { type: "application/pdf" }),
    new File(["bad"], "错误资料.exe", { type: "application/octet-stream" }),
  ]);

  expect(within(fileRow("错误资料.exe")).getByRole("alert"))
    .toHaveTextContent("文件类型不受支持");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "开始上传" })).toBeDisabled();
  expect(actionSpies.start).not.toHaveBeenCalled();

  const duplicateA = new File(["a"], "重复.md", { type: "text/markdown" });
  const duplicateB = new File(["b"], "重复.md", { type: "text/markdown" });
  await user.upload(input, [duplicateA, duplicateB]);
  expect(screen.getByRole("alert", { name: "批次校验错误" }))
    .toHaveTextContent("同一批次包含重复文件名");
  expect(screen.getByRole("button", { name: "开始上传" })).toBeDisabled();

  const invalidAndLarge = new File(["x"], "../invalid.pdf", { type: "application/pdf" });
  Object.defineProperty(invalidAndLarge, "size", {
    configurable: true,
    value: 50 * 1024 * 1024 + 1,
  });
  const unsupportedAndEmpty = new File([], "unsupported.exe");
  await user.upload(input, [invalidAndLarge, unsupportedAndEmpty]);
  expect(within(fileRow(invalidAndLarge.name)).getAllByRole("alert").map((alert) => alert.textContent))
    .toEqual(expect.arrayContaining([
      expect.stringContaining("文件名"),
      expect.stringContaining("50.0 MB"),
    ]));
  expect(within(fileRow(unsupportedAndEmpty.name)).getAllByRole("alert").map((alert) => alert.textContent))
    .toEqual(expect.arrayContaining(["文件类型不受支持", "文件不能为空"]));
});

test("keeps the native input keyboard reachable and starts a valid selection", async () => {
  const user = userEvent.setup();
  renderUploadBatch();
  const input = screen.getByLabelText("上传知识资料");
  await user.tab();
  expect(input).toHaveFocus();

  const pdf = new File(["pdf"], "键盘选择.pdf", { type: "application/pdf" });
  await user.upload(input, pdf);
  expect(screen.getByText(pdf.name)).toHaveClass("knowledge-upload-file-name");
  await user.click(screen.getByRole("button", { name: "开始上传" }));
  expect(actionSpies.start).toHaveBeenCalledTimes(1);
});

test.each([
  {
    name: "Worker failure",
    state: () => ({
      ...EMPTY_STATE,
      batchId: BATCH_ID,
      files: [selectedFile(
        new File(["worker"], "Worker失败.pdf", { type: "application/pdf" }),
        "failed",
        {
          itemId: ROOT_ITEM_ID,
          error: new ApiError("http", "Worker 无法解析", { status: 422 }),
          failureStage: "worker",
        },
      )],
    }),
    hasDedicatedRetry: false,
  },
  {
    name: "cancelled upload",
    state: () => ({
      ...EMPTY_STATE,
      files: [selectedFile(
        new File(["cancelled"], "已取消.pdf", { type: "application/pdf" }),
        "cancelled",
      )],
    }),
    hasDedicatedRetry: false,
  },
  {
    name: "Worker processing",
    state: () => ({
      ...EMPTY_STATE,
      batchId: BATCH_ID,
      files: [selectedFile(
        new File(["processing"], "处理中.pdf", { type: "application/pdf" }),
        "processing",
        { itemId: ROOT_ITEM_ID },
      )],
    }),
    hasDedicatedRetry: false,
  },
  {
    name: "ready file",
    state: () => ({
      ...EMPTY_STATE,
      batchId: BATCH_ID,
      files: [selectedFile(
        new File(["ready"], "已就绪.pdf", { type: "application/pdf" }),
        "ready",
        { itemId: ROOT_ITEM_ID },
      )],
    }),
    hasDedicatedRetry: false,
  },
  {
    name: "hash preparation failure",
    state: () => {
      const error = new ApiError("network", "无法读取文件，请重新选择");
      return {
        ...EMPTY_STATE,
        error,
        files: [selectedFile(
          new File(["hash"], "读取失败.pdf", { type: "application/pdf" }),
          "failed",
          { error, failureStage: "hash" },
        )],
      };
    },
    hasDedicatedRetry: false,
  },
  {
    name: "active hashing",
    state: () => ({
      ...EMPTY_STATE,
      pending: true,
      files: [selectedFile(
        new File(["hashing"], "计算中.pdf", { type: "application/pdf" }),
        "hashing",
      )],
    }),
    hasDedicatedRetry: false,
  },
  {
    name: "mixed confirmed and local transfer failure",
    state: () => ({
      ...EMPTY_STATE,
      batchId: BATCH_ID,
      files: [
        selectedFile(
          new File(["confirmed"], "已确认.pdf", { type: "application/pdf" }),
          "queued",
          { itemId: ROOT_ITEM_ID },
        ),
        selectedFile(
          new File(["failed"], "传输失败.pdf", { type: "application/pdf" }),
          "failed",
          {
            error: new ApiError("network", "上传连接中断"),
            failureStage: "transfer",
          },
        ),
      ],
    }),
    hasDedicatedRetry: true,
  },
] satisfies Array<{
  name: string;
  state: () => KnowledgeUploadBatchState;
  hasDedicatedRetry: boolean;
}>)("blocks generic submission for $name", ({ state, hasDedicatedRetry }) => {
  initialState = state();
  renderUploadBatch();
  const form = screen.getByRole("form", { name: "知识资料批量上传" });
  const genericSubmit = form.querySelector<HTMLButtonElement>('button[type="submit"]');

  expect(genericSubmit).not.toBeNull();
  expect(genericSubmit).toBeDisabled();
  fireEvent.submit(form);
  expect(actionSpies.start).not.toHaveBeenCalled();
  if (hasDedicatedRetry) {
    expect(screen.getByRole("button", { name: "重新上传失败文件" })).toBeEnabled();
  } else {
    expect(screen.queryByRole("button", { name: "重新上传失败文件" })).toBeNull();
  }
});

test("allows explicit create-level retry only before any item is confirmed", async () => {
  initialState = {
    ...EMPTY_STATE,
    error: new ApiError("network", "无法创建上传批次，请重试"),
    files: [
      selectedFile(
        new File(["create"], "创建失败.pdf", { type: "application/pdf" }),
        "creating",
      ),
    ],
  };
  const user = userEvent.setup();
  renderUploadBatch();

  await user.click(screen.getByRole("button", { name: "重新创建上传批次" }));
  expect(actionSpies.start).toHaveBeenCalledTimes(1);
});

test("uses the same selection path for drag/drop and always clears drag state without moving focus", () => {
  renderUploadBatch();
  const input = screen.getByLabelText("上传知识资料");
  const dropRegion = screen.getByRole("group", { name: "选择知识资料" });
  const pdf = new File(["pdf"], "拖放资料.pdf", { type: "application/pdf" });
  input.focus();

  fireEvent.dragEnter(dropRegion, { dataTransfer: { files: [pdf], types: ["Files"] } });
  expect(dropRegion).toHaveAttribute("data-drag-active", "true");
  fireEvent.dragLeave(dropRegion, { dataTransfer: { files: [pdf], types: ["Files"] } });
  expect(dropRegion).not.toHaveAttribute("data-drag-active");

  fireEvent.dragEnter(dropRegion, { dataTransfer: { files: [pdf], types: ["Files"] } });
  fireEvent.drop(dropRegion, { dataTransfer: { files: [pdf], types: ["Files"] } });
  expect(screen.getByText(pdf.name)).toBeInTheDocument();
  expect(actionSpies.select).toHaveBeenLastCalledWith([pdf]);
  expect(dropRegion).not.toHaveAttribute("data-drag-active");
  expect(input).toHaveFocus();
});

test("emits picker A again after an accepted drop replaces it with B", async () => {
  const user = userEvent.setup();
  renderUploadBatch();
  const input = screen.getByLabelText("上传知识资料");
  const dropRegion = screen.getByRole("group", { name: "选择知识资料" });
  const pickerA = new File(["picker-a"], "选择器-A.pdf", { type: "application/pdf" });
  const droppedB = new File(["drop-b"], "拖放-B.pdf", { type: "application/pdf" });

  await user.upload(input, pickerA);
  fireEvent.drop(dropRegion, {
    dataTransfer: { files: [droppedB], types: ["Files"] },
  });
  await user.upload(input, pickerA);

  expect(screen.getByText(pickerA.name)).toBeInTheDocument();
  expect(screen.queryByText(droppedB.name)).toBeNull();
  expect(actionSpies.select).toHaveBeenCalledTimes(3);
  expect(actionSpies.select).toHaveBeenNthCalledWith(1, [pickerA]);
  expect(actionSpies.select).toHaveBeenNthCalledWith(2, [droppedB]);
  expect(actionSpies.select).toHaveBeenNthCalledWith(3, [pickerA]);
});

test.each([
  ["selected", "等待上传"],
  ["hashing", "正在计算校验值"],
  ["creating", "正在创建上传批次"],
  ["uploading", "正在上传"],
  ["completing", "正在确认"],
  ["awaiting_upload", "等待服务器接收上传"],
  ["queued", "已确认，等待处理"],
  ["processing", "后台处理中"],
  ["ready", "处理完成，可用于知识检索"],
  ["failed", "处理失败"],
  ["cancelled", "已取消"],
] satisfies [KnowledgeUploadFilePhase, string][])(
  "labels the %s file phase as %s",
  (phase, label) => {
    const pdf = new File(["pdf"], `${phase}.pdf`, { type: "application/pdf" });
    initialState = {
      ...EMPTY_STATE,
      pending: ["hashing", "creating", "uploading", "completing"].includes(phase),
      files: [selectedFile(pdf, phase, {
        error: phase === "failed" ? new ApiError("network", "上传连接中断") : null,
        failureStage: phase === "failed" ? "transfer" : null,
      })],
    };
    renderUploadBatch();
    expect(within(fileRow(pdf.name)).getByText(label)).toBeInTheDocument();
  },
);

test("renders determinate upload progress with an accessible value and visible percentage", () => {
  const pdf = new File(["pdf"], "进度.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    pending: true,
    files: [selectedFile(pdf, "uploading", {
      progress: { loaded: 40, total: 100, percent: 40 },
    })],
  };
  renderUploadBatch();
  const row = within(fileRow(pdf.name));
  expect(row.getByRole("progressbar", { name: `${pdf.name} 上传进度` }))
    .toHaveAttribute("value", "40");
  expect(row.getByText("40%")).toBeInTheDocument();
});

test("explains cancellation boundaries and cancels only the current browser upload", async () => {
  const pdf = new File(["pdf"], "确认中.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    pending: true,
    files: [selectedFile(pdf, "completing")],
  };
  const user = userEvent.setup();
  renderUploadBatch();

  expect(screen.getByText("取消只会停止当前浏览器中的上传，不会撤销已确认的后台处理。"))
    .toBeInTheDocument();
  expect(screen.queryByText(/索引完成/)).toBeNull();
  await user.click(screen.getByRole("button", { name: "取消当前上传" }));
  expect(actionSpies.cancel).toHaveBeenCalledTimes(1);
});

test("keeps upload and confirmation work ahead of Worker status in a mixed batch summary", () => {
  const uploading = new File(["a"], "仍在上传.pdf", { type: "application/pdf" });
  const queued = new File(["b"], "已经确认.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    pending: true,
    batchId: BATCH_ID,
    startedAt: 10,
    files: [
      selectedFile(uploading, "uploading", { itemId: "00000000-0000-4000-8000-000000009011" }),
      selectedFile(queued, "queued", { itemId: "00000000-0000-4000-8000-000000009012" }),
    ],
    batch: batchDetail([
      batchItem({ id: "00000000-0000-4000-8000-000000009012", normalizedPath: queued.name }),
    ]),
  };
  renderUploadBatch();

  expect(screen.getByText("正在上传。")).toHaveAttribute("aria-live", "polite");
  expect(screen.queryByText("已确认的文件正在后台处理。")).toBeNull();
});

test("offers retry only for failed transfer or confirmation stages", async () => {
  const worker = new File(["b"], "Worker失败.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    files: [selectedFile(worker, "failed", {
      error: new ApiError("http", "Worker 无法解析", { status: 422 }),
      failureStage: "worker",
    })],
  };
  const user = userEvent.setup();
  const workerOnly = renderUploadBatch();

  expect(screen.getByText("后台处理失败的文件不能原地重试，请修正后重新选择。"))
    .toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "重新上传失败文件" })).toBeNull();
  workerOnly.unmount();

  const confirmation = new File(["a"], "确认失败.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    files: [selectedFile(confirmation, "failed", {
      error: new ApiError("network", "确认连接中断"),
      failureStage: "complete",
    })],
  };
  renderUploadBatch();
  await user.click(screen.getByRole("button", { name: "重新上传失败文件" }));
  expect(actionSpies.retryFailed).toHaveBeenCalledTimes(1);
});

test.each(["create", "complete"] as const)(
  "does not offer a retry action for a %s contract failure",
  (stage) => {
    const contractError = new ApiError("contract", "上传响应关联无效");
    initialState = {
      ...EMPTY_STATE,
      error: stage === "create" ? contractError : null,
      files: [selectedFile(
        new File(["contract"], `${stage}-contract.pdf`, { type: "application/pdf" }),
        stage === "create" ? "creating" : "failed",
        stage === "create"
          ? {}
          : { error: contractError, failureStage: "complete" },
      )],
    };
    renderUploadBatch();

    expect(screen.queryByRole("button", { name: "重新创建上传批次" })).toBeNull();
    expect(screen.queryByRole("button", { name: "重新上传失败文件" })).toBeNull();
  },
);

test("resets the file input on clear so the same file can be selected again", async () => {
  const user = userEvent.setup();
  renderUploadBatch();
  const input = screen.getByLabelText("上传知识资料") as HTMLInputElement;
  const pdf = new File(["same"], "再次选择.pdf", { type: "application/pdf" });

  await user.upload(input, pdf);
  expect(input.files).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "清空选择" }));
  expect(input.value).toBe("");
  expect(actionSpies.clear).toHaveBeenCalledTimes(1);

  await user.upload(input, pdf);
  expect(actionSpies.select).toHaveBeenCalledTimes(2);
  expect(screen.getByText(pdf.name)).toBeInTheDocument();
});

test("returns keyboard focus to the picker on explicit clear but not on hook-driven clear", async () => {
  const user = userEvent.setup();
  renderUploadBatch();
  const input = screen.getByLabelText("上传知识资料") as HTMLInputElement;
  const pdf = new File(["focus"], "焦点恢复.pdf", { type: "application/pdf" });

  await user.upload(input, pdf);
  const clearButton = screen.getByRole("button", { name: "清空选择" });
  clearButton.focus();
  await user.keyboard("{Enter}");

  expect(screen.queryByRole("button", { name: "清空选择" })).toBeNull();
  expect(input).toHaveFocus();
  expect(input.value).toBe("");
  await user.upload(input, pdf);
  expect(screen.getByText(pdf.name)).toBeInTheDocument();

  const unrelatedControl = document.createElement("button");
  unrelatedControl.textContent = "组件外控制";
  document.body.append(unrelatedControl);
  try {
    unrelatedControl.focus();
    act(() => setFakeUploadState?.(EMPTY_STATE));

    expect(unrelatedControl).toHaveFocus();
    expect(input.value).toBe("");
  } finally {
    unrelatedControl.remove();
  }
});

test("supports manual refresh after the five-minute automatic window", async () => {
  const pdf = new File(["pdf"], "处理中.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    batchId: BATCH_ID,
    startedAt: 10,
    files: [selectedFile(pdf, "processing", { itemId: ROOT_ITEM_ID })],
    batch: batchDetail([batchItem({ id: ROOT_ITEM_ID, normalizedPath: pdf.name })]),
  };
  const user = userEvent.setup();
  renderUploadBatch();

  expect(screen.getByText("处理状态会自动刷新最多 5 分钟；之后仍可手动刷新。"))
    .toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "刷新处理状态" }));
  expect(actionSpies.refreshBatch).toHaveBeenCalledTimes(1);
});

test("shows an observable elapsed tracking state while preserving manual refresh", async () => {
  const processing = new File(["processing"], "后台处理中.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    batchId: BATCH_ID,
    batchPollingTimedOut: true,
    files: [selectedFile(processing, "processing", { itemId: ROOT_ITEM_ID })],
    batch: batchDetail([
      batchItem({ id: ROOT_ITEM_ID, normalizedPath: processing.name, status: "processing" }),
    ]),
  };
  const user = userEvent.setup();
  renderUploadBatch();

  expect(screen.getByText(/后台仍在处理/)).toBeInTheDocument();
  expect(screen.queryByText("本批次处理失败，请检查失败文件。")).toBeNull();
  await user.click(screen.getByRole("button", { name: "刷新处理状态" }));
  expect(actionSpies.refreshBatch).toHaveBeenCalledTimes(1);
});

test("offers stop tracking after transfer work settles while keeping processing truth", async () => {
  const processing = new File(["processing"], "继续处理.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    batchId: BATCH_ID,
    files: [selectedFile(processing, "processing", { itemId: ROOT_ITEM_ID })],
    batch: batchDetail([
      batchItem({ id: ROOT_ITEM_ID, normalizedPath: processing.name, status: "processing" }),
    ]),
  };
  const user = userEvent.setup();
  renderUploadBatch();

  await user.click(screen.getByRole("button", { name: "停止自动跟踪" }));

  expect(actionSpies.cancel).toHaveBeenCalledTimes(1);
  expect(within(fileRow(processing.name)).getByText("后台处理中")).toBeInTheDocument();
});

test.each([
  ["completed", 2, 0, "上一批次已完成：2 个文件就绪。"],
  ["completed_with_errors", 1, 1, "上一批次已完成：1 个就绪，1 个失败。"],
] as const)("renders a retained safe %s summary", (status, readyCount, failedCount, text) => {
  initialState = {
    ...EMPTY_STATE,
    lastFinalSummary: { status, itemCount: 2, readyCount, failedCount },
  };
  renderUploadBatch();

  expect(screen.getByText(text)).toBeInTheDocument();
  expect(screen.queryByText(BATCH_ID)).toBeNull();
});

test.each(["processing", "completed"] as const)(
  "real controller removes a recovered %s batch alert and trace after identical success",
  async (status) => {
    const actual = await vi.importActual<typeof import("../../src/hooks/useKnowledgeUploadBatch.ts")>(
      "../../src/hooks/useKnowledgeUploadBatch.ts",
    );
    const selected = new File(["real controller"], "recovered.pdf", { type: "application/pdf" });
    const detail = batchDetail([batchItem({
      id: ROOT_ITEM_ID, normalizedPath: selected.name, status: status === "completed" ? "ready" : "processing",
    })], status);
    const dependencies: KnowledgeUploadDependencies = {
      prepareFiles: prepareKnowledgeFiles,
      createBatch: async () => ({ batchId: BATCH_ID, uploads: [{
        uploadId: CHILD_1_ID, itemId: ROOT_ITEM_ID, method: "PUT",
        url: "https://objects.example.test/recovery", headers: {}, expiresAt: "2026-09-04T10:00:00Z",
      }] }),
      putObject: async () => undefined,
      complete: async ({ uploadId, batchId, itemId }) => ({
        uploadId, batchId, itemId, status: "queued", resourceId: null, resourceVersionId: null,
      }),
      now: () => 0,
    };
    vi.mocked(useKnowledgeUploadBatch).mockImplementation((props) => actual.useKnowledgeUploadBatch({
      ...props, dependencies,
    }));
    let resolveRecovery!: (response: Response) => void;
    const recovery = new Promise<Response>((resolve) => { resolveRecovery = resolve; });
    let requests = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      requests += 1;
      if (requests === 1) return Response.json(detail);
      if (requests <= 4) return Response.json({
        message: "数据库暂时不可用", code: "database_unavailable", traceId: "trace-recovered-ui",
      }, { status: 503, headers: { "X-Request-ID": "trace-recovered-ui" } });
      return recovery;
    }));
    const client = createAppQueryClient();
    client.setDefaultOptions({ queries: { ...client.getDefaultOptions().queries, retryDelay: 0 } });
    const rendered = render(<QueryClientProvider client={client}>
      <KnowledgeUploadBatch organizationId={ORGANIZATION_ID} projectId={PROJECT_ID}
        csrfToken="csrf" sessionSignal={new AbortController().signal} onAccessUnavailable={vi.fn()} />
    </QueryClientProvider>);
    try {
      fireEvent.change(screen.getByLabelText("上传知识资料"), { target: { files: [selected] } });
      fireEvent.click(screen.getByRole("button", { name: "开始上传" }));
      const phase = status === "completed" ? "处理完成，可用于知识检索" : "后台处理中";
      await waitFor(() => expect(within(fileRow(selected.name)).getByText(phase)).toBeInTheDocument());
      if (status === "processing") fireEvent.click(screen.getByRole("button", { name: "停止自动跟踪" }));
      fireEvent.click(screen.getByRole("button", { name: "刷新处理状态" }));
      expect(await screen.findByText("请求编号：trace-recovered-ui")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "刷新处理状态" }));
      await waitFor(() => expect(requests).toBe(5));
      expect(screen.getByText("请求编号：trace-recovered-ui")).toBeInTheDocument();
      expect(screen.getByRole("alert")).toHaveTextContent("数据库暂时不可用");
      resolveRecovery(Response.json(detail));
      await waitFor(() => expect(screen.queryByText("请求编号：trace-recovered-ui")).toBeNull());
      expect(screen.queryByRole("alert")).toBeNull();
      expect(within(fileRow(selected.name)).getByText(phase)).toBeInTheDocument();
    } finally {
      resolveRecovery(Response.json(detail));
      rendered.unmount();
      client.clear();
      vi.unstubAllGlobals();
    }
  },
);

test("renders operation and batch errors as text with safe trace IDs and no diagnostic secrets", () => {
  const hostileMessage = "<script data-hostile-error>上传暂时失败</script>";
  initialState = {
    ...EMPTY_STATE,
    error: new ApiError("network", hostileMessage, {
      traceId: "trace-safe-001",
      code: "internal_upload_id_001",
      context: "PUT https://objects.example.test/private-key",
      cause: { body: "raw-object-store-secret" },
    }),
    batchId: BATCH_ID,
    batchError: new ApiError("http", "无法刷新处理状态", {
      status: 503,
      traceId: "trace-safe-002",
      context: `GET /private/batches/${BATCH_ID}`,
    }),
  };
  const { container } = renderUploadBatch();

  expect(screen.getByText(hostileMessage)).toBeInTheDocument();
  expect(screen.getByText("请求编号：trace-safe-001")).toBeInTheDocument();
  expect(screen.getByText("请求编号：trace-safe-002")).toBeInTheDocument();
  expect(container.querySelector("script[data-hostile-error]")).toBeNull();
  for (const secret of [
    "https://objects.example.test/private-key",
    "internal_upload_id_001",
    "raw-object-store-secret",
    BATCH_ID,
  ]) {
    expect(container).not.toHaveTextContent(secret);
  }
});

test("keeps long hostile ZIP child paths in server order inside a nested semantic list", () => {
  const zip = new File(["zip"], "知识包😀مرحبا.zip", { type: "application/zip" });
  const childPath1 = "第一章/" + "没有空格的超长中文文件名".repeat(16) + ".md";
  const childPath2 = "<img data-hostile-path src=x>第二章😀مرحبا.md";
  const childError = "<script data-child-error>无法解析</script>";
  initialState = {
    ...EMPTY_STATE,
    batchId: BATCH_ID,
    startedAt: 10,
    files: [selectedFile(zip, "processing", { itemId: ROOT_ITEM_ID })],
    batch: batchDetail([
      batchItem({ id: ROOT_ITEM_ID, normalizedPath: zip.name }),
      batchItem({ id: CHILD_1_ID, parentItemId: ROOT_ITEM_ID, normalizedPath: childPath1, status: "ready" }),
      batchItem({
        id: CHILD_2_ID,
        parentItemId: ROOT_ITEM_ID,
        normalizedPath: childPath2,
        status: "failed",
        errorDetail: childError,
      }),
    ], "completed_with_errors"),
  };
  const { container } = renderUploadBatch();
  const rootRow = fileRow(zip.name);
  const childList = within(rootRow).getByRole("list", { name: `${zip.name} 中的文件` });
  const childRows = within(childList).getAllByRole("listitem");

  expect(childList).toHaveClass("knowledge-upload-child-list");
  expect(childRows).toHaveLength(2);
  expect(childRows[0]).toHaveClass("knowledge-upload-child");
  expect(childRows[0]).toHaveTextContent(childPath1);
  expect(childRows[1]).toHaveTextContent(childPath2);
  expect(childRows[1]).toHaveTextContent(childError);
  expect(container.querySelector("img[data-hostile-path], script[data-child-error]")).toBeNull();
  for (const internalId of [BATCH_ID, ROOT_ITEM_ID, CHILD_1_ID, CHILD_2_ID]) {
    expect(container).not.toHaveTextContent(internalId);
  }
});

test("uses one polite phase summary and reserves alerts for actionable failures", () => {
  const pdf = new File(["pdf"], "已取消.pdf", { type: "application/pdf" });
  initialState = {
    ...EMPTY_STATE,
    files: [selectedFile(pdf, "cancelled")],
  };
  const { container } = renderUploadBatch();

  expect(container.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
  expect(screen.getByText("当前浏览器中的上传已取消。已确认的服务器工作可能继续。"))
    .toHaveAttribute("aria-live", "polite");
  expect(screen.queryByRole("alert")).toBeNull();
});
