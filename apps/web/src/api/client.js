// 通用请求层：超时、取消、错误分类只在这里写一遍。
// 页面代码永远不直接调 fetch —— 这是 Day 12「所有请求都走统一错误处理」的约束提前落地。

import { ApiError } from "./errors.js";

const BASE_URL = "http://localhost:8787";
const DEFAULT_TIMEOUT_MS = 3000;

/**
 * 发一个 JSON 请求，把底层五花八门的失败翻译成 ApiError。
 *
 * @param {string} path 相对路径，如 "/api/docs"
 * @param {object} [options]
 * @param {Record<string, string>} [options.query] 查询参数
 * @param {number} [options.timeoutMs] 客户端截止时间
 * @param {AbortSignal} [options.signal] 外部取消信号（用户点取消、组件卸载）
 * @returns {Promise<unknown>} 解析后的 JSON
 */
export async function request(path, { query, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = {}) {
  // fetch 没有原生超时。做法：自己开一个 controller，用 setTimeout 到点 abort。
  // 超时和用户取消因此走同一条路径，区别只在事后判断谁先 abort 的。
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // 外部信号的取消要转达给内部 controller。
  // 若外部信号已经是 aborted 状态，addEventListener 不会再触发，所以要先查一次。
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  const url = new URL(path, BASE_URL);
  for (const [key, value] of Object.entries(query ?? {})) {
    url.searchParams.set(key, value);
  }

  try {
    const response = await fetch(url, { signal: controller.signal });

    // 坑一：fetch 对 4xx/5xx 不 reject。服务器返回 500，上面这行照样 resolve。
    // 只有网络层挂了才会进 catch。所以 HTTP 错误必须在这里手动抛。
    if (!response.ok) {
      throw new ApiError("http", `服务器返回 ${response.status}`, response.status);
    }

    // 坑二：fetch 是两段式。上面只等到响应头，body 要再 await 一次，
    // 而 .json() 自己也可能抛（响应不是合法 JSON）。
    return await response.json();
  } catch (error) {
    throw toApiError(error, { timeoutMs, externalSignal: signal });
  } finally {
    // 成功、失败、取消都要清定时器，否则它还会在 timeoutMs 后 abort 一个已结束的请求。
    clearTimeout(timer);
  }
}

/** 把原生错误归一成 ApiError。抽成函数是为了能单独测。 */
function toApiError(error, { timeoutMs, externalSignal }) {
  if (error instanceof ApiError) return error; // 上面手动抛的 http 错误，原样透传

  if (error.name === "AbortError") {
    // abort 有两个来源：我们的超时定时器，或外部取消。
    // 外部取消时 externalSignal.aborted 为 true —— 这是区分二者的唯一依据。
    return externalSignal?.aborted
      ? new ApiError("aborted", "请求已被取消")
      : new ApiError("timeout", `请求超过 ${timeoutMs}ms 未响应`);
  }

  if (error instanceof SyntaxError) {
    // .json() 解析失败：服务器返回了 200 但 body 不是 JSON（常见于网关吐 HTML 错误页）
    return new ApiError("http", "服务器返回了无法解析的内容");
  }

  // 剩下的（TypeError: Failed to fetch）是真·网络失败：断网、DNS、服务器没起
  return new ApiError("network", "无法连接服务器，请检查网络");
}
