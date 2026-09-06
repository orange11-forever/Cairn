import { FileUp, RefreshCw, RotateCcw, Trash2, X } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
} from "react";

import { ApiError } from "../../api/errors.ts";
import type { KnowledgeBatchDetail } from "../../api/knowledgeUploads.ts";
import {
  canRetryKnowledgeUploadCreate,
  canRetryKnowledgeUploadFile,
  useKnowledgeUploadBatch,
  type KnowledgeUploadBatchState,
  type KnowledgeUploadFilePhase,
} from "../../hooks/useKnowledgeUploadBatch.ts";
import {
  KNOWLEDGE_UPLOAD_ACCEPT,
  SUPPORTED_KNOWLEDGE_UPLOADS,
} from "../../lib/knowledgeUpload.ts";
import { formatBytes } from "../../lib/validation.ts";

export interface KnowledgeUploadBatchProps {
  organizationId: string;
  projectId: string;
  csrfToken: string;
  sessionSignal: AbortSignal;
  onAccessUnavailable(error: ApiError): void;
}

const FILE_PHASE_LABELS: Record<KnowledgeUploadFilePhase, string> = {
  selected: "等待上传",
  hashing: "正在计算校验值",
  creating: "正在创建上传批次",
  uploading: "正在上传",
  completing: "正在确认",
  awaiting_upload: "等待服务器接收上传",
  queued: "已确认，等待 Worker 处理",
  processing: "Worker 正在处理",
  ready: "Worker 处理完成，可用于知识检索",
  failed: "处理失败",
  cancelled: "已取消",
};

function isCreateRetry(upload: KnowledgeUploadBatchState): boolean {
  return upload.batch === null && canRetryKnowledgeUploadCreate(upload);
}

function canStartUpload(upload: KnowledgeUploadBatchState): boolean {
  if (upload.pending || upload.files.length === 0 || upload.issues.length > 0) return false;
  if (isCreateRetry(upload)) return true;
  return upload.error === null &&
    upload.batchError === null &&
    upload.batchId === null &&
    upload.startedAt === null &&
    upload.batch === null &&
    upload.files.every((file) =>
      file.phase === "selected" &&
      file.itemId === null &&
      file.error === null &&
      file.failureStage === null
    );
}

function batchSummary(upload: KnowledgeUploadBatchState): string {
  if (upload.issues.length > 0) return "所选文件需要修正后才能开始上传。";
  if (upload.files.length === 0) return "请选择文件，或把文件拖放到选择区域。";
  if (upload.files.every(({ phase }) => phase === "cancelled")) {
    return "当前浏览器中的上传已取消。已确认的服务器工作可能继续。";
  }
  if (isCreateRetry(upload)) return "上传批次尚未创建，可以重新尝试。";
  if (upload.pending) {
    const activePhase = upload.files.find(({ phase }) =>
      phase === "hashing" ||
      phase === "creating" ||
      phase === "uploading" ||
      phase === "completing"
    )?.phase;
    return activePhase === undefined
      ? "正在准备上传。"
      : `${FILE_PHASE_LABELS[activePhase]}。`;
  }
  if (upload.batch !== null) {
    switch (upload.batch.status) {
      case "pending":
        return "服务器已接收上传批次，正在等待 Worker。";
      case "processing":
        return "Worker 正在处理已确认的文件。";
      case "completed":
        return "Worker 已完成本批次处理，可在知识资料中查看就绪文件。";
      case "completed_with_errors":
        return "Worker 已完成本批次处理，部分文件处理失败。";
      case "failed":
        return "Worker 无法完成本批次处理，请检查失败文件。";
    }
  }
  if (upload.files.some(({ phase }) => phase === "failed")) {
    return "部分文件失败，请查看文件旁的错误和可用操作。";
  }
  if (upload.files.every(({ phase }) => phase === "ready")) {
    return "所有文件均已由 Worker 处理就绪。";
  }
  return `已选择 ${upload.files.length} 个文件，可以开始上传。`;
}

