// 应用入口：只做三件事——拿 DOM、把 store 和 UI 接起来、绑事件。
// 这里不该出现任何业务逻辑或 fetch 调用；一旦出现，说明该往下分层了。

import { createDocumentStore } from "./state/documentStore.js";
import { renderDocumentList } from "./ui/documentList.js";
import { renderStatusBar } from "./ui/statusBar.js";

const elements = {
  scenario: document.getElementById("scenario"),
  load: document.getElementById("load-btn"),
  cancel: document.getElementById("cancel-btn"),
  statusBar: document.getElementById("status-bar"),
  list: document.getElementById("document-list"),
};

const store = createDocumentStore();

// 单一订阅：状态一变就整体重画。
// 原生 DOM 下这样做够用且不会漏更新；Day 8 React 接管后，这正是它替你做的事。
store.subscribe((state) => {
  renderStatusBar(elements.statusBar, state);
  renderDocumentList(elements.list, state.documents);

  elements.load.disabled = state.phase === "loading";
  elements.cancel.disabled = state.phase !== "loading";
});

elements.load.addEventListener("click", () => {
  store.load({ scenario: elements.scenario.value });
});

elements.cancel.addEventListener("click", () => store.cancel());
