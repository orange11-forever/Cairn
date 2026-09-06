import { afterEach, expect, test, vi } from "vitest";

import {
  completeKnowledgeUpload,
  createKnowledgeUploadBatch,
  fetchKnowledgeBatch,
  putKnowledgeObject,
} from "../../src/api/knowledgeUploads.ts";

const PROJECT_ID = "00000000-0000-4000-8000-000000004001";
const BATCH_ID = "00000000-0000-4000-8000-000000008001";
const OTHER_BATCH_ID = "00000000-0000-4000-8000-000000008099";
const UPLOAD_ID_1 = "00000000-0000-4000-8000-000000009001";
const UPLOAD_ID_2 = "00000000-0000-4000-8000-000000009002";
const ITEM_ID_1 = "00000000-0000-4000-8000-000000010001";
const ITEM_ID_2 = "00000000-0000-4000-8000-000000010002";

const intents = [
  {
    fileName: "design.pdf",
    mediaType: "application/pdf",
    sizeBytes: 12,
    sha256: "a".repeat(64),
  },
  {
    fileName: "notes.md",
    mediaType: "text/markdown",
    sizeBytes: 34,
    sha256: "b".repeat(64),
  },
] as const;

const validCreateResponse = {
  batchId: BATCH_ID,
  uploads: [
    {
      uploadId: UPLOAD_ID_1,
      itemId: ITEM_ID_1,
      method: "PUT",
      url: "https://objects.invalid/upload-one?signature=private-one",
      headers: { "x-upload-token": "private-header-one" },
      expiresAt: "2026-09-03T10:00:00Z",
    },
    {
      uploadId: UPLOAD_ID_2,
      itemId: ITEM_ID_2,
      method: "PUT",
      url: "https://objects.invalid/upload-two?signature=private-two",
      headers: { "x-upload-token": "private-header-two" },
      expiresAt: "2026-09-03T10:00:00Z",
    },
  ],
} as const;

const validCompleteResponse = {
  uploadId: UPLOAD_ID_1,
  batchId: BATCH_ID,
  itemId: ITEM_ID_1,
  resourceId: null,
  resourceVersionId: null,
  status: "queued",
} as const;

const validBatchResponse = {
  id: BATCH_ID,
  status: "processing",
  itemCount: 1,
  readyCount: 0,
  failedCount: 0,
  createdAt: "2026-09-03T09:00:00Z",
  completedAt: null,
  items: [{
    id: ITEM_ID_1,
    parentItemId: null,
    normalizedPath: "design.pdf",
    mediaType: "application/pdf",
    sizeBytes: 12,
    status: "processing",
    resourceId: null,
    resourceVersionId: null,
    errorCode: null,
    errorDetail: null,
    createdAt: "2026-09-03T09:00:00Z",
    completedAt: null,
  }],
} as const;

const objectInstruction = {
  uploadId: UPLOAD_ID_1,
  itemId: ITEM_ID_1,
  method: "PUT",
  url: "https://objects.invalid/upload?signature=private-query",
  headers: {
    "Content-Type": "application/pdf",
    "x-upload-token": "private-header",
  },
  expiresAt: "2026-09-03T10:00:00Z",
} as const;

type XhrEventHandler = ((event: ProgressEvent) => void) | null;

function fakeXhr() {
  return {
    status: 0,
    responseText: "",
    withCredentials: true,
    upload: { onprogress: null as XhrEventHandler },
    onload: null as XhrEventHandler,
    onerror: null as XhrEventHandler,
    onabort: null as XhrEventHandler,
    open: vi.fn(),
    setRequestHeader: vi.fn(),
    send: vi.fn(),
    abort: vi.fn(),
  };
}

function asXmlHttpRequest(xhr: ReturnType<typeof fakeXhr>): XMLHttpRequest {
  return xhr as unknown as XMLHttpRequest;
}

function fire(handler: XhrEventHandler): void {
  handler?.(new ProgressEvent("xhr"));
}

