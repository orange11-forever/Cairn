// 文档面板集中消费用户级查询，子组件保持纯展示（props 进、UI 出）。

import { useMemo, useState } from "react";
import type { ResourceId } from "@cairn/contracts";
import { RefreshCw, Square } from "lucide-react";

import { DocumentList } from "./DocumentList.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { UploadZone } from "./UploadZone.tsx";
import { WorkspaceHeader } from "./WorkspaceHeader.tsx";
import { WorkspaceStatus } from "./WorkspaceStatus.tsx";
import type { WorkspaceStatusProps } from "./WorkspaceStatus.tsx";
import { toApiError } from "../api/errors.ts";
import { countByStatus, filterByStatus, statusLabel } from "../lib/documents.ts";
import type { DocumentLoadState } from "../lib/statusText.ts";
import { useDocumentsQuery } from "../queries/documents.ts";
import { DOCUMENT_STATUSES, type DocumentStatus } from "../schemas/documents.ts";

const SCENARIOS = [
  { value: "success", label: "成功（有数据）" },
  { value: "empty", label: "成功（空数据）" },
  { value: "error", label: "HTTP 500 错误" },
  { value: "slow", label: "慢响应（触发 3s 超时）" },
] as const;

/** 状态筛选的选项。"all" 是哨兵值，不是真实状态（见 lib/documents.ts）。 */
type StatusFilter = DocumentStatus | "all";

function getWorkspaceStatus(
  loadState: DocumentLoadState,
  onRetry: () => void,
): Omit<WorkspaceStatusProps, "mascot"> {
  switch (loadState.phase) {
    case "loading":
      return {
        state: "loading",
        title: "正在整理资料",
        description: "文档状态同步完成后，我会提示你哪些资料可以用于问答。",
      };
    case "error":
      return {
        state: "error",
        title: "暂时无法读取资料",
        description:
          loadState.error.kind === "contract"
            ? "返回的数据暂时无法识别，请联系管理员检查资料服务。"
            : "上传入口仍然可用，也可以重新加载现有文档。",
        action:
          loadState.error.kind === "contract" ? undefined : (
            <button type="button" onClick={onRetry}>
              <RefreshCw aria-hidden="true" size={16} strokeWidth={1.8} />
              再次加载
            </button>
          ),
      };
    case "success":
      return loadState.documents.length > 0
        ? {
            state: "success",
            title: "资料已就绪",
            description: "已加载的资料可以继续筛选；处理中的文档会在完成后进入问答。",
          }
        : {
            state: "empty",
            title: "建立知识空间",
            description: "从下方上传第一份团队资料，我会陪你确认处理进度。",
          };
    case "idle":
      return {
        state: "empty",
        title: "从资料清单开始",
        description: "加载已有文档，或直接上传新的团队资料。",
      };
  }
}

