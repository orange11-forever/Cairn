import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { KnowledgeDocument } from "../../src/components/knowledge/KnowledgeDocument.tsx";
import { knowledgeKeys } from "../../src/queries/knowledge.ts";

const resourceId = "00000000-0000-4000-8000-000000005001";
const resourceVersionId = "00000000-0000-4000-8000-000000006001";
const chunkId = "00000000-0000-4000-8000-000000007001";
const projectId = "00000000-0000-4000-8000-000000004001";
const organizationId = "00000000-0000-4000-8000-000000003001";
const content = { resourceId, resourceVersionId, title: "Manual", mediaType: "text/plain",
  format: "text", content: "first\nhit\nEOF", lineCount: 3, highlight: null };
const originalScrollIntoView = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
function mount(fetchImpl: typeof fetch, citation = false) {
  vi.stubGlobal("fetch", fetchImpl);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const session = new AbortController();
  const missing = vi.fn();
  const props = { id: "reader", title: "Manual", organizationId, projectId, resourceId,
    csrfToken: "synthetic", canWrite: true, sessionSignal: session.signal,
    onResourceMissing: missing, onRetrySucceeded: vi.fn(), onDeleteSucceeded: vi.fn(),
    ...(citation ? { citation: { resourceId, resourceVersionId, chunkId, title: "Manual" } } : {}) };
  const view = render(<QueryClientProvider client={client}><KnowledgeDocument {...props} /></QueryClientProvider>);
  return { ...view, client, session, missing, props };
}
afterEach(() => {
  vi.unstubAllGlobals(); vi.restoreAllMocks();
  if (originalScrollIntoView) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScrollIntoView);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

test("reads true EOF and exposes metadata only from its explicit control", async () => {
  let detailsRequests = 0;
  mount(async (input) => {
    const request = input as Request;
    if (request.url.endsWith("/content")) return Response.json(content);
    detailsRequests += 1;
    return Response.json({ id: resourceId, title: "Manual", sourceType: "upload", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z", latestVersion: null });
  });
  expect(await screen.findByText("EOF", { exact: false }, { timeout: 5000 })).toBeVisible();
  expect(screen.getByText("已到文档末尾 · 正文完整")).toBeVisible();
  expect(detailsRequests).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: "资料详情" }));
  expect(await screen.findByRole("region", { name: "Manual 资料详情" })).toBeVisible();
  expect(screen.getByRole("button", { name: "删除资料" })).toBeVisible();
});

test("offline hides and removes the complete body, reconnect requires explicit reading", async () => {
  let connected = true;
  vi.spyOn(navigator, "onLine", "get").mockImplementation(() => connected);
  let count = 0;
  const view = mount(async () => { count += 1; return Response.json(content); });
  expect(await screen.findByText("EOF", { exact: false })).toBeVisible();
  act(() => { connected = false; window.dispatchEvent(new Event("offline")); });
  expect(screen.queryByText("EOF", { exact: false })).toBeNull();
  await waitFor(() => expect(view.client.getQueryData(knowledgeKeys.content(organizationId, projectId, resourceId))).toBeUndefined());
  act(() => { connected = true; window.dispatchEvent(new Event("online")); });
  expect(screen.queryByText("EOF", { exact: false })).toBeNull();
  expect(count).toBe(1);
  await userEvent.click(screen.getByRole("button", { name: "重新读取正文" }));
  expect(await screen.findByText("EOF", { exact: false })).toBeVisible();
  expect(count).toBe(2);
});

test("unmount cancels pending body and prevents a late response from repopulating cache", async () => {
  let resolve!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  const view = mount(async (input) => {
    signal = (input as Request).signal;
    return new Promise<Response>(done => { resolve = done; });
  });
  await waitFor(() => expect(signal).toBeDefined());
  view.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolve(Response.json(content)); });
  expect(view.client.getQueryData(knowledgeKeys.content(organizationId, projectId, resourceId))).toBeUndefined();
});

test("session cancellation immediately removes authorized body", async () => {
  const view = mount(async () => Response.json(content));
  expect(await screen.findByText("EOF", { exact: false })).toBeVisible();
  act(() => view.session.abort());
  await waitFor(() => expect(screen.queryByText("EOF", { exact: false })).toBeNull());
  expect(view.client.getQueryData(knowledgeKeys.content(organizationId, projectId, resourceId))).toBeUndefined();
});

test("range citations honestly display the excerpt and return focus to the trusted block", async () => {
  mount(async () => Response.json({ ...content,
    highlight: { chunkId, lineStart: 1, lineEnd: 3, text: "ambiguous indexed excerpt", matchType: "range" } }), true);
  expect(await screen.findByText("ambiguous indexed excerpt")).toBeVisible();
  expect(screen.getByText(/引用所在区块/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "回到引用" }));
  expect(document.activeElement).toHaveAttribute("data-citation-hit", "true");
});