function captureRequests(responseBody: unknown, init?: ResponseInit): Request[] {
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requests.push(input as Request);
    return Response.json(responseBody, init);
  }));
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("creates an upload batch with the exact Identity request and preserves response order", async () => {
  const requests = captureRequests(validCreateResponse, { status: 201 });
  const signal = new AbortController().signal;

  await expect(createKnowledgeUploadBatch({
    projectId: PROJECT_ID,
    csrfToken: "csrf-create",
    intents,
    signal,
  })).resolves.toEqual(validCreateResponse);

  expect(requests).toHaveLength(1);
  const request = requests[0]!;
  expect(request.method).toBe("POST");
  expect(request.credentials).toBe("include");
  expect(request.headers.get("X-CSRF-Token")).toBe("csrf-create");
  await expect(request.json()).resolves.toEqual({ files: intents });
  expect(new URL(request.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/uploads`,
  );
});

test("completes the correlated upload with an empty POST body and session CSRF", async () => {
  const requests = captureRequests(validCompleteResponse);

  await expect(completeKnowledgeUpload({
    projectId: PROJECT_ID,
    uploadId: UPLOAD_ID_1,
    batchId: BATCH_ID,
    itemId: ITEM_ID_1,
    csrfToken: "csrf-complete",
    signal: new AbortController().signal,
  })).resolves.toEqual(validCompleteResponse);

  expect(requests).toHaveLength(1);
  const request = requests[0]!;
  expect(request.method).toBe("POST");
  expect(request.credentials).toBe("include");
  expect(request.headers.get("X-CSRF-Token")).toBe("csrf-complete");
  expect(await request.text()).toBe("");
  expect(new URL(request.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/uploads/${UPLOAD_ID_1}/complete`,
  );
});

test("fetches only the requested schema-valid knowledge batch", async () => {
  const requests = captureRequests(validBatchResponse);

  await expect(fetchKnowledgeBatch({
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    signal: new AbortController().signal,
  })).resolves.toEqual(validBatchResponse);

  expect(requests).toHaveLength(1);
  const request = requests[0]!;
  expect(request.method).toBe("GET");
  expect(request.credentials).toBe("include");
  expect(new URL(request.url).pathname).toBe(
    `/api/v1/projects/${PROJECT_ID}/knowledge/batches/${BATCH_ID}`,
  );
});

test.each([
  ["create", 202, validCreateResponse, () => createKnowledgeUploadBatch({
    projectId: PROJECT_ID,
    csrfToken: "csrf-create",
    intents,
    signal: new AbortController().signal,
  }), "POST /api/v1/projects/{project_id}/knowledge/uploads"],
  ["complete", 201, validCompleteResponse, () => completeKnowledgeUpload({
    projectId: PROJECT_ID,
    uploadId: UPLOAD_ID_1,
    batchId: BATCH_ID,
    itemId: ITEM_ID_1,
    csrfToken: "csrf-complete",
    signal: new AbortController().signal,
  }), "POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete"],
  ["batch", 202, validBatchResponse, () => fetchKnowledgeBatch({
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    signal: new AbortController().signal,
  }), "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}"],
])("rejects schema-valid %s response with wrong success status %s", async (
  _name,
  status,
  body,
  invoke,
  context,
) => {
  captureRequests(body, { status });
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(invoke()).rejects.toMatchObject({
    kind: "contract",
    context,
    retryable: false,
  });
});

test.each([
  ["create", 201, "POST /api/v1/projects/{project_id}/knowledge/uploads", () =>
    createKnowledgeUploadBatch({
      projectId: PROJECT_ID,
      csrfToken: "csrf-create",
      intents,
      signal: new AbortController().signal,
    })],
  ["complete", 200,
    "POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete", () =>
      completeKnowledgeUpload({
        projectId: PROJECT_ID,
        uploadId: UPLOAD_ID_1,
        batchId: BATCH_ID,
        itemId: ITEM_ID_1,
        csrfToken: "csrf-complete",
        signal: new AbortController().signal,
      })],
  ["batch", 200, "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}", () =>
    fetchKnowledgeBatch({
      projectId: PROJECT_ID,
      batchId: BATCH_ID,
      signal: new AbortController().signal,
    })],
])("classifies invalid JSON on declared %s success as a contract error", async (
  _name,
  status,
  context,
  invoke,
) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{invalid", {
    status,
    headers: { "Content-Type": "application/json" },
  })));
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(invoke()).rejects.toMatchObject({
    kind: "contract",
    context,
    retryable: false,
  });
});

