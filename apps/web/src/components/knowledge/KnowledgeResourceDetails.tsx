import { RefreshCw } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/errors.ts";
import { buildKnowledgeDownloadUrl, type KnowledgeResource } from "../../api/knowledge.ts";
import {
  deleteKnowledgeResource,
  retryKnowledgeResourceVersion,
} from "../../api/knowledgeResources.ts";
import { formatCalendarDate } from "../../lib/dateTime.ts";
import { formatKnowledgeMediaType } from "../../lib/knowledgeSearch.ts";
import { formatBytes } from "../../lib/validation.ts";
import { knowledgeKeys, useKnowledgeResourceQuery } from "../../queries/knowledge.ts";

const DATE_TIME = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit",
});
const STATUS: Record<NonNullable<KnowledgeResource["latestVersion"]>["status"], string> = {
  queued: "等待处理", processing: "处理中", ready: "可检索", failed: "处理失败",
};
const FAILURE: Record<string, string> = {
  archive_duplicate_path: "压缩包包含重复路径，无法安全处理。",
  archive_encrypted: "加密压缩包暂不支持，请上传未加密文件。",
  archive_limit_exceeded: "压缩包超过安全处理限制，请缩小或拆分后重新上传。",
  archive_nested: "不支持嵌套压缩包，请解压后分别上传。",
  archive_path_unsafe: "压缩包包含不安全路径，无法处理。",
  database_unavailable: "数据库暂时不可用，请稍后刷新状态。",
  embedding_dimension_mismatch: "向量模型配置不匹配，请联系管理员。",
  embedding_unavailable: "向量服务暂时不可用，请稍后刷新状态。",
  encrypted_pdf_unsupported: "加密 PDF 暂不支持，请上传未加密文件。",
  file_too_large: "文件超过处理大小限制，请缩小或拆分后重新上传。",
  parser_failed: "文件解析失败，请刷新状态或联系管理员。",
  ingestion_retry_exhausted: "自动处理重试已用尽，请联系管理员。",
  lease_lost: "处理任务已中断并等待恢复，请稍后刷新状态。",
  no_extractable_text: "未找到可提取的文字内容，请检查文件内容。",
  object_store_unavailable: "文件存储暂时不可用，请稍后刷新状态。",
  unsupported_media_type: "文件类型不受支持，请转换格式后重新上传。",
  upload_checksum_mismatch: "上传文件校验失败，请重新上传文件。",
  archive_partial_failure: "压缩包中有部分文件处理失败。",
  upload_expired: "上传已过期，请重新上传文件。",
  upload_media_type_mismatch: "上传文件类型与声明不一致，请重新上传正确文件。",
  upload_object_missing: "找不到已上传文件，请重新上传文件。",
  upload_size_mismatch: "上传文件大小与声明不一致，请重新上传文件。",
};

function sourceLabel(sourceType: string): string {
  return sourceType === "zip_entry" ? "ZIP 内文件" : "上传文件";
}

function failureMessage(code: string | null): string | null {
  if (code === null) return null;
  return Object.hasOwn(FAILURE, code)
    ? FAILURE[code]!
    : "未知处理错误，请刷新状态或联系管理员";
}

function errorView(error: unknown) {
  if (!(error instanceof ApiError)) return {
    message: "资料详情暂时无法读取，请稍后重试", traceId: null, retryable: true,
  };
  return { message: error.message, traceId: error.traceId, retryable: error.retryable };
}

export interface KnowledgeResourceDetailsProps {
  id: string;
  organizationId: string;
  projectId: string;
  resourceId: string;
  csrfToken: string;
  canWrite: boolean;
  actionsDisabled?: boolean;
  sessionSignal: AbortSignal;
  onResourceMissing(): void | Promise<void>;
  onRetrySucceeded(resource: KnowledgeResource): void | Promise<void>;
  onDeleteSucceeded(resource: KnowledgeResource): void | Promise<void>;
}

