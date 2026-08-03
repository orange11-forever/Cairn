import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiErrorResponseSchema,
  AskResponseSchema,
  DocumentsResponseSchema,
  LoginResponseSchema,
  UploadResponseSchema,
} from "@cairn/contracts";
import {
  DEMO_ACCOUNT,
  DOCUMENTS,
  createApiErrorBody,
  createGroundedAnswer,
  createUploadResponse,
} from "../../mocks/fixtures.mjs";

test("mock fixtures satisfy the shared response contracts", () => {
  assert.equal(LoginResponseSchema.safeParse({ user: DEMO_ACCOUNT.user }).success, true);
  assert.equal(DocumentsResponseSchema.safeParse(DOCUMENTS).success, true);
  assert.equal(
    AskResponseSchema.safeParse(
      createGroundedAnswer({
        id: "00000000-0000-4000-8000-000000002001",
        createdAt: "2026-08-03T08:00:00Z",
      }),
    ).success,
    true,
  );
  assert.equal(
    UploadResponseSchema.safeParse(
      createUploadResponse(
        [{ name: "runbook.pdf", size: 1024 }],
        () => "00000000-0000-4000-8000-000000003001",
      ),
    ).success,
    true,
  );
  assert.equal(
    ApiErrorResponseSchema.safeParse(
      createApiErrorBody("internal_error", "服务器内部错误", "req-123"),
    ).success,
    true,
  );
});
