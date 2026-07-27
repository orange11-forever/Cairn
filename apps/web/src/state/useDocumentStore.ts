// documentStore 通往 React 的桥。
//
// documentStore.ts 一行没改。它是一个普通的观察者模式实现（getState + subscribe），
// 早于 React 存在，也不知道 React 存在——这正是 Day 5 分层想要的效果：
// 状态机不该知道谁在渲染它。
//
// React 提供了专门接这种"外部 store"的钩子：useSyncExternalStore。
// 不用 useState + useEffect 手动同步的理由：
//   手写版本在并发渲染下会撕裂（tearing）——同一次渲染里两个组件读到不同版本的状态，
//   因为 useEffect 是渲染后才跑的，订阅建立前状态可能已经变了。
//   useSyncExternalStore 由 React 内部保证读取一致，这是它存在的全部意义。

import { useSyncExternalStore } from "react";

import { createDocumentStore } from "./documentStore.ts";
import type { DocumentState, DocumentStore } from "./documentStore.ts";

/**
 * 模块级单例。
 *
 * 必须在模块级创建，不能写在组件体里：
 *   function DocumentsPanel() {
 *     const store = createDocumentStore();   // ✗ 每次渲染造一个新 store
 *   }
 * 那样每次重渲染都会得到一个全新的空 store，状态永远回到 idle；
 * 配合 subscribe 还可能形成"订阅新 store → 触发渲染 → 又造新 store"的死循环。
 *
 * 单例也意味着状态是应用级的：将来若要同一页面开两个独立的文档面板，
 * 这里要改成 createDocumentStore() + Context。今天只有一个面板，不需要。
 */
export const documentStore: DocumentStore = createDocumentStore();

/**
 * 订阅 store，返回当前状态。状态变化时组件自动重渲染。
 *
 * 第二个参数（getSnapshot）有个硬性要求：**状态没变时必须返回同一个引用**。
 * 如果每次调用都返回一个新对象，React 会认为状态一直在变，陷入无限重渲染。
 *
 * documentStore 恰好满足：它的 setState 是整体替换（`state = next`），
 * 状态不变时 getState() 返回的就是同一个对象。而这个决定当初是为
 * "可辨识联合不能用 {...state, ...next} 合并"做的（见 documentStore.ts 的注释）——
 * 一个为类型正确性做的选择，在这里意外地满足了一个完全无关的运行时要求。
 */
export function useDocumentState(): DocumentState {
  return useSyncExternalStore(documentStore.subscribe, documentStore.getState);
}