test.each([
  ["create", 201, "POST /api/v1/projects/{project_id}/knowledge/uploads", () =>
    createKnowledgeUploadBatch({
      projectId: PROJECT_ID,
      csrfToken: "csrf-create",
      intents,
      signal: new AbortController().signal,
    })],
  ["complete", 200,
    "POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete", () =>
      completeKnowledgeUpload({
        projectId: PROJECT_ID,
        uploadId: UPLOAD_ID_1,
        batchId: BATCH_ID,
        itemId: ITEM_ID_1,
        csrfToken: "csrf-complete",
        signal: new AbortController().signal,
      })],
  ["batch", 200, "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}", () =>
    fetchKnowledgeBatch({
      projectId: PROJECT_ID,
      batchId: BATCH_ID,
      signal: new AbortController().signal,
    })],
])("classifies an empty declared %s success as a contract error", async (
  _name,
  status,
  context,
  invoke,
) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status })));
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(invoke()).rejects.toMatchObject({
    kind: "contract",
    context,
    retryable: false,
  });
});

test.each([
  ["schema", { batchId: BATCH_ID }],
  ["count", { ...validCreateResponse, uploads: validCreateResponse.uploads.slice(0, 1) }],
  ["duplicate upload ID", {
    ...validCreateResponse,
    uploads: [
      validCreateResponse.uploads[0],
      { ...validCreateResponse.uploads[1], uploadId: UPLOAD_ID_1 },
    ],
  }],
  ["duplicate item ID", {
    ...validCreateResponse,
    uploads: [
      validCreateResponse.uploads[0],
      { ...validCreateResponse.uploads[1], itemId: ITEM_ID_1 },
    ],
  }],
  ["method", {
    ...validCreateResponse,
    uploads: [validCreateResponse.uploads[0], { ...validCreateResponse.uploads[1], method: "POST" }],
  }],
])("rejects upload-batch %s contract mismatch without logging upload secrets", async (_name, body) => {
  captureRequests(body, { status: 201 });
  const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(createKnowledgeUploadBatch({
    projectId: PROJECT_ID,
    csrfToken: "csrf-create",
    intents,
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "contract",
    context: "POST /api/v1/projects/{project_id}/knowledge/uploads",
    retryable: false,
  });

  const logged = errorLog.mock.calls.flat().join(" ");
  expect(logged).not.toContain("signature=private");
  expect(logged).not.toContain("private-header");
});

test.each([
  ["schema", { uploadId: UPLOAD_ID_1 }],
  ["upload ID", { ...validCompleteResponse, uploadId: UPLOAD_ID_2 }],
  ["batch ID", { ...validCompleteResponse, batchId: OTHER_BATCH_ID }],
  ["item ID", { ...validCompleteResponse, itemId: ITEM_ID_2 }],
])("rejects upload-completion %s contract mismatch", async (_name, body) => {
  captureRequests(body);
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(completeKnowledgeUpload({
    projectId: PROJECT_ID,
    uploadId: UPLOAD_ID_1,
    batchId: BATCH_ID,
    itemId: ITEM_ID_1,
    csrfToken: "csrf-complete",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "contract",
    context:
      "POST /api/v1/projects/{project_id}/knowledge/uploads/{upload_id}/complete",
  });
});

test.each([
  ["schema", { id: BATCH_ID }],
  ["batch ID", { ...validBatchResponse, id: OTHER_BATCH_ID }],
])("rejects knowledge-batch %s contract mismatch", async (_name, body) => {
  captureRequests(body);
  vi.spyOn(console, "error").mockImplementation(() => undefined);

  await expect(fetchKnowledgeBatch({
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "contract",
    context: "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}",
  });
});

test.each([401, 403, 404, 409, 410, 422, 500, 503])(
  "preserves upload HTTP %s details",
  async (status) => {
    const code = `upload_error_${status}`;
    const message = status === 404 ? "上传不可用" : `上传失败 ${status}`;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      code,
      message,
      traceId: `trace-body-${status}`,
    }), {
      status,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": `trace-header-${status}`,
        "Retry-After": status === 503 ? "19" : "0",
      },
    })));

    await expect(createKnowledgeUploadBatch({
      projectId: PROJECT_ID,
      csrfToken: "csrf-create",
      intents,
      signal: new AbortController().signal,
    })).rejects.toMatchObject({
      kind: "http",
      status,
      code,
      message,
      traceId: `trace-body-${status}`,
      retryAfterSeconds: status === 503 ? 19 : null,
      context: "POST /api/v1/projects/{project_id}/knowledge/uploads",
    });
  },
);

