import { afterEach, describe, expect, test, vi } from "vitest";

import { ApiError } from "../../src/api/errors.ts";
import {
  KNOWLEDGE_UPLOAD_ACCEPT,
  SUPPORTED_KNOWLEDGE_UPLOADS,
  prepareKnowledgeFiles,
  sha256Hex,
  validateKnowledgeFiles,
} from "../../src/lib/knowledgeUpload.ts";

const MIB = 1024 * 1024;

afterEach(() => {
  vi.restoreAllMocks();
});

function file(name: string, size = 1): File {
  const value = new File(["x"], name);
  Object.defineProperty(value, "size", { configurable: true, value: size });
  return value;
}

describe("knowledge upload media validation", () => {
  test("maps every supported extension to the server canonical media type", async () => {
    const expected = [
      [".pdf", "application/pdf"],
      [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
      [".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"],
      [".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
      [".csv", "text/csv"],
      [".html", "text/html"],
      [".htm", "text/html"],
      [".txt", "text/plain"],
      [".md", "text/markdown"],
      [".markdown", "text/markdown"],
      [".zip", "application/zip"],
    ] as const;

    expect(Object.entries(SUPPORTED_KNOWLEDGE_UPLOADS)).toEqual(expected);
    expect(KNOWLEDGE_UPLOAD_ACCEPT).toBe(expected.map(([extension]) => extension).join(","));

    const files = expected.map(([extension]) => file(`SOURCE${extension.toUpperCase()}`));
    expect(validateKnowledgeFiles(files)).toEqual([]);

    const prepared = await prepareKnowledgeFiles(
      files,
      new AbortController().signal,
      () => undefined,
    );
    expect(prepared.map(({ intent }) => intent.mediaType)).toEqual(
      expected.map(([, mediaType]) => mediaType),
    );
  });

  test("accepts the exact file count and byte limits", () => {
    expect(validateKnowledgeFiles(Array.from({ length: 20 }, (_, index) => file(`${index}.pdf`)))).toEqual([]);
    expect(validateKnowledgeFiles([file("deck.pptx", 50 * MIB)])).toEqual([]);
    expect(validateKnowledgeFiles([file("archive.zip", 100 * MIB)])).toEqual([]);
  });

  test("reports empty selections, excess files, empty files, and bytes beyond each limit", () => {
    expect(validateKnowledgeFiles([])).toContainEqual(
      expect.objectContaining({ error: "一次必须上传 1 至 20 个文件" }),
    );
    expect(validateKnowledgeFiles(Array.from({ length: 21 }, (_, index) => file(`${index}.pdf`))))
      .toContainEqual(expect.objectContaining({ error: "一次必须上传 1 至 20 个文件" }));
    expect(validateKnowledgeFiles([file("empty.txt", 0)])[0]?.error).toContain("不能为空");
    expect(validateKnowledgeFiles([file("large.pdf", 50 * MIB + 1)])[0]?.error).toContain("50.0 MB");
    expect(validateKnowledgeFiles([file("large.zip", 100 * MIB + 1)])[0]?.error).toContain("100.0 MB");
  });

  test("collects independent name, extension, empty, and size issues in one pass", () => {
    expect(validateKnowledgeFiles([file("../invalid.pdf", 50 * MIB + 1)]))
      .toEqual([
        expect.objectContaining({ index: 0, error: expect.stringContaining("文件名") }),
        expect.objectContaining({ index: 0, error: expect.stringContaining("50.0 MB") }),
      ]);
    expect(validateKnowledgeFiles([file("unsupported.exe", 0)]))
      .toEqual([
        { index: 0, error: "文件类型不受支持" },
        { index: 0, error: "文件不能为空" },
      ]);
  });

  test("rejects unsupported extensions without trusting File.type", () => {
    const unsupported = new File(["x"], "legacy.doc", { type: "application/pdf" });
    const disguised = new File(["x"], "report.pdf", { type: "text/plain" });

    expect(validateKnowledgeFiles([unsupported])[0]?.error).toContain("文件类型不受支持");
    expect(validateKnowledgeFiles([disguised])).toEqual([]);
  });
});

describe("knowledge upload file names", () => {
  test.each([
    "",
    " report.pdf",
    "report.pdf ",
    "../secret.txt",
    String.raw`folder\secret.txt`,
    "bad\0name.txt",
    "bad\u0001name.txt",
    "bad\u0085name.txt",
  ])("rejects an unsafe file name: %j", (name) => {
    expect(validateKnowledgeFiles([file(name, 1)])[0]?.error).toContain("文件名");
  });

  test("enforces the 1 to 255 character boundary by Unicode characters", () => {
    expect(validateKnowledgeFiles([file(`${"a".repeat(251)}.pdf`)])).toEqual([]);
    expect(validateKnowledgeFiles([file(`${"a".repeat(252)}.pdf`)])[0]?.error).toContain("255");
    expect(validateKnowledgeFiles([file(`${"😀".repeat(251)}.pdf`)])).toEqual([]);
  });

  test("reports NFC and locale-independent lowercase duplicates once at batch level", () => {
    expect(validateKnowledgeFiles([
      file("Résumé.pdf"),
      file("RE\u0301SUME\u0301.PDF"),
    ])).toContainEqual(expect.objectContaining({
      error: "同一批次包含重复文件名",
      index: null,
    }));
    expect(validateKnowledgeFiles([file("I.PDF"), file("i.pdf")]))
      .toContainEqual(expect.objectContaining({ error: "同一批次包含重复文件名" }));
  });
});

describe("knowledge upload hashing", () => {
  test("returns the known SHA-256 digest as lowercase hexadecimal", async () => {
    await expect(sha256Hex(new Blob(["abc"]), new AbortController().signal))
      .resolves.toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  test("hashes file reads serially and reports each hashing index in request order", async () => {
    let activeArrayBuffers = 0;
    let maxActiveArrayBuffers = 0;
    const files = [file("one.txt"), file("two.txt"), file("three.txt")];
    for (const [index, value] of files.entries()) {
      Object.defineProperty(value, "arrayBuffer", {
        configurable: true,
        value: vi.fn(async () => {
          activeArrayBuffers += 1;
          maxActiveArrayBuffers = Math.max(maxActiveArrayBuffers, activeArrayBuffers);
          await Promise.resolve();
          activeArrayBuffers -= 1;
          return new Uint8Array([index]).buffer;
        }),
      });
    }
    const onHashing = vi.fn();

    const prepared = await prepareKnowledgeFiles(
      files,
      new AbortController().signal,
      onHashing,
    );

    expect(maxActiveArrayBuffers).toBe(1);
    expect(onHashing.mock.calls).toEqual([[0], [1], [2]]);
    expect(prepared.map(({ file: preparedFile }) => preparedFile)).toEqual(files);
    expect(prepared.map(({ intent }) => intent.fileName)).toEqual(files.map(({ name }) => name));
  });

  test("prepares the complete canonical upload intent", async () => {
    const source = new File(["abc"], "REPORT.PDF", { type: "text/plain" });

    await expect(prepareKnowledgeFiles(
      [source],
      new AbortController().signal,
      () => undefined,
    )).resolves.toEqual([{
      file: source,
      intent: {
        fileName: "REPORT.PDF",
        mediaType: "application/pdf",
        sizeBytes: 3,
        sha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
      },
    }]);
  });

  test("rejects an already-aborted request without reading the blob", async () => {
    const controller = new AbortController();
    controller.abort();
    const value = file("notes.txt");
    const arrayBuffer = vi.fn();
    Object.defineProperty(value, "arrayBuffer", { configurable: true, value: arrayBuffer });

    await expect(sha256Hex(value, controller.signal)).rejects.toMatchObject({ kind: "aborted" });
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  test("pre-aborted preparation performs no hashing callback, file read, or digest", async () => {
    const controller = new AbortController();
    controller.abort();
    const value = file("pre-aborted.txt");
    const arrayBuffer = vi.fn();
    const onHashing = vi.fn();
    const digest = vi.spyOn(globalThis.crypto.subtle, "digest");
    Object.defineProperty(value, "arrayBuffer", { configurable: true, value: arrayBuffer });

    await expect(prepareKnowledgeFiles([value], controller.signal, onHashing))
      .rejects.toMatchObject({ kind: "aborted" });

    expect(onHashing).not.toHaveBeenCalled();
    expect(arrayBuffer).not.toHaveBeenCalled();
    expect(digest).not.toHaveBeenCalled();
  });

  test("stops before digest and the next file when cancellation happens during a read", async () => {
    const controller = new AbortController();
    const files = [file("one.txt"), file("two.txt")];
    const digest = vi.spyOn(globalThis.crypto.subtle, "digest");
    const firstRead = vi.fn(async () => {
      controller.abort();
      return new Uint8Array([1]).buffer;
    });
    const secondRead = vi.fn(async () => new Uint8Array([2]).buffer);
    Object.defineProperty(files[0]!, "arrayBuffer", { configurable: true, value: firstRead });
    Object.defineProperty(files[1]!, "arrayBuffer", { configurable: true, value: secondRead });

    await expect(prepareKnowledgeFiles(files, controller.signal, vi.fn()))
      .rejects.toMatchObject({ kind: "aborted" });
    expect(firstRead).toHaveBeenCalledOnce();
    expect(digest).not.toHaveBeenCalled();
    expect(secondRead).not.toHaveBeenCalled();
  });

  test("rejects cancellation observed immediately after digesting", async () => {
    const controller = new AbortController();
    vi.spyOn(globalThis.crypto.subtle, "digest").mockImplementationOnce(async () => {
      controller.abort();
      return new ArrayBuffer(32);
    });

    await expect(sha256Hex(new Blob(["safe"]), controller.signal))
      .rejects.toMatchObject({ kind: "aborted" });
  });

  test("converts an unexpected blob read failure to a safe ApiError", async () => {
    const secret = "signed-object-secret";
    const thrown = { secret };
    const unreadable = file("unreadable.txt");
    Object.defineProperty(unreadable, "arrayBuffer", {
      configurable: true,
      value: vi.fn(async () => { throw thrown; }),
    });

    const readFailure = await sha256Hex(unreadable, new AbortController().signal)
      .catch((error: unknown) => error);
    expect(readFailure).toBeInstanceOf(ApiError);
    expect(readFailure).toMatchObject({ kind: "network", message: "无法读取文件，请重新选择" });
    expect((readFailure as ApiError).cause).toBe(thrown);
    expect(String(readFailure)).not.toContain(secret);
  });

  test("rethrows an existing ApiError without changing its identity or kind", async () => {
    const sentinel = new ApiError("contract", "sentinel contract failure");
    const unreadable = file("unreadable.txt");
    Object.defineProperty(unreadable, "arrayBuffer", {
      configurable: true,
      value: vi.fn(async () => { throw sentinel; }),
    });

    const failure = await sha256Hex(unreadable, new AbortController().signal)
      .catch((error: unknown) => error);
    expect(failure).toBe(sentinel);
    expect(failure).toMatchObject({ kind: "contract" });
  });

  test("converts an unexpected crypto failure to a safe ApiError", async () => {
    const secret = "signed-object-secret";
    vi.spyOn(globalThis.crypto.subtle, "digest")
      .mockRejectedValueOnce({ secret });
    const digestFailure = await sha256Hex(new Blob(["safe"]), new AbortController().signal)
      .catch((error: unknown) => error);
    expect(digestFailure).toBeInstanceOf(ApiError);
    expect(digestFailure).toMatchObject({ kind: "network", message: "无法读取文件，请重新选择" });
    expect(String(digestFailure)).not.toContain(secret);
  });
});
