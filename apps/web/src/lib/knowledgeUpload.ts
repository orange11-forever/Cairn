import { ApiError } from "../api/errors.ts";

export const SUPPORTED_KNOWLEDGE_UPLOADS = Object.freeze({
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".csv": "text/csv",
  ".html": "text/html",
  ".htm": "text/html",
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".markdown": "text/markdown",
  ".zip": "application/zip",
} as const);

export const KNOWLEDGE_UPLOAD_ACCEPT = Object.keys(SUPPORTED_KNOWLEDGE_UPLOADS).join(",");

export interface KnowledgeFileIssue {
  index: number | null;
  error: string;
}

export interface PreparedKnowledgeFile {
  file: File;
  intent: {
    fileName: string;
    mediaType: string;
    sizeBytes: number;
    sha256: string;
  };
}

const MAX_FILE_COUNT = 20;
const REGULAR_FILE_MAX_BYTES = 50 * 1024 * 1024;
const ZIP_FILE_MAX_BYTES = 100 * 1024 * 1024;
const INVALID_FILE_NAME = /[\\/\u0000-\u001f\u007f-\u009f]/u;

type SupportedExtension = keyof typeof SUPPORTED_KNOWLEDGE_UPLOADS;

function extensionOf(fileName: string): string {
  const dot = fileName.lastIndexOf(".");
  return dot < 0 ? "" : fileName.slice(dot).toLowerCase();
}

function isSupportedExtension(extension: string): extension is SupportedExtension {
  return Object.hasOwn(SUPPORTED_KNOWLEDGE_UPLOADS, extension);
}

function hasValidName(fileName: string): boolean {
  const characterCount = [...fileName].length;
  return characterCount >= 1 &&
    characterCount <= 255 &&
    fileName === fileName.trim() &&
    !INVALID_FILE_NAME.test(fileName);
}

export function validateKnowledgeFiles(files: readonly File[]): KnowledgeFileIssue[] {
  const issues: KnowledgeFileIssue[] = [];
  if (files.length < 1 || files.length > MAX_FILE_COUNT) {
    issues.push({ index: null, error: "一次必须上传 1 至 20 个文件" });
  }

  const seenNames = new Set<string>();
  let hasDuplicate = false;

  files.forEach((file, index) => {
    const validName = hasValidName(file.name);
    if (!validName) {
      issues.push({
        index,
        error: "文件名必须为 1 至 255 个字符，且不得包含路径分隔符、NUL、控制字符或首尾空白",
      });
    }

    const duplicateKey = file.name.normalize("NFC").toLowerCase();
    if (seenNames.has(duplicateKey)) hasDuplicate = true;
    seenNames.add(duplicateKey);

    const extension = extensionOf(file.name);
    const supportedExtension = isSupportedExtension(extension);
    if (!supportedExtension) issues.push({ index, error: "文件类型不受支持" });

    if (file.size === 0) {
      issues.push({ index, error: "文件不能为空" });
      return;
    }

    if (!supportedExtension) return;
    const maxBytes = extension === ".zip" ? ZIP_FILE_MAX_BYTES : REGULAR_FILE_MAX_BYTES;
    if (file.size > maxBytes) {
      const maxMegabytes = maxBytes / (1024 * 1024);
      issues.push({ index, error: `文件大小不能超过 ${maxMegabytes.toFixed(1)} MB` });
    }
  });

  if (hasDuplicate) {
    issues.push({ index: null, error: "同一批次包含重复文件名" });
  }
  return issues;
}

function throwIfAborted(signal: AbortSignal): void {
  if (signal.aborted) throw new ApiError("aborted", "请求已被取消");
}

// Native reads/digests cannot be aborted. Keep their buffer ownership exclusive
// across operations and hook instances until the underlying work really settles.
let previousHashFinished = Promise.resolve();

export async function sha256Hex(blob: Blob, signal: AbortSignal): Promise<string> {
  throwIfAborted(signal);
  const previous = previousHashFinished;
  let release!: () => void;
  previousHashFinished = new Promise<void>((resolve) => { release = resolve; });
  await previous;
  try {
    throwIfAborted(signal);
    const bytes = await blob.arrayBuffer();
    throwIfAborted(signal);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    throwIfAborted(signal);

    let hexadecimal = "";
    for (const byte of new Uint8Array(digest)) {
      hexadecimal += byte.toString(16).padStart(2, "0");
    }
    return hexadecimal;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (signal.aborted) throw new ApiError("aborted", "请求已被取消", { cause: error });
    throw new ApiError("network", "无法读取文件，请重新选择", { cause: error });
  } finally {
    release();
  }
}

export async function prepareKnowledgeFiles(
  files: readonly File[],
  signal: AbortSignal,
  onHashing: (index: number) => void,
): Promise<PreparedKnowledgeFile[]> {
  const prepared: PreparedKnowledgeFile[] = [];
  for (const [index, file] of files.entries()) {
    throwIfAborted(signal);
    onHashing(index);
    const sha256 = await sha256Hex(file, signal);
    const extension = extensionOf(file.name);
    if (!isSupportedExtension(extension)) {
      throw new ApiError("contract", "文件类型不受支持");
    }
    prepared.push({
      file,
      intent: {
        fileName: file.name,
        mediaType: SUPPORTED_KNOWLEDGE_UPLOADS[extension],
        sizeBytes: file.size,
        sha256,
      },
    });
  }
  return prepared;
}