test("normalizes a non-JSON upload completion failure with the request ID", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("upstream html", {
    status: 500,
    headers: { "Content-Type": "text/html", "X-Request-ID": "trace-non-json" },
  })));

  await expect(completeKnowledgeUpload({
    projectId: PROJECT_ID,
    uploadId: UPLOAD_ID_1,
    batchId: BATCH_ID,
    itemId: ITEM_ID_1,
    csrfToken: "csrf-complete",
    signal: new AbortController().signal,
  })).rejects.toMatchObject({
    kind: "http",
    status: 500,
    code: "http_error",
    message: "服务器返回 500",
    traceId: "trace-non-json",
  });
});

test("preserves cancellation while fetching a knowledge batch", async () => {
  let requestSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    requestSignal = (input as Request).signal;
    return await new Promise<Response>((_resolve, reject) => {
      requestSignal?.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true },
      );
    });
  }));
  const controller = new AbortController();
  const pending = fetchKnowledgeBatch({
    projectId: PROJECT_ID,
    batchId: BATCH_ID,
    signal: controller.signal,
  });

  await vi.waitFor(() => expect(requestSignal).toBeDefined());
  controller.abort();

  await expect(pending).rejects.toMatchObject({
    kind: "aborted",
    message: "请求已被取消",
    context: "GET /api/v1/projects/{project_id}/knowledge/batches/{batch_id}",
  });
});

test("maps an unknown upload transport throw without leaking its value into the message", async () => {
  const fakeSecret = "presigned-secret-must-not-leak";
  vi.stubGlobal("fetch", vi.fn(async () => { throw { url: fakeSecret }; }));

  let caught: unknown;
  try {
    await createKnowledgeUploadBatch({
      projectId: PROJECT_ID,
      csrfToken: "csrf-create",
      intents,
      signal: new AbortController().signal,
    });
  } catch (error) {
    caught = error;
  }

  expect(caught).toMatchObject({
    kind: "network",
    message: "无法连接服务器，请检查网络",
    context: "POST /api/v1/projects/{project_id}/knowledge/uploads",
  });
  expect((caught as Error).message).not.toContain(fakeSecret);
});

