// 文档面板。整个应用里唯一消费 documentStore 的组件。
//
// "唯一"是刻意的：状态订阅集中在一处，子组件全是纯展示（props 进、UI 出）。
// 好处是子组件能被单独测试和复用，且看一眼这个文件就知道数据从哪来。
// 反过来的做法——每个子组件自己 useDocumentState()——会让"谁依赖了服务端状态"
// 散落在整棵树里，重构时得逐个文件找。

import { useMemo, useState } from "react";

import { DocumentList } from "./DocumentList.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { UploadZone } from "./UploadZone.tsx";
import { toApiError } from "../api/errors.ts";
import { countByStatus, filterByStatus, statusLabel } from "../lib/documents.ts";
import type { DocumentLoadState } from "../lib/statusText.ts";
import { useDocumentsQuery } from "../queries/documents.ts";
import { DOCUMENT_STATUSES, type DocumentStatus } from "../schemas/documents.ts";
import type { ResourceId } from "../schemas/primitives.ts";

const SCENARIOS = [
  { value: "success", label: "成功（有数据）" },
  { value: "empty", label: "成功（空数据）" },
  { value: "error", label: "HTTP 500 错误" },
  { value: "slow", label: "慢响应（触发 3s 超时）" },
] as const;

/** 状态筛选的选项。"all" 是哨兵值，不是真实状态（见 lib/documents.ts）。 */
type StatusFilter = DocumentStatus | "all";

export function DocumentsPanel({ userId }: { userId: ResourceId }) {
  // 场景选择器：迁到 React 后必须变成受控 state。
  // 旧的 main.ts 是在点击时读 elements.scenario.value——让 DOM 自己记着状态。
  // 那样能跑，但它意味着有两处状态真相（React 树 + DOM 节点），
  // 而 React 重渲染时不保证保留未受控节点的值。这是"UI 是 state 的函数"
  // 这条原则的实际约束：想让 React 管渲染，就不能有它不知道的状态。
  const [scenario, setScenario] = useState<string>("success");
  const query = useDocumentsQuery(userId, scenario);

  // Day 9：状态筛选。
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const loadState: DocumentLoadState = query.isFetching
    ? { phase: "loading" }
    : query.isError
      ? { phase: "error", error: toApiError(query.error) }
      : query.isSuccess
        ? { phase: "success", ...query.data }
        : { phase: "idle" };

  const isLoading = loadState.phase === "loading";

  // documents 只存在于 success 态（Day 7 可辨识联合的结果）。
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
  // 等数据量真的上来（Day 24 检索结果分页、上千条文档），这个结构不用改，
  // 只是那时 memo 才真的开始省时间。而**性能优化的决定必须在测量之后**——
  // 这里没测量，所以不拿性能当理由。
  // ---------------------------------------------------------------------------

  const visibleDocuments = useMemo(
    () => filterByStatus(documents, statusFilter),
    [documents, statusFilter],
  );

  // countByStatus 是 Day 6 写的，至今**没有 UI 消费者**——今天是它第一次被用上。
  // 注意它统计的是 documents（全部），不是 visibleDocuments（筛选后）：
  // 角标要显示"处理中 1"而不是"当前筛选下处理中 0"，否则筛到 completed 之后
  // 其他角标全变成 0，用户就没法用角标判断该切到哪个筛选了。
  const counts = useMemo(() => countByStatus(documents), [documents]);

  return (
    <section className="documents-panel" aria-labelledby="documents-title">
      <h1 id="documents-title">知识文档</h1>
      <p>管理用于企业问答的内部资料。</p>

      <div className="documents-controls">
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

        {/*
          两个按钮的 disabled 都从 state.phase 算出来，不再手动赋值。
          这就是声明式的差别：旧代码在订阅回调里写 `load.disabled = phase === "loading"`——
          一个必须在每次状态变化时被正确执行的**指令**，漏掉一处就出现
          "加载完了按钮还是灰的"。现在它是一个**描述**，phase 是什么，按钮就是什么，
          没有"忘了更新"这种失败模式。
        */}
        <button
          id="load-btn"
          type="button"
          disabled={isLoading}
          onClick={() => void query.refetch()}
        >
          加载文档
        </button>
        <button
          id="cancel-btn"
          type="button"
          disabled={!isLoading}
          onClick={() => void query.cancel()}
        >
          取消
        </button>
      </div>

      <StatusBar state={loadState} />

      {/*
        Day 9：状态筛选器。只在真的有文档时出现——
        0 个文档时显示一排"已就绪 0 / 处理中 0"的按钮是在给用户提供
        一个点了什么都不会变的控件。

        用 radio 而不是 button 组：这是一组互斥选项，radiogroup 的语义
        让读屏用户听到"3 之 1 项已选中"，知道总共有几个选择、自己在哪个。
        一排 button 只能听到"按钮 已就绪"，看不出这是单选。
        视觉上 CSS 会把它画成按钮样子——语义和外观是两件事。
      */}
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
              {/* "all" 没有对应的 statusLabel（它不是真状态），单独给文案 */}
              {value === "all" ? `全部 ${documents.length}` : `${statusLabel(value)} ${counts[value] ?? 0}`}
            </label>
          ))}
        </fieldset>
      )}

      <DocumentList documents={visibleDocuments} />

      {/*
        筛选后为空的情况要单独说。
        直接显示一个空列表会让用户以为文档丢了——而真相是他自己筛掉了所有。
        这条和 lib/statusText.ts 里"空数据给引导而不是报错"是同一个判断：
        沉默地少显示数据是最难被发现的一类问题。
      */}
      {documents.length > 0 && visibleDocuments.length === 0 && (
        <p className="document-list-empty" role="status">
          当前筛选下没有文档。切到「全部 {documents.length}」看所有。
        </p>
      )}

      <UploadZone />
    </section>
  );
}
