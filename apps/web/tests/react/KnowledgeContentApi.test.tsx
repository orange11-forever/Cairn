import { afterEach, expect, test, vi } from "vitest";
import { fetchKnowledgeContent } from "../../src/api/knowledgeContent.ts";

const resourceId = "00000000-0000-4000-8000-000000005001";
const resourceVersionId = "00000000-0000-4000-8000-000000006001";
const chunkId = "00000000-0000-4000-8000-000000007001";
const body = { resourceId, resourceVersionId, title: "Manual", mediaType: "text/plain",
  format: "text", content: "start\nhit\nEOF", lineCount: 3,
  highlight: { chunkId, lineStart: 2, lineEnd: 2, text: "hit", matchType: "exact" } };
const request = { projectId: "00000000-0000-4000-8000-000000004001", resourceId,
  resourceVersionId, chunkId, signal: new AbortController().signal };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("reads complete content through the generated GET with pinned citation query", async () => {
  let url: URL | undefined;
  vi.stubGlobal("fetch", async (input: Request) => { url = new URL(input.url); return Response.json(body); });
  await expect(fetchKnowledgeContent(request)).resolves.toEqual(body);
  expect(url?.searchParams.get("version_id")).toBe(resourceVersionId);
  expect(url?.searchParams.get("chunk_id")).toBe(chunkId);
});

test.each([
  { ...body, resourceId: resourceVersionId }, { ...body, resourceVersionId: resourceId },
  { ...body, lineCount: 2 }, { ...body, highlight: null },
  { ...body, highlight: { ...body.highlight, chunkId: resourceId } },
  { ...body, highlight: { ...body.highlight, lineEnd: 5 } },
  { ...body, highlight: { ...body.highlight, text: "forged" } },
  { ...body, format: "markdown" }, { ...body, title: undefined },
])("rejects malformed or incoherent authorized content %#", async (invalid) => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", async () => Response.json(invalid));
  await expect(fetchKnowledgeContent(request)).rejects.toMatchObject({ kind: "contract" });
});

test("discards even schema-valid late content after cancellation", async () => {
  const controller = new AbortController();
  vi.stubGlobal("fetch", async () => { controller.abort(); return Response.json(body); });
  await expect(fetchKnowledgeContent({ ...request, signal: controller.signal }))
    .rejects.toMatchObject({ kind: "aborted" });
});

test("rejects unexpected successful status and preserves safe traced errors", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", async () => Response.json(body, { status: 201 }));
  await expect(fetchKnowledgeContent(request)).rejects.toMatchObject({ kind: "contract" });
  vi.stubGlobal("fetch", async () => Response.json({ code: "knowledge_changed", message: "已变化", traceId: "trace-content" }, { status: 409 }));
  await expect(fetchKnowledgeContent(request)).rejects.toMatchObject({ status: 409, code: "knowledge_changed", traceId: "trace-content" });
});