test("puts the file with the exact object-store instruction and reports computable progress", async () => {
  const xhr = fakeXhr();
  const file = new File(["0123456789"], "design.pdf", { type: "application/pdf" });
  const onProgress = vi.fn();
  const xhrFactory = vi.fn(() => asXmlHttpRequest(xhr));
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file,
    signal: new AbortController().signal,
    onProgress,
    xhrFactory,
  });

  expect(xhrFactory).toHaveBeenCalledTimes(1);
  expect(xhr.open).toHaveBeenCalledWith("PUT", objectInstruction.url, true);
  expect(xhr.withCredentials).toBe(false);
  expect(xhr.setRequestHeader.mock.calls).toEqual(Object.entries(objectInstruction.headers));
  expect(xhr.send).toHaveBeenCalledWith(file);

  xhr.upload.onprogress?.({
    loaded: 4,
    total: 10,
    lengthComputable: true,
  } as ProgressEvent);
  expect(onProgress).toHaveBeenCalledWith({ loaded: 4, total: 10, percent: 40 });

  xhr.status = 200;
  fire(xhr.onload);
  await expect(pending).resolves.toBeUndefined();
});

test.each([
  ["same-origin", new URL("/private-object?signature=private-origin", window.location.href).href],
  ["unparseable", "http://[private-invalid-url"],
] as const)("rejects a %s instruction URL before constructing an XHR", async (_case, url) => {
  const xhr = fakeXhr();
  const xhrFactory = vi.fn(() => asXmlHttpRequest(xhr));
  const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
  const pending = putKnowledgeObject({
    instruction: { ...objectInstruction, url },
    file: new File(["blocked"], "notes.md"),
    signal: new AbortController().signal,
    onProgress: vi.fn(),
    xhrFactory,
  });
  const outcome = await Promise.race([
    pending.then(
      () => ({ state: "resolved" as const }),
      (caught: unknown) => ({ state: "rejected" as const, error: caught }),
    ),
    new Promise<{ state: "pending" }>((resolve) => {
      setTimeout(() => resolve({ state: "pending" }), 0);
    }),
  ]);

  expect({
    state: outcome.state,
    factoryCalls: xhrFactory.mock.calls.length,
    sendCalls: xhr.send.mock.calls.length,
  }).toEqual({ state: "rejected", factoryCalls: 0, sendCalls: 0 });
  if (outcome.state !== "rejected") throw new Error("expected unsafe URL rejection");
  expect(outcome.error).toMatchObject({
    kind: "network",
    message: "文件直传失败，请重试",
    context: null,
  });
  expect((outcome.error as Error & { cause?: unknown }).cause).toBeUndefined();
  expect((outcome.error as Error).message).not.toContain("private");
  expect(errorLog).not.toHaveBeenCalled();
});

test("accepts an object-store 204 response", async () => {
  const xhr = fakeXhr();
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["ok"], "notes.md"),
    signal: new AbortController().signal,
    onProgress: vi.fn(),
    xhrFactory: () => asXmlHttpRequest(xhr),
  });

  xhr.status = 204;
  fire(xhr.onload);

  await expect(pending).resolves.toBeUndefined();
});

test("uses the file size for uncomputable progress and keeps percentages finite", async () => {
  const xhr = fakeXhr();
  const onProgress = vi.fn();
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["0123456789"], "notes.md"),
    signal: new AbortController().signal,
    onProgress,
    xhrFactory: () => asXmlHttpRequest(xhr),
  });

  xhr.upload.onprogress?.({
    loaded: 8,
    total: 999,
    lengthComputable: false,
  } as ProgressEvent);
  xhr.upload.onprogress?.({
    loaded: 12,
    total: 10,
    lengthComputable: true,
  } as ProgressEvent);

  expect(onProgress).toHaveBeenNthCalledWith(1, { loaded: 8, total: 10, percent: 80 });
  expect(onProgress).toHaveBeenNthCalledWith(2, { loaded: 12, total: 10, percent: 100 });

  xhr.status = 200;
  fire(xhr.onload);
  await pending;

  const emptyXhr = fakeXhr();
  const emptyProgress = vi.fn();
  const emptyPending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File([], "empty.md"),
    signal: new AbortController().signal,
    onProgress: emptyProgress,
    xhrFactory: () => asXmlHttpRequest(emptyXhr),
  });
  emptyXhr.upload.onprogress?.({
    loaded: 0,
    total: 0,
    lengthComputable: false,
  } as ProgressEvent);

  expect(emptyProgress).toHaveBeenCalledWith({ loaded: 0, total: 0, percent: 0 });

  emptyXhr.status = 200;
  fire(emptyXhr.onload);
  await emptyPending;
});

