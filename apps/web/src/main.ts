// 应用入口：只做三件事——拿 DOM、把 store 和 UI 接起来、绑事件。
// 这里不该出现任何业务逻辑或 fetch 调用；一旦出现，说明该往下分层了。

import { createDocumentStore } from "./state/documentStore.ts";
import { renderDocumentList } from "./ui/documentList.ts";
import { renderStatusBar } from "./ui/statusBar.ts";

/**
 * 按 id 取元素，取不到就抛错。
 *
 * 为什么需要它：getElementById 的返回类型是 `HTMLElement | null`，
 * 因为编译器无法知道 HTML 里有没有这个 id。TS 迁移到入口文件时，
 * 这是必然撞上的一堵墙 —— 原来的 JS 版本对每个元素都隐含假设了"它一定存在"。
 *
 * 处理方式有三种，选第三种：
 *   1. `!` 非空断言 —— 骗编译器，id 拼错时仍然在运行时炸，只是炸在更远的地方。
 *   2. 每次用前判空 —— 五个元素每个都判，噪音淹没真正的逻辑，而且判空之后
 *      "元素不存在"这个分支要写点什么？没有合理的降级行为。
 *   3. 启动时集中断言（这里）—— 缺元素说明 HTML 和 JS 不匹配，这是构建期的错误，
 *      应当立刻、响亮地失败，而不是让页面半死不活地显示一部分。
 *
 * 泛型参数让调用方指定具体元素类型：select 要读 .value，button 要写 .disabled，
 * 光有 HTMLElement 拿不到这些属性。
 */
function requireElement<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) {
    throw new Error(`页面缺少必需的元素 #${id}：HTML 与脚本不匹配`);
  }
  return element as T;
}

const elements = {
  scenario: requireElement<HTMLSelectElement>("scenario"),
  load: requireElement<HTMLButtonElement>("load-btn"),
  cancel: requireElement<HTMLButtonElement>("cancel-btn"),
  statusBar: requireElement<HTMLParagraphElement>("status-bar"),
  list: requireElement<HTMLUListElement>("document-list"),
};

const store = createDocumentStore();

// 单一订阅：状态一变就整体重画。
// 原生 DOM 下这样做够用且不会漏更新；Day 8 React 接管后，这正是它替你做的事。
store.subscribe((state) => {
  renderStatusBar(elements.statusBar, state);

  // documents 只存在于 success 态（Day 7 把 state 改成可辨识联合的结果）。
  // 其余状态一律清空列表 —— 这个判断以前散在 store 里（每个分支都写 documents: []），
  // 现在集中在 UI 层，因为"出错时列表显示什么"本来就是展示决策。
  renderDocumentList(elements.list, state.phase === "success" ? state.documents : []);

  elements.load.disabled = state.phase === "loading";
  elements.cancel.disabled = state.phase !== "loading";
});

elements.load.addEventListener("click", () => {
  void store.load({ scenario: elements.scenario.value });
});

elements.cancel.addEventListener("click", () => store.cancel());
