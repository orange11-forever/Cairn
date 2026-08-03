export const IDS = Object.freeze({
  user: "00000000-0000-4000-8000-000000001001",
  document1: "00000000-0000-4000-8000-000000000001",
  document2: "00000000-0000-4000-8000-000000000002",
  document3: "00000000-0000-4000-8000-000000000003",
  document4: "00000000-0000-4000-8000-000000000004",
});

export const DOCUMENTS = Object.freeze([
  { id: IDS.document1, title: "产品需求文档", status: "completed" },
  { id: IDS.document2, title: "API 接口设计", status: "processing" },
  { id: IDS.document3, title: "测试报告 v2", status: "completed" },
  { id: IDS.document4, title: "部署手册", status: "failed" },
]);

export const DEMO_ACCOUNT = Object.freeze({
  email: "demo@cairn.dev",
  password: "cairn-demo-2026",
  user: {
    id: IDS.user,
    email: "demo@cairn.dev",
    displayName: "演示用户",
    role: "member",
  },
});

export function createGroundedAnswer({ id, createdAt }) {
  return {
    kind: "grounded_answer",
    id,
    content: "严重故障需要先通知当班负责人，再按照升级矩阵联系服务负责人。",
    createdAt,
    citations: [
      {
        documentId: IDS.document1,
        documentTitle: "值班流程",
        snippet: "P0 故障 5 分钟内通知当班负责人，15 分钟内拉起服务负责人。",
        anchor: "section-4",
        score: 0.92,
      },
    ],
  };
}

export function createUploadResponse(files, idFactory) {
  return {
    accepted: files.length,
    jobs: files.map((file) => ({
      id: idFactory(),
      documentTitle: file.name,
      status: "pending",
    })),
  };
}

export function createApiErrorBody(code, message, traceId) {
  return { message, code, traceId };
}