test.each([403, 500])(
  "maps object-store HTTP %s to a fixed network error without reading or leaking secrets",
  async (status) => {
    const xhr = fakeXhr();
    const responseText = vi.fn(() => "private-response-body");
    Object.defineProperty(xhr, "responseText", { get: responseText });
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const pending = putKnowledgeObject({
      instruction: objectInstruction,
      file: new File(["secret"], "design.pdf"),
      signal: new AbortController().signal,
      onProgress: vi.fn(),
      xhrFactory: () => asXmlHttpRequest(xhr),
    });

    xhr.status = status;
    fire(xhr.onload);

    let caught: unknown;
    try {
      await pending;
    } catch (error) {
      caught = error;
    }
    expect(caught).toMatchObject({
      kind: "network",
      message: "文件直传失败，请重试",
      context: null,
    });
    expect((caught as Error & { cause?: unknown }).cause).toBeUndefined();
    expect(responseText).not.toHaveBeenCalled();
    expect(errorLog).not.toHaveBeenCalled();
    expect((caught as Error).message).not.toContain("private");
  },
);

test("maps an XHR network event to the fixed object-upload error", async () => {
  const xhr = fakeXhr();
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["network"], "notes.md"),
    signal: new AbortController().signal,
    onProgress: vi.fn(),
    xhrFactory: () => asXmlHttpRequest(xhr),
  });

  fire(xhr.onerror);

  await expect(pending).rejects.toMatchObject({
    kind: "network",
    message: "文件直传失败，请重试",
    context: null,
  });
});

test("maps an XHR abort event to cancellation", async () => {
  const xhr = fakeXhr();
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["abort"], "notes.md"),
    signal: new AbortController().signal,
    onProgress: vi.fn(),
    xhrFactory: () => asXmlHttpRequest(xhr),
  });

  fire(xhr.onabort);

  await expect(pending).rejects.toMatchObject({
    kind: "aborted",
    message: "请求已被取消",
    context: null,
  });
});

test("rejects a pre-aborted upload without constructing or sending an XHR", async () => {
  const controller = new AbortController();
  controller.abort();
  const xhrFactory = vi.fn(() => asXmlHttpRequest(fakeXhr()));

  await expect(putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["abort"], "notes.md"),
    signal: controller.signal,
    onProgress: vi.fn(),
    xhrFactory,
  })).rejects.toMatchObject({
    kind: "aborted",
    message: "请求已被取消",
  });

  expect(xhrFactory).not.toHaveBeenCalled();
});

test("aborts the active XHR from the signal even when xhr.abort throws", async () => {
  const xhr = fakeXhr();
  const secretThrownValue = { secret: "private-abort-throw" };
  xhr.abort.mockImplementation(() => { throw secretThrownValue; });
  const controller = new AbortController();
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["abort"], "notes.md"),
    signal: controller.signal,
    onProgress: vi.fn(),
    xhrFactory: () => asXmlHttpRequest(xhr),
  });

  controller.abort();

  await expect(pending).rejects.toMatchObject({
    kind: "aborted",
    message: "请求已被取消",
  });
  expect(xhr.abort).toHaveBeenCalledTimes(1);
});