export function KnowledgeResourceDetails(props: KnowledgeResourceDetailsProps) {
  const queryClient = useQueryClient();
  const query = useKnowledgeResourceQuery(props);
  const reported404 = useRef(false);
  const active = useRef(true);
  const operation = useRef<AbortController | null>(null);
  const operationLocked = useRef(false);
  const deleteButton = useRef<HTMLButtonElement | null>(null);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [pendingOperation, setPendingOperation] = useState<"retry" | "delete" | null>(null);
  const [operationError, setOperationError] = useState<unknown>(null);
  const [operationMissing, setOperationMissing] = useState(false);
  const [contractRecoveryRequired, setContractRecoveryRequired] = useState(false);
  const retryMutation = useMutation({
    retry: false,
    networkMode: "always",
    mutationFn: ({ versionId, signal }: { versionId: string; signal: AbortSignal }) =>
      retryKnowledgeResourceVersion({
        projectId: props.projectId,
        resourceId: props.resourceId,
        versionId,
        csrfToken: props.csrfToken,
        signal,
      }),
  });
  const deleteMutation = useMutation({
    retry: false,
    networkMode: "always",
    mutationFn: ({ signal }: { signal: AbortSignal }) => deleteKnowledgeResource({
      projectId: props.projectId,
      resourceId: props.resourceId,
      csrfToken: props.csrfToken,
      signal,
    }),
  });

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      operation.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (props.canWrite) return;
    setConfirmationOpen(false);
    operation.current?.abort();
  }, [props.canWrite]);
  useEffect(() => {
    if (!props.actionsDisabled) return;
    setConfirmationOpen(false);
  }, [props.actionsDisabled]);

  const notFound = query.error instanceof ApiError && query.error.status === 404;
  useEffect(() => {
    if (!notFound || reported404.current) return;
    reported404.current = true;
    props.onResourceMissing();
  }, [notFound, props]);

  async function refreshDetail(): Promise<void> {
    setConfirmationOpen(false);
    const result = await query.refetch();
    if (!active.current || !result.isSuccess) return;
    setContractRecoveryRequired(false);
    setOperationError(null);
  }

  if (query.fetchStatus !== "idle") return <div id={props.id} className="knowledge-resource-details" role="status">
    {query.fetchStatus === "paused" ? "网络连接恢复后将读取最新资料详情…" : "正在读取资料详情…"}
  </div>;
  if (notFound || operationMissing) return <div id={props.id} className="knowledge-resource-details" role="status">该资料已不可用，正在重新检查项目知识访问权限。</div>;
  if (query.isError) {
    const error = errorView(query.error);
    return <div id={props.id} className="knowledge-resource-details knowledge-resource-detail-error">
      <p role="alert">{error.message}</p>
      {error.traceId === null ? null : <p>请求编号：{error.traceId}</p>}
      {error.retryable ? <button type="button" onClick={() => void refreshDetail()}>重试读取资料详情</button> : null}
    </div>;
  }

  const resource = query.data;
  if (resource === undefined) return <div id={props.id} className="knowledge-resource-details" role="status">正在读取资料详情…</div>;
  const authorizedResource = resource;
  const version = resource.latestVersion;
  const failure = version === null ? null : failureMessage(version.errorCode);
  const pending = pendingOperation !== null;
  const presentedOperationError = operationError === null ? null : errorView(operationError);

  async function handleOperationError(error: unknown, refreshConflict: boolean): Promise<void> {
    if (!active.current || (error instanceof ApiError && error.kind === "aborted")) return;
    if (error instanceof ApiError && error.status === 404) {
      setOperationMissing(true);
      setConfirmationOpen(false);
      await props.onResourceMissing();
      return;
    }
    setOperationError(error);
    if (error instanceof ApiError && error.kind === "contract") {
      setContractRecoveryRequired(true);
      setConfirmationOpen(false);
    }
    if (refreshConflict && error instanceof ApiError && error.status === 409) {
      await query.refetch();
    }
  }

  async function retryVersion(): Promise<void> {
    if (
      operationLocked.current ||
      !props.canWrite ||
      props.actionsDisabled === true ||
      version?.status !== "failed" ||
      version.retryable !== true
    ) return;
    operationLocked.current = true;
    const controller = new AbortController();
    operation.current = controller;
    setPendingOperation("retry");
    setConfirmationOpen(false);
    setOperationError(null);
    const signal = AbortSignal.any([controller.signal, props.sessionSignal]);
    try {
      const updated = await retryMutation.mutateAsync({ versionId: version.id, signal });
      if (!active.current || signal.aborted || operation.current !== controller) return;
      queryClient.setQueryData(
        knowledgeKeys.resource(props.organizationId, props.projectId, props.resourceId),
        updated,
      );
      await props.onRetrySucceeded(updated);
    } catch (error) {
      await handleOperationError(error, true);
    } finally {
      if (operation.current === controller) {
        operation.current = null;
        operationLocked.current = false;
        if (active.current) setPendingOperation(null);
      }
    }
  }

  async function confirmDelete(): Promise<void> {
    if (operationLocked.current || !props.canWrite || props.actionsDisabled === true) return;
    operationLocked.current = true;
    const controller = new AbortController();
    operation.current = controller;
    setPendingOperation("delete");
    setOperationError(null);
    const signal = AbortSignal.any([controller.signal, props.sessionSignal]);
    try {
      await deleteMutation.mutateAsync({ signal });
      if (!active.current || signal.aborted || operation.current !== controller) return;
      await props.onDeleteSucceeded(authorizedResource);
    } catch (error) {
      await handleOperationError(error, false);
    } finally {
      if (operation.current === controller) {
        operation.current = null;
        operationLocked.current = false;
        if (active.current) setPendingOperation(null);
      }
    }
  }

  return <section id={props.id} className="knowledge-resource-details" aria-label={`${resource.title} 资料详情`}>
    <div className="knowledge-resource-detail-heading">
      <div><strong>{resource.title}</strong><p>状态仅在手动刷新时更新。</p></div>
      <button type="button" disabled={query.isFetching || pending} onClick={() => {
        void refreshDetail();
      }}>
        <RefreshCw aria-hidden="true" size={17} />{query.isFetching ? "正在刷新资料状态" : "刷新资料状态"}
      </button>
    </div>
    <dl className="knowledge-resource-detail-grid">
      <div><dt>来源</dt><dd>{sourceLabel(resource.sourceType)}</dd></div>
      <div><dt>创建时间</dt><dd><time dateTime={resource.createdAt}>{formatCalendarDate(resource.createdAt, DATE_TIME)}</time></dd></div>
      <div><dt>更新时间</dt><dd><time dateTime={resource.updatedAt}>{formatCalendarDate(resource.updatedAt, DATE_TIME)}</time></dd></div>
      {version === null ? <div><dt>当前状态</dt><dd>等待生成首个版本</dd></div> : <>
        <div><dt>文件类型</dt><dd>{formatKnowledgeMediaType(version.mediaType)}</dd></div>
        <div><dt>文件大小</dt><dd>{formatBytes(version.sizeBytes)}</dd></div>
        <div><dt>处理状态</dt><dd>{STATUS[version.status]}</dd></div>
        <div><dt>开始处理</dt><dd>{version.processingStartedAt === null ? "尚未开始" : <time dateTime={version.processingStartedAt}>{formatCalendarDate(version.processingStartedAt, DATE_TIME)}</time>}</dd></div>
        <div><dt>可用时间</dt><dd>{version.readyAt === null ? "尚未就绪" : <time dateTime={version.readyAt}>{formatCalendarDate(version.readyAt, DATE_TIME)}</time>}</dd></div>
      </>}
    </dl>
    {failure === null ? null : <p className="knowledge-resource-failure" role="alert">{failure}</p>}
    {version?.status === "ready" ? <a className="knowledge-resource-download"
      href={buildKnowledgeDownloadUrl(props.projectId, props.resourceId)} target="_blank"
      rel="noopener noreferrer">下载资料（在新标签页打开）</a> : null}
    {props.canWrite && props.actionsDisabled !== true ? <div className="knowledge-resource-operations">
      {contractRecoveryRequired ? null : <><div className="knowledge-resource-operation-actions">
        {version?.status === "failed" && version.retryable === true ? (
          <button type="button" disabled={pending} onClick={() => void retryVersion()}>
            {pendingOperation === "retry" ? "正在重新处理" : "重新处理失败版本"}
          </button>
        ) : null}
        <button ref={deleteButton} type="button" disabled={pending} onClick={() => {
          setOperationError(null);
          setConfirmationOpen(true);
        }}>删除资料</button>
      </div>
      {confirmationOpen ? <div className="knowledge-resource-delete-confirmation"
        role="group" aria-label="确认删除资料">
        <p><strong>确认删除“{resource.title}”？</strong></p>
        <p>该资料会从项目知识和搜索结果中移除；后端保留数据不会立即物理清除。</p>
        <div>
          <button type="button" className="danger-action" disabled={pending}
            onClick={() => void confirmDelete()}>
            {pendingOperation === "delete" ? "正在删除资料" : "确认删除资料"}
          </button>
          <button type="button" disabled={pending} onClick={() => {
            setConfirmationOpen(false);
            setOperationError(null);
            requestAnimationFrame(() => deleteButton.current?.focus());
          }}>取消删除</button>
        </div>
      </div> : null}</>}
      {presentedOperationError === null ? null : <div className="knowledge-resource-operation-error">
        <p role="alert">{presentedOperationError.message}</p>
        {presentedOperationError.traceId === null
          ? null
          : <p>请求编号：{presentedOperationError.traceId}</p>}
      </div>}
    </div> : null}
  </section>;
}
