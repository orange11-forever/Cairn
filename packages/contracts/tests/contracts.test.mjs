import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiErrorResponseSchema,
  AskRequestSchema,
  AskResponseSchema,
  DocumentsResponseSchema,
  LoginRequestSchema,
  LoginResponseSchema,
  UploadRequestSchema,
  UploadResponseSchema,
} from "../src/index.ts";

const USER_ID = "00000000-0000-4000-8000-000000001001";
const DOCUMENT_ID = "00000000-0000-4000-8000-000000000001";

test("auth contracts require a valid email, password, UUID, and role", () => {
  assert.deepEqual(LoginRequestSchema.parse({ email: "dev@cairn.dev", password: " secret " }), {
    email: "dev@cairn.dev",
    password: " secret ",
  });
  assert.equal(LoginRequestSchema.safeParse({ email: "invalid", password: "x" }).success, false);
  assert.equal(
    LoginResponseSchema.safeParse({
      user: { id: USER_ID, email: "dev@cairn.dev", role: "member" },
    }).success,
    true,
  );
  assert.equal(
    LoginResponseSchema.safeParse({
      user: { id: USER_ID, email: "dev@cairn.dev", role: "superuser" },
    }).success,
    false,
  );
});

test("document contracts are strict while list shape stays explicit", () => {
  assert.deepEqual(
    DocumentsResponseSchema.parse([
      { id: DOCUMENT_ID, title: "  设计评审.pdf  ", status: "completed" },
    ]),
    [{ id: DOCUMENT_ID, title: "设计评审.pdf", status: "completed" }],
  );
  assert.equal(
    DocumentsResponseSchema.safeParse([
      { id: DOCUMENT_ID, title: "文档", status: "unknown" },
    ]).success,
    false,
  );
});

test("ask contracts distinguish grounded answers from not-found answers", () => {
  assert.deepEqual(AskRequestSchema.parse({ question: "  如何升级故障？  " }), {
    question: "如何升级故障？",
  });
  assert.equal(
    AskResponseSchema.safeParse({
      kind: "grounded_answer",
      id: USER_ID,
      content: "通知负责人。",
      createdAt: "2026-08-03T08:00:00Z",
      citations: [],
    }).success,
    false,
  );
  assert.equal(
    AskResponseSchema.safeParse({
      kind: "not_found",
      id: USER_ID,
      createdAt: "2026-08-03T08:00:00Z",
    }).success,
    true,
  );
});

test("upload and error responses preserve their transport semantics", () => {
  assert.equal(
    UploadRequestSchema.safeParse({ files: [{ name: "runbook.pdf", size: 1024 }] }).success,
    true,
  );
  assert.equal(UploadRequestSchema.safeParse({ files: [] }).success, false);
  assert.equal(
    UploadResponseSchema.safeParse({
      accepted: 1,
      jobs: [{ id: USER_ID, documentTitle: "runbook.pdf", status: "pending" }],
    }).success,
    true,
  );
  assert.deepEqual(
    ApiErrorResponseSchema.parse({
      message: "请求失败",
      code: "internal_error",
      traceId: "req-123",
      gateway: "edge-1",
    }),
    { message: "请求失败", code: "internal_error", traceId: "req-123", gateway: "edge-1" },
  );
});