export function DocumentsPanel({
  userId,
  parentSignal,
}: {
  userId: ResourceId;
  parentSignal?: AbortSignal;
}) {
  // 场景选择器：迁到 React 后必须变成受控 state。
  // 旧的 main.ts 是在点击时读 elements.scenario.value——让 DOM 自己记着状态。
  // 那样能跑，但它意味着有两处状态真相（React 树 + DOM 节点），
  // 而 React 重渲染时不保证保留未受控节点的值。这是"UI 是 state 的函数"
  // 这条原则的实际约束：想让 React 管渲染，就不能有它不知道的状态。
  const [scenario, setScenario] = useState<string>("success");
  const query = useDocumentsQuery(userId, scenario);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const loadState: DocumentLoadState = query.isFetching
    ? { phase: "loading" }
    : query.isError
      ? { phase: "error", error: toApiError(query.error) }
      : query.isSuccess
        ? { phase: "success", ...query.data }
        : { phase: "idle" };

  const isLoading = loadState.phase === "loading";

  // documents 只存在于 success 态。
  // 其余状态一律空数组——"出错时列表显示什么"是展示决策，所以这个判断属于 UI 层。
  const documents = loadState.phase === "success" ? loadState.documents : [];

  // ---------------------------------------------------------------------------
  // useMemo：派生数据。这是本日 useMemo 的唯一用处，理由要说清楚。
  //
  // **不是性能。** 4 条数据下 filter 和一次遍历计数省下的时间是零，
  // 而 useMemo 自己要存依赖、比较依赖、存结果，那些开销并不是免费的。
  // 在这个规模上，包 memo 大概比不包还慢一点。
  //
  // 包它的理由是它是「派生数据」的**正确形状**——先把这个习惯建立起来：
  //   派生值从 state 算出来，不存进 state。
  //
  // 对照那个错误形状（本日「不该用 Effect」的第一号样本）：
  //   const [visible, setVisible] = useState([]);
  //   useEffect(() => { setVisible(filterByStatus(documents, filter)) },
  //             [documents, filter]);
  // 它有三个具体问题：
  //   1. 渲染两遍。第一遍 visible 还是旧的，用户能看到一帧过期的列表。
  //   2. visible 成了第二份真相，而它完全可以从 documents + filter 算出来。
  //   3. 依赖数组漏一个就静默失效——筛选器点了没反应，且不报任何错。
  //
  // 数据量增长到分页或上千条文档时，这个结构不用改，
  // 只是那时 memo 才真的开始省时间。而**性能优化的决定必须在测量之后**——
  // 这里没测量，所以不拿性能当理由。
  // ---------------------------------------------------------------------------

  const visibleDocuments = useMemo(
    () => filterByStatus(documents, statusFilter),
    [documents, statusFilter],
  );

  // countByStatus 统计的是 documents（全部），不是 visibleDocuments（筛选后）：
  // 角标要显示"处理中 1"而不是"当前筛选下处理中 0"，否则筛到 completed 之后
  // 其他角标全变成 0，用户就没法用角标判断该切到哪个筛选了。
  const counts = useMemo(() => countByStatus(documents), [documents]);

  const workspaceStatus = getWorkspaceStatus(loadState, () => void query.refetch());

  return (
    <section className="documents-panel" aria-labelledby="documents-title">
      <WorkspaceHeader
        id="documents-title"
        title="知识文档"
        description="管理用于企业问答的内部资料。"
      />

      {import.meta.env.DEV && (
        <div className="documents-dev-toolbar" data-dev-only="true">
          <span>开发预览</span>
          <div>
            <label htmlFor="scenario">模拟场景</label>
            <select
              id="scenario"
              value={scenario}
              onChange={(event) => setScenario(event.target.value)}
            >
              {SCENARIOS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      <div className="documents-workbench">
        <div className="documents-primary">
          <div className="documents-controls">
            <button
              id="load-btn"
              type="button"
              disabled={isLoading}
              onClick={() => void query.refetch()}
            >
              <RefreshCw aria-hidden="true" size={16} strokeWidth={1.8} />
              加载文档
            </button>
            <button
              id="cancel-btn"
              type="button"
              disabled={!isLoading}
              onClick={() => void query.cancel()}
            >
              <Square aria-hidden="true" size={15} strokeWidth={1.8} />
              取消
            </button>
          </div>

          <StatusBar state={loadState} />

          {documents.length > 0 && (
            <fieldset className="status-filter">
              <legend>按状态筛选</legend>
              {(["all", ...DOCUMENT_STATUSES] as const).map((value) => (
                <label key={value} className="status-filter-option">
                  <input
                    type="radio"
                    name="status-filter"
                    value={value}
                    checked={statusFilter === value}
                    onChange={() => setStatusFilter(value)}
                  />
                  {value === "all"
                    ? `全部 ${documents.length}`
                    : `${statusLabel(value)} ${counts[value] ?? 0}`}
                </label>
              ))}
            </fieldset>
          )}

          <DocumentList documents={visibleDocuments} />

          {documents.length > 0 && visibleDocuments.length === 0 && (
            <p className="document-list-empty" role="status" aria-label="筛选结果">
              当前筛选下没有文档。切到「全部 {documents.length}」看所有。
            </p>
          )}
        </div>

        <aside className="documents-secondary" aria-label="工作区提示">
          <WorkspaceStatus
            {...workspaceStatus}
            mascot={{ label: "岑宁，Cairn 知识向导", variant: "half" }}
          />
          <UploadZone parentSignal={parentSignal} />
        </aside>
      </div>
    </section>
  );
}
