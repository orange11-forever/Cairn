// 文档面板。整个应用里唯一消费 documentStore 的组件。
//
// "唯一"是刻意的：状态订阅集中在一处，子组件全是纯展示（props 进、UI 出）。
// 好处是子组件能被单独测试和复用，且看一眼这个文件就知道数据从哪来。
// 反过来的做法——每个子组件自己 useDocumentState()——会让"谁依赖了服务端状态"
// 散落在整棵树里，重构时得逐个文件找。

import { useState } from "react";

import { DocumentList } from "./DocumentList.tsx";
import { StatusBar } from "./StatusBar.tsx";
import { UploadZone } from "./UploadZone.tsx";
import { documentStore, useDocumentState } from "../state/useDocumentStore.ts";

const SCENARIOS = [
  { value: "success", label: "成功（有数据）" },
  { value: "empty", label: "成功（空数据）" },
  { value: "error", label: "HTTP 500 错误" },
  { value: "slow", label: "慢响应（触发 3s 超时）" },
] as const;

export function DocumentsPanel() {
  const state = useDocumentState();

  // 场景选择器：迁到 React 后必须变成受控 state。
  // 旧的 main.ts 是在点击时读 elements.scenario.value——让 DOM 自己记着状态。
  // 那样能跑，但它意味着有两处状态真相（React 树 + DOM 节点），
  // 而 React 重渲染时不保证保留未受控节点的值。这是"UI 是 state 的函数"
  // 这条原则的实际约束：想让 React 管渲染，就不能有它不知道的状态。
  const [scenario, setScenario] = useState<string>("success");

  const isLoading = state.phase === "loading";

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
          onClick={() => void documentStore.load({ scenario })}
        >
          加载文档
        </button>
        <button
          id="cancel-btn"
          type="button"
          disabled={!isLoading}
          onClick={() => documentStore.cancel()}
        >
          取消
        </button>
      </div>

      <StatusBar state={state} />

      {/*
        documents 只存在于 success 态（Day 7 可辨识联合的结果）。
        其余状态一律传空数组——"出错时列表显示什么"是展示决策，
        所以这个三元判断属于 UI 层，不属于 store。
      */}
      <DocumentList documents={state.phase === "success" ? state.documents : []} />

      <UploadZone />
    </section>
  );
}