test.each([401, 404, 409, 503])("reauthorization failure%d removes old body and refreshes access", async (status) => {
  let failed = false;
  const view = mount(async () => failed ? Response.json({ message: "资料不可用", code: "unavailable", traceId: "trace" }, { status }) : Response.json(content));
  expect(await screen.findByText("EOF", { exact: false })).toBeVisible();
  failed = true;
  await userEvent.click(screen.getByRole("button", { name: "重新读取正文" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("资料不可用");
  expect(screen.queryByText("EOF", { exact: false })).toBeNull();
  expect(view.missing).toHaveBeenCalledTimes(status === 503 ? 0 : 1);
  expect(view.client.getQueryData(knowledgeKeys.content(organizationId, projectId, resourceId))).toBeUndefined();
});

test.each([
  { name: "late list item", tag: "LI", line: 500,
    markdown: Array.from({ length: 500 }, (_, index) => `- item ${index + 1}`).join("\n"),
    text: "item 500", ancestor: "ul", earlier: "li" },
  { name: "late table row", tag: "TR", line: 302,
    markdown: ["| Item | Status |", "| --- | --- |", ...Array.from({ length: 300 }, (_, index) => `| row ${index + 1} | ready |`)].join("\n"),
    text: "row 300", ancestor: "table", earlier: "tbody tr" },
])("focuses and returns to the actual $name without highlighting uncited ancestors", async (fixture) => {
  const scrolled: HTMLElement[] = [];
  const scroll = vi.fn(function (this: HTMLElement, _options?: ScrollIntoViewOptions) {
    scrolled.push(this);
  });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
  const view = mount(async () => Response.json({ ...content, mediaType: "text/markdown", format: "markdown",
    content: fixture.markdown, lineCount: fixture.line,
    highlight: { chunkId, lineStart: fixture.line, lineEnd: fixture.line, text: fixture.text, matchType: "exact" } }), true);
  await screen.findByText(fixture.text, {}, { timeout: 5000 });
  await waitFor(() => expect(document.activeElement).toHaveAttribute("data-citation-hit", "true"));
  expect(document.activeElement?.tagName).toBe(fixture.tag);
  expect(document.activeElement).toHaveAttribute("data-line-start", String(fixture.line));
  expect(document.activeElement).toHaveTextContent(fixture.text);
  expect(view.container.querySelector(fixture.ancestor)).not.toHaveAttribute("data-citation-hit");
  expect(view.container.querySelector(fixture.earlier)).not.toHaveAttribute("data-citation-hit");
  expect(scrolled[0]).toBe(document.activeElement);
  expect(scroll).toHaveBeenCalledWith({ block: "center", behavior: "instant" });
  await userEvent.click(screen.getByRole("button", { name: "回到引用" }));
  expect(document.activeElement?.tagName).toBe(fixture.tag);
  expect(document.activeElement).toHaveAttribute("data-line-start", String(fixture.line));
  expect(scrolled.at(-1)).toBe(document.activeElement);
});

test("citation scrolling adjusts only the owning reader and keeps the referenced line inside its viewport", async () => {
  const markdown = Array.from({ length: 500 }, (_, index) => `- item ${index + 1}`).join("\n");
  const calls: ScrollToOptions[] = [];
  const scroller = document.createElement("div");
  scroller.className = "knowledge-reader-scroll";
  Object.defineProperty(scroller, "clientHeight", { value: 400 });
  scroller.getBoundingClientRect = () => ({ top: 100, bottom: 500, height: 400 } as DOMRect);
  Object.defineProperty(scroller, "scrollTo", { value: (options: ScrollToOptions) => {
    calls.push(options); scroller.scrollTop = options.top ?? 0;
  } });
  const originalBounds = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.tagName === "LI" && this.dataset.lineStart === "500") {
      const top = 100 + 10000 - scroller.scrollTop;
      return { top, bottom: top + 24, height: 24 } as DOMRect;
    }
    return originalBounds.call(this);
  });
  const view = mount(async () => Response.json({ ...content, mediaType: "text/markdown", format: "markdown",
    content: markdown, lineCount: 500,
    highlight: { chunkId, lineStart: 500, lineEnd: 500, text: "item 500", matchType: "exact" } }), true);
  view.container.parentElement?.appendChild(scroller);
  scroller.appendChild(view.container);
  await screen.findByText("item 500", {}, { timeout: 5000 });
  await waitFor(() => expect(document.activeElement).toHaveAttribute("data-line-start", "500"));
  expect(calls[0]).toEqual({ top: 9812, behavior: "instant" });
  const bounds = document.activeElement!.getBoundingClientRect();
  expect(bounds.top).toBeGreaterThanOrEqual(100);
  expect(bounds.bottom).toBeLessThanOrEqual(500);
  expect(window.scrollY).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: "回到引用" }));
  expect(calls.at(-1)).toEqual({ top: 9812, behavior: "instant" });
});
