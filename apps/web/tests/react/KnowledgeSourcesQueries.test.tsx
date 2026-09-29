import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";

import type { KnowledgeSourceSync } from "../../src/api/knowledgeSources.ts";
import { shouldPollFeishuSync, useFeishuSync, usePrivatePageActive } from "../../src/queries/knowledgeSources.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const SOURCE_ID = "00000000-0000-4000-8000-000000011001";
const SYNC_ID = "00000000-0000-4000-8000-000000012001";
const running = {
  id: SYNC_ID, projectId: PROJECT_ID, sourceId: SOURCE_ID,
  status: "running", resourceStatus: null, attempt: 1, trigger: "manual",
  createdAt: "2026-09-29T00:00:00Z", completedAt: null,
  errorCode: null, failureCode: null, nextAttemptAt: null,
  resourceId: null, resourceVersionId: null,
} satisfies KnowledgeSourceSync;
const wrapper = (client: QueryClient) => ({ children }: { children: ReactNode }) =>
  <QueryClientProvider client={client}>{children}</QueryClientProvider>;
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

afterEach(() => {
  vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
});

test("only active sync or pending indexing polls within five minutes", () => {
  expect(shouldPollFeishuSync(running, 0, 0)).toBe(true);
  expect(shouldPollFeishuSync({ ...running, status: "queued" }, 0, 2_000)).toBe(true);
  expect(shouldPollFeishuSync({ ...running, status: "completed", resourceStatus: "processing" }, 0, 2_000)).toBe(true);
  expect(shouldPollFeishuSync({ ...running, status: "completed", resourceStatus: "ready" }, 0, 2_000)).toBe(false);
  expect(shouldPollFeishuSync({ ...running, status: "failed" }, 0, 2_000)).toBe(false);
  expect(shouldPollFeishuSync(running, 0, 300_000)).toBe(false);
});

test("real sync query fetches every two seconds, stops at the deadline and permits manual refresh", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  let now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  const fetcher = vi.fn(async () => Response.json(running));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const session = new AbortController();
  const rendered = renderHook(() => useFeishuSync("org", PROJECT_ID, SOURCE_ID, SYNC_ID,
    session.signal, true), { wrapper: wrapper(client) });
  await act(flush);
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => { now = 2_000; await vi.advanceTimersByTimeAsync(2_000); await flush(); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => { now = 300_000; await vi.advanceTimersByTimeAsync(298_000); await flush(); });
  const atDeadline = fetcher.mock.calls.length;
  await act(async () => { now = 302_000; await vi.advanceTimersByTimeAsync(2_000); await flush(); });
  expect(fetcher).toHaveBeenCalledTimes(atDeadline);
  await act(async () => { await rendered.result.current.refresh(); await flush(); });
  expect(fetcher).toHaveBeenCalledTimes(atDeadline + 1);
  rendered.unmount(); client.clear();
});

test("visibility, offline and session abort hide private page activity", async () => {
  Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  const session = new AbortController();
  const result = renderHook(() => usePrivatePageActive(session.signal));
  expect(result.result.current).toBe(true);
  act(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange")); });
  expect(result.result.current).toBe(false);
  act(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    window.dispatchEvent(new Event("offline")); });
  expect(result.result.current).toBe(false);
  act(() => { Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
    window.dispatchEvent(new Event("online")); });
  expect(result.result.current).toBe(true);
  act(() => session.abort());
  expect(result.result.current).toBe(false);
});
