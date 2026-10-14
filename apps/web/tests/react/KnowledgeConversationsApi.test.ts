import { afterEach, expect, test, vi } from "vitest";
import { appendKnowledgeConversationTurn, createKnowledgeConversation, fetchKnowledgeConversation } from "../../src/api/knowledgeConversations.ts";

const id = "00000000-0000-4000-8000-000000000001";
const turnId = "00000000-0000-4000-8000-000000000002";
const detail = { id, title: "新对话", revision: 1, createdAt: "2026-10-12T12:00:00Z", updatedAt: "2026-10-12T12:00:00Z", turns: [] };
const signal = () => new AbortController().signal;
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test.each([200, 201])("create accepts the generated complete response on status %s", async status => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(detail, { status })));
  expect(await createKnowledgeConversation({ projectId: id, id, csrfToken: "csrf", signal: signal() })).toEqual(detail);
});

test.each([
  { ...detail, id: turnId },
  { ...detail, revision: 2 },
  { ...detail, extra: "private" },
])("read rejects wrong identity and inconsistent revision/body", async value => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(value)));
  await expect(fetchKnowledgeConversation({ projectId: id, conversationId: id, signal: signal() })).rejects.toMatchObject({ kind: "contract" });
});

test("append requires the submitted turn and validates its question and complete sequence", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(detail)));
  await expect(appendKnowledgeConversationTurn({ projectId: id, conversationId: id, id: turnId, expectedRevision: 1, question: "测试问题", csrfToken: "csrf", signal: signal() })).rejects.toMatchObject({ kind: "contract" });
});

test("a late 401 becomes aborted before it can expire the new session", async () => {
  const controller = new AbortController();
  vi.stubGlobal("fetch", vi.fn(async () => { controller.abort(); return Response.json({ code: "session_invalid", message: "会话无效", traceId: "late" }, { status: 401 }); }));
  await expect(fetchKnowledgeConversation({ projectId: id, conversationId: id, signal: controller.signal })).rejects.toMatchObject({ kind: "aborted", status: null });
});

test("current 401 remains the session-invalid HTTP error for the session boundary", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ code: "session_invalid", message: "会话无效", traceId: "current" }, { status: 401 })));
  await expect(fetchKnowledgeConversation({ projectId: id, conversationId: id, signal: signal() })).rejects.toMatchObject({ kind: "http", status: 401, code: "session_invalid" });
});

test.each([
  { id: turnId, sequence: 2, question: "测试问题", answer: null, answerUnavailable: true, contextTruncated: false, createdAt: detail.createdAt },
  { id: turnId, sequence: 1, question: "测试问题", answer: null, answerUnavailable: false, contextTruncated: false, createdAt: detail.createdAt },
])("rejects sequence and redaction inconsistency even when generated fields match", async turn => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ...detail, revision: 2, turns: [turn] })));
  await expect(fetchKnowledgeConversation({ projectId: id, conversationId: id, signal: signal() })).rejects.toMatchObject({ kind: "contract" });
});
