// 文档加载的状态机。
// 一次请求不是「加载中/完成」两态。这里是六态：
//   idle → loading → success(有数据) | success(空数据) | error(network/http/timeout) | 回 idle(用户取消)
// 状态集中在一处，UI 只订阅变化后重画，数据单向流动。

import { fetchDocuments } from "../api/documents.js";
import { ApiError } from "../api/errors.js";

/** @typedef {"idle" | "loading" | "success" | "error"} Phase */

export function createDocumentStore() {
  let state = { phase: /** @type {Phase} */ ("idle"), documents: [], error: null };
  const listeners = new Set();

  // 当前在飞的请求。发新请求前取消旧的，避免慢响应后到、覆盖掉新结果（陈旧响应竞态）。
  let inFlight = null;

  function setState(next) {
    state = { ...state, ...next };
    for (const listener of listeners) listener(state);
  }

  return {
    getState: () => state,

    subscribe(listener) {
      listeners.add(listener);
      listener(state); // 订阅即拿到当前状态，省掉调用方手动首次渲染
      return () => listeners.delete(listener);
    },

    /** @param {{ scenario?: string }} [options] */
    async load({ scenario } = {}) {
      if (inFlight) inFlight.abort();

      const controller = new AbortController();
      inFlight = controller;

      setState({ phase: "loading", error: null });

      try {
        const documents = await fetchDocuments({ scenario, signal: controller.signal });
        setState({ phase: "success", documents, error: null });
      } catch (error) {
        // 用户主动取消不是错误：回 idle，不弹红条。
        if (error instanceof ApiError && error.kind === "aborted") {
          setState({ phase: "idle", documents: [], error: null });
        } else {
          setState({
            phase: "error",
            documents: [],
            error: error instanceof ApiError
              ? error
              : new ApiError("network", error.message ?? "未知错误"),
          });
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