test.each(["constructor", "open", "header", "send"] as const)(
  "normalizes a thrown %s value without retaining upload secrets",
  async (stage) => {
    const xhr = fakeXhr();
    const secretThrownValue = { secret: `private-${stage}-throw` };
    const xhrFactory = vi.fn(() => asXmlHttpRequest(xhr));
    if (stage === "constructor") xhrFactory.mockImplementation(() => { throw secretThrownValue; });
    if (stage === "open") xhr.open.mockImplementation(() => { throw secretThrownValue; });
    if (stage === "header") {
      xhr.setRequestHeader.mockImplementation(() => { throw secretThrownValue; });
    }
    if (stage === "send") xhr.send.mockImplementation(() => { throw secretThrownValue; });

    let caught: unknown;
    try {
      await putKnowledgeObject({
        instruction: objectInstruction,
        file: new File(["throws"], "notes.md"),
        signal: new AbortController().signal,
        onProgress: vi.fn(),
        xhrFactory,
      });
    } catch (error) {
      caught = error;
    }

    expect(caught).toMatchObject({
      kind: "network",
      message: "文件直传失败，请重试",
      context: null,
    });
    expect((caught as Error & { cause?: unknown }).cause).toBeUndefined();
    expect((caught as Error).message).not.toContain("private");
    if (stage !== "constructor") expect(xhr.send).toHaveBeenCalledTimes(stage === "send" ? 1 : 0);
  },
);

test("cleans listeners and handlers and settles only once across terminal races", async () => {
  const xhr = fakeXhr();
  const controller = new AbortController();
  const addListener = vi.spyOn(controller.signal, "addEventListener");
  const removeListener = vi.spyOn(controller.signal, "removeEventListener");
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["race"], "notes.md"),
    signal: controller.signal,
    onProgress: vi.fn(),
    xhrFactory: () => asXmlHttpRequest(xhr),
  });
  const load = xhr.onload;
  const error = xhr.onerror;
  const abort = xhr.onabort;

  expect(addListener).toHaveBeenCalledWith("abort", expect.any(Function), { once: true });
  xhr.status = 204;
  fire(load);
  fire(error);
  fire(abort);

  await expect(pending).resolves.toBeUndefined();
  expect(removeListener).toHaveBeenCalledTimes(1);
  expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
  expect(xhr.onload).toBeNull();
  expect(xhr.onerror).toBeNull();
  expect(xhr.onabort).toBeNull();
  expect(xhr.upload.onprogress).toBeNull();

  controller.abort();
  expect(xhr.abort).not.toHaveBeenCalled();
});

test.each(["normal", "reentrant", "throwing"] as const)(
  "normalizes a throwing progress callback, aborts with %s behavior, and ignores later events",
  async (abortBehavior) => {
    const xhr = fakeXhr();
    const controller = new AbortController();
    const removeListener = vi.spyOn(controller.signal, "removeEventListener");
    const secret = "private-progress-callback-value";
    const abortSecret = "private-progress-abort-value";
    const onProgress = vi.fn(() => { throw new Error(secret); });
    const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const pending = putKnowledgeObject({
      instruction: objectInstruction,
      file: new File(["progress"], "notes.md"),
      signal: controller.signal,
      onProgress,
      xhrFactory: () => asXmlHttpRequest(xhr),
    });
    const progress = xhr.upload.onprogress;
    const load = xhr.onload;
    const error = xhr.onerror;
    const abort = xhr.onabort;
    if (abortBehavior === "reentrant") xhr.abort.mockImplementation(() => fire(abort));
    if (abortBehavior === "throwing") {
      xhr.abort.mockImplementation(() => { throw new Error(abortSecret); });
    }

    let escaped = false;
    try {
      progress?.({ loaded: 4, total: 8, lengthComputable: true } as ProgressEvent);
    } catch {
      escaped = true;
    }
    const outcome = await Promise.race([
      pending.then(
        () => ({ state: "resolved" as const }),
        (caught: unknown) => ({ state: "rejected" as const, error: caught }),
      ),
      new Promise<{ state: "pending" }>((resolve) => {
        setTimeout(() => resolve({ state: "pending" }), 0);
      }),
    ]);

    expect({ escaped, state: outcome.state }).toEqual({ escaped: false, state: "rejected" });
    if (outcome.state !== "rejected") throw new Error("expected progress failure rejection");
    expect(outcome.error).toMatchObject({
      kind: "network",
      message: "文件直传失败，请重试",
      context: null,
    });
    expect((outcome.error as Error & { cause?: unknown }).cause).toBeUndefined();
    expect((outcome.error as Error).message).not.toContain(secret);
    expect((outcome.error as Error).message).not.toContain(abortSecret);
    expect(xhr.abort).toHaveBeenCalledTimes(1);
    expect(removeListener).toHaveBeenCalledTimes(1);
    expect(xhr.onload).toBeNull();
    expect(xhr.onerror).toBeNull();
    expect(xhr.onabort).toBeNull();
    expect(xhr.upload.onprogress).toBeNull();

    expect(() => {
      progress?.({ loaded: 8, total: 8, lengthComputable: true } as ProgressEvent);
      fire(load);
      fire(error);
      fire(abort);
      controller.abort();
    }).not.toThrow();
    expect(onProgress).toHaveBeenCalledTimes(1);
    expect(removeListener).toHaveBeenCalledTimes(1);
    expect(xhr.abort).toHaveBeenCalledTimes(1);
    expect(errorLog).not.toHaveBeenCalled();
  },
);