function previousFinalSummary(upload: KnowledgeUploadBatchState): string | null {
  const summary = upload.lastFinalSummary;
  if (summary === null || upload.batchId !== null) return null;
  if (summary.status === "completed") {
    return `上一批次已完成：${summary.readyCount} 个文件就绪。`;
  }
  if (summary.status === "completed_with_errors") {
    return `上一批次已完成：${summary.readyCount} 个就绪，${summary.failedCount} 个失败。`;
  }
  return `上一批次处理失败：${summary.failedCount} 个文件失败。`;
}

function samePresentedError(left: ApiError | null, right: ApiError | null): boolean {
  return left !== null &&
    right !== null &&
    left.message === right.message &&
    left.traceId === right.traceId;
}

function PresentedError({
  error,
  className,
}: {
  error: ApiError;
  className: string;
}) {
  return (
    <div className={className} role="alert">
      <p>{error.message}</p>
      {error.traceId === null ? null : <p>请求编号：{error.traceId}</p>}
    </div>
  );
}

function BatchChildList({
  parentName,
  parentItemId,
  items,
}: {
  parentName: string;
  parentItemId: string;
  items: KnowledgeBatchDetail["items"];
}) {
  const children = items.filter((item) => item.parentItemId === parentItemId);
  if (children.length === 0) return null;
  return (
    <ol className="knowledge-upload-child-list" aria-label={`${parentName} 中的文件`}>
      {children.map((item) => (
        <li
          className="knowledge-upload-child"
          data-status={item.status}
          key={item.id}
        >
          <div className="knowledge-upload-child-heading">
            <span className="knowledge-upload-child-path">{item.normalizedPath}</span>
            <span className="knowledge-upload-file-status" data-status={item.status}>
              {FILE_PHASE_LABELS[item.status]}
            </span>
          </div>
          {item.errorDetail === null ? null : (
            <p className="knowledge-upload-file-error" role="alert">
              {item.errorDetail}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

export function KnowledgeUploadBatch(props: KnowledgeUploadBatchProps) {
  const inputId = useId();
  const hintId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragActive, setDragActive] = useState(false);
  const upload = useKnowledgeUploadBatch(props);
  const hasEligibleRetry = upload.files.some(canRetryKnowledgeUploadFile);
  const hasWorkerFailure = upload.files.some(({ phase, failureStage }) =>
    phase === "failed" && failureStage === "worker"
  );
  const createRetry = isCreateRetry(upload);
  const canStart = canStartUpload(upload);
  const canStopTracking = upload.batchId !== null &&
    !upload.batchTrackingStopped &&
    (upload.batch === null || (
      upload.batch.status !== "completed" &&
      upload.batch.status !== "completed_with_errors" &&
      upload.batch.status !== "failed"
    ));
  const retainedSummary = previousFinalSummary(upload);
  const inputErrorIds = upload.issues.map((issue, index) => (
    issue.index === null
      ? `${inputId}-batch-error-${index}`
      : `${inputId}-file-${issue.index}-error-${index}`
  ));
  const duplicateOperationError = upload.files.some(({ error }) =>
    samePresentedError(error, upload.error)
  );

  useEffect(() => {
    if (upload.files.length === 0 && inputRef.current !== null) {
      inputRef.current.value = "";
    }
  }, [upload.files.length]);

  useEffect(() => {
    if (!upload.pending) return;
    dragDepth.current = 0;
    setDragActive(false);
  }, [upload.pending]);

  function selectFiles(files: readonly File[]) {
    if (upload.pending || files.length === 0) return;
    upload.select(files);
  }

  function changeSelection(event: ChangeEvent<HTMLInputElement>) {
    selectFiles(event.currentTarget.files === null ? [] : [...event.currentTarget.files]);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canStart) {
      inputRef.current?.focus();
      return;
    }
    void upload.start();
  }

  function clear() {
    dragDepth.current = 0;
    setDragActive(false);
    if (inputRef.current !== null) inputRef.current.value = "";
    upload.clear();
    inputRef.current?.focus();
  }

  function dragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (upload.pending) return;
    dragDepth.current += 1;
    setDragActive(true);
  }

  function dragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!upload.pending) event.dataTransfer.dropEffect = "copy";
  }

  function dragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragActive(false);
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    const files = [...event.dataTransfer.files];
    if (!upload.pending && files.length > 0 && inputRef.current !== null) {
      inputRef.current.value = "";
    }
    selectFiles(files);
  }

  return (
    <section className="knowledge-upload-batch" aria-labelledby={`${inputId}-heading`}>
      <div className="knowledge-upload-heading">
        <h2 id={`${inputId}-heading`}>批量上传知识资料</h2>
        <p>先上传文件并确认到服务器，再由 Worker 异步处理；只有就绪文件可用于知识检索。</p>
      </div>

      <form className="knowledge-upload-form" aria-label="知识资料批量上传" onSubmit={submit}>
        <div
          className="knowledge-upload-drop-region"
          data-drag-active={dragActive ? "true" : undefined}
          role="group"
          aria-label="选择知识资料"
          onDragEnter={dragEnter}
          onDragOver={dragOver}
          onDragLeave={dragLeave}
          onDrop={drop}
        >
          <label htmlFor={inputId}>上传知识资料</label>
          <input
            id={inputId}
            ref={inputRef}
            name="knowledge-files"
            type="file"
            multiple
            accept={KNOWLEDGE_UPLOAD_ACCEPT}
            disabled={upload.pending}
            aria-invalid={upload.issues.length > 0 ? "true" : undefined}
            aria-describedby={[hintId, ...inputErrorIds].join(" ")}
            onChange={changeSelection}
          />
          <p className="knowledge-upload-hint" id={hintId}>
            支持 {Object.keys(SUPPORTED_KNOWLEDGE_UPLOADS).join("、")}；普通文件不超过 50 MB，ZIP 不超过 100 MB，一次 1 至 20 个文件。也可拖放到此处。
          </p>
        </div>

        {upload.files.length === 0 ? null : (
          <ol
            className="knowledge-upload-file-list"
            aria-label="本批次文件"
            aria-busy={upload.pending ? "true" : undefined}
          >
            {upload.files.map((fileState, fileIndex) => {
              const issues = upload.issues
                .map((issue, issueIndex) => ({ issue, issueIndex }))
                .filter(({ issue }) => issue.index === fileIndex);
              const children = upload.batch === null || fileState.itemId === null
                ? null
                : (
                    <BatchChildList
                      parentName={fileState.file.name}
                      parentItemId={fileState.itemId}
                      items={upload.batch.items}
                    />
                  );
              return (
                <li
                  className="knowledge-upload-file"
                  data-invalid={issues.length > 0 ? "true" : undefined}
                  data-phase={fileState.phase}
                  key={`${fileState.file.name}-${fileIndex}`}
                >
                  <div className="knowledge-upload-file-heading">
                    <span className="knowledge-upload-file-name">{fileState.file.name}</span>
                    <span className="knowledge-upload-file-size">{formatBytes(fileState.file.size)}</span>
                  </div>
                  <div className="knowledge-upload-file-state">
                    <span className="knowledge-upload-file-status" data-status={fileState.phase}>
                      {FILE_PHASE_LABELS[fileState.phase]}
                    </span>
                    {fileState.phase !== "uploading" ? null : (
                      <div className="knowledge-upload-progress">
                        <progress
                          aria-label={`${fileState.file.name} 上传进度`}
                          max={100}
                          value={fileState.progress?.percent ?? 0}
                        />
                        <span className="knowledge-upload-progress-text">
                          {fileState.progress?.percent ?? 0}%
                        </span>
                      </div>
                    )}
                  </div>
                  {issues.map(({ issue, issueIndex }) => (
                    <p
                      className="knowledge-upload-file-error"
                      id={`${inputId}-file-${fileIndex}-error-${issueIndex}`}
                      role="alert"
                      key={`${issue.error}-${issueIndex}`}
                    >
                      {issue.error}
                    </p>
                  ))}
                  {fileState.error === null ? null : (
                    <PresentedError
                      error={fileState.error}
                      className="knowledge-upload-file-error"
                    />
                  )}
                  {children}
                </li>
              );
            })}
          </ol>
        )}

        {upload.issues.map((issue, issueIndex) => issue.index === null ? (
          <p
            className="knowledge-upload-batch-error"
            id={`${inputId}-batch-error-${issueIndex}`}
            role="alert"
            aria-label="批次校验错误"
            key={`${issue.error}-${issueIndex}`}
          >
            {issue.error}
          </p>
        ) : null)}

        <p className="knowledge-upload-summary" aria-live="polite" aria-atomic="true">
          {batchSummary(upload)}
        </p>
        {retainedSummary === null ? null : (
          <p className="knowledge-upload-previous-summary">{retainedSummary}</p>
        )}

        {upload.error === null || duplicateOperationError ? null : (
          <PresentedError error={upload.error} className="knowledge-upload-operation-error" />
        )}
        {upload.batchError === null ? null : (
          <PresentedError error={upload.batchError} className="knowledge-upload-batch-error" />
        )}

        {upload.files.length === 0 ? null : (
          <p className="knowledge-upload-cancel-note">
            取消只会停止当前浏览器中的上传，不会撤销已在服务器确认的工作；Worker 仍可能继续处理。
          </p>
        )}
        {upload.batchId === null ? null : (
          <p className="knowledge-upload-refresh-note">
            {upload.batchPollingTimedOut
              ? "后台仍在处理；自动跟踪已停止，请手动刷新处理状态。"
              : upload.batchTrackingStopped
                ? "已停止自动跟踪；服务器仍可能继续处理，可手动刷新。"
                : "处理状态会自动刷新最多 5 分钟；之后仍可手动刷新。"}
          </p>
        )}
        {hasWorkerFailure ? (
          <p className="knowledge-upload-retry-note">
            Worker 处理失败的文件不能原地重试，请修正后重新选择。
          </p>
        ) : null}

        <div className="knowledge-upload-actions">
          <button type="submit" disabled={!canStart}>
            <FileUp aria-hidden="true" size={18} />
            {upload.pending
              ? "上传与确认中…"
              : createRetry
                ? "重新创建上传批次"
                : "开始上传"}
          </button>
          {upload.pending ? (
            <button type="button" className="secondary-action" onClick={upload.cancel}>
              <X aria-hidden="true" size={18} />
              取消当前上传
            </button>
          ) : null}
          {!upload.pending && canStopTracking ? (
            <button type="button" className="secondary-action" onClick={upload.cancel}>
              <X aria-hidden="true" size={18} />
              停止自动跟踪
            </button>
          ) : null}
          {hasEligibleRetry && !upload.pending ? (
            <button
              type="button"
              className="secondary-action"
              onClick={() => void upload.retryFailed()}
            >
              <RotateCcw aria-hidden="true" size={18} />
              重新上传失败文件
            </button>
          ) : null}
          {upload.batchId === null ? null : (
            <button
              type="button"
              className="secondary-action"
              onClick={() => void upload.refreshBatch()}
            >
              <RefreshCw aria-hidden="true" size={18} />
              刷新处理状态
            </button>
          )}
          {upload.files.length > 0 && !upload.pending ? (
            <button type="button" className="secondary-action" onClick={clear}>
              <Trash2 aria-hidden="true" size={18} />
              清空选择
            </button>
          ) : null}
        </div>
      </form>
    </section>
  );
}
