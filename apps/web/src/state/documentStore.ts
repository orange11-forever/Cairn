// 文档加载的状态机。
// 一次请求不是「加载中/完成」两态。这里是六态：
//   idle → loading → success(有数据) | success(空数据) | error(network/http/timeout/contract) | 回 idle(用户取消)
// 状态集中在一处，UI 只订阅变化后重画，数据单向流动。
//
// Day 7 从 .js 迁到 .ts，并把 state 改成**可辨识联合**。
// 原来的形状是 `{ phase, documents, error }` —— 一个对象带三个总是存在的字段，
// 于是类型允许这些组合存在：
//   { phase: "loading", error: someError }   加载中却带着错误
//   { phase: "error", error: null }          出错了却没有错误对象
//   { phase: "success", documents: [] }      和"空数据"无法区分于"出错后被清空"
// 这些组合后端不会产生、UI 也不该处理，但类型允许它们，于是 UI 得到处判空
//（statusBar 里那句 `if (!error) return "发生未知错误"` 就是为此存在的死代码）。
//
// 改成联合之后，`phase === "error"` 的分支里 error 必然存在，编译器自己知道。

import { fetchDocuments } from "../api/documents.ts";
import { ApiError, toApiError } from "../api/errors.ts";
import type { Document } from "../schemas/documents.ts";

/**
 * 状态的可辨识联合。判别字段是 phase。
 *
 * 注意 documents 只出现在 success 里。这是刻意的：
 * "出错时列表该显示什么"是个产品决策，把 documents 放进 error 态就等于
 * 让每个 UI 组件各自决定要不要显示旧数据 —— 结果必然不一致。
 * 不放，UI 就只有一个选择：清空。想改成"保留旧数据"时，改的是这里的类型，
 * 编译器会把所有需要跟着改的地方列出来。
 */
export type DocumentState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "success"; documents: Document[]; dropped: number }
  | { phase: "error"; error: ApiError };

export type Listener = (state: DocumentState) => void;

export interface LoadOptions {
  scenario?: string;
}

export interface DocumentStore {
  getState(): DocumentState;
  subscribe(listener: Listener): () => void;
  load(options?: LoadOptions): Promise<void>;
  cancel(): void;
}

export function createDocumentStore(): DocumentStore {
  let state: DocumentState = { phase: "idle" };
  const listeners = new Set<Listener>();

  // 当前在飞的请求。发新请求前取消旧的，避免慢响应后到、覆盖掉新结果（陈旧响应竞态）。
  let inFlight: AbortController | null = null;

  /**
   * 整体替换而不是 `{ ...state, ...next }` 合并。
   *
   * 合并在可辨识联合下是错的：从 success 合并进 `{phase:"loading"}` 会留下
   * 上一次的 documents 字段，得到一个 `{phase:"loading", documents:[...]}` ——
   * 这个形状不在联合里，但运行时真的存在。类型说它不可能，实际它就在内存里，
   * 这种"类型和现实脱节"比没有类型更危险。
   */
  function setState(next: DocumentState): void {
    state = next;
    for (const listener of listeners) listener(state);
  }

  return {
    getState: () => state,

    subscribe(listener) {
      listeners.add(listener);
      listener(state); // 订阅即拿到当前状态，省掉调用方手动首次渲染
      return () => listeners.delete(listener);
    },

    async load({ scenario }: LoadOptions = {}) {
      if (inFlight) inFlight.abort();

      const controller = new AbortController();
      inFlight = controller;

      setState({ phase: "loading" });

      try {
        const { documents, dropped } = await fetchDocuments({
          scenario,
          signal: controller.signal,
        });
        setState({ phase: "success", documents, dropped });
      } catch (error) {
        // 用户主动取消不是错误：回 idle，不弹红条。
        if (error instanceof ApiError && error.kind === "aborted") {
          setState({ phase: "idle" });
        } else {
          // toApiError 处理 unknown。原来这里写的是 `error.message ?? "未知错误"`，
          // 在 TS 下过不去 —— catch 到的是 unknown。它在 JS 里能跑只是因为
          // 运行时碰巧 throw 的都是 Error 实例，那是运气不是保证。
          setState({ phase: "error", error: toApiError(error) });
        }
      } finally {
        // 只有仍是自己那次请求时才清，否则会把后一次请求的 controller 误清掉
        if (inFlight === controller) inFlight = null;
      }
    },

    cancel() {
      if (inFlight) inFlight.abort();
    },
  };
}