test("normalizes a throwing progress-event getter and makes later events inert", async () => {
  const xhr = fakeXhr();
  const controller = new AbortController();
  const removeListener = vi.spyOn(controller.signal, "removeEventListener");
  const secret = "private-progress-getter-value";
  const readLoaded = vi.fn(() => { throw new Error(secret); });
  const event = {} as ProgressEvent;
  Object.defineProperties(event, {
    loaded: { get: readLoaded },
    total: { value: 8 },
    lengthComputable: { value: true },
  });
  const onProgress = vi.fn();
  const errorLog = vi.spyOn(console, "error").mockImplementation(() => undefined);
  const pending = putKnowledgeObject({
    instruction: objectInstruction,
    file: new File(["progress"], "notes.md"),
    signal: controller.signal,
    onProgress,
    xhrFactory: () => asXmlHttpRequest(xhr),
  });
  const progress = xhr.upload.onprogress;
  const load = xhr.onload;
  const error = xhr.onerror;
  const abort = xhr.onabort;

  let escaped = false;
  try {
    progress?.(event);
  } catch {
    escaped = true;
  }
  const outcome = await Promise.race([
    pending.then(
      () => ({ state: "resolved" as const }),
      (caught: unknown) => ({ state: "rejected" as const, error: caught }),
    ),
    new Promise<{ state: "pending" }>((resolve) => {
      setTimeout(() => resolve({ state: "pending" }), 0);
    }),
  ]);

  expect({ escaped, state: outcome.state }).toEqual({ escaped: false, state: "rejected" });
  if (outcome.state !== "rejected") throw new Error("expected progress getter rejection");
  expect(outcome.error).toMatchObject({
    kind: "network",
    message: "文件直传失败，请重试",
    context: null,
  });
  expect((outcome.error as Error & { cause?: unknown }).cause).toBeUndefined();
  expect((outcome.error as Error).message).not.toContain(secret);
  expect(readLoaded).toHaveBeenCalledTimes(1);
  expect(onProgress).not.toHaveBeenCalled();
  expect(xhr.abort).toHaveBeenCalledTimes(1);
  expect(removeListener).toHaveBeenCalledTimes(1);
  expect(xhr.onload).toBeNull();
  expect(xhr.onerror).toBeNull();
  expect(xhr.onabort).toBeNull();
  expect(xhr.upload.onprogress).toBeNull();

  expect(() => {
    progress?.(event);
    fire(load);
    fire(error);
    fire(abort);
    controller.abort();
  }).not.toThrow();
  expect(readLoaded).toHaveBeenCalledTimes(1);
  expect(onProgress).not.toHaveBeenCalled();
  expect(xhr.abort).toHaveBeenCalledTimes(1);
  expect(removeListener).toHaveBeenCalledTimes(1);
  expect(errorLog).not.toHaveBeenCalled();
});
