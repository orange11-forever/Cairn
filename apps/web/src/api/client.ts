// 通用请求层：超时、取消、错误分类只在这里写一遍。
// 页面代码永远不直接调 fetch，所有请求都走统一错误处理。

import { ApiError } from "./errors.ts";
import {
  parseApiErrorResponse,
  type ParsedApiErrorResponse,
} from "../schemas/apiError.ts";

/**
 * 后端地址。**从环境变量读，不写死。**
 *
 * 这是私有部署的硬性要求，不是洁癖：客户会用他们自己的域名
 *（`https://kb.某公司内网.local`），而我们不可能提前知道那是什么。
 * 同一份代码要能跑在三种环境下而一行不改：
 *   本地开发    http://localhost:8787
 *   演示环境    https://demo.example.com/api
 *   客户内网    https://kb.customer.local/api
 *
 * 用 `import.meta.env` 而不是 `process.env`：浏览器里没有 `process` 这个对象。
 * Vite 在**构建时**把 `import.meta.env.VITE_*` 替换成字面量字符串——
 * 所以这个值是编译进产物的，不是运行时读的。
 *
 * 两个由此而来的后果，都要知道：
 *
 * 1. **只有 `VITE_` 前缀的变量会被注入。** 这是 Vite 的安全设计——
 *    否则服务器上的 `DATABASE_PASSWORD` 之类会被打进前端产物发给浏览器。
 *    换句话说：能出现在这里的值，都是公开的。别把密钥放进 VITE_ 变量。
 *
 * 2. **改了它要重新构建**，不是重启就行。客户换域名需要重新 build。
 *    若部署需要运行时改配置，应由启动时注入的配置端点解决。
 */
const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8787";

const DEFAULT_TIMEOUT_MS = 3000;

export interface RequestOptions {
  query?: Record<string, string>;
  /** 客户端截止时间。 */
  timeoutMs?: number;
  /** 外部取消信号（用户点取消、组件卸载）。 */
  signal?: AbortSignal;

  /**
   * HTTP 方法。默认 GET。
   *
   * 收窄成联合而不是 string：写成 "PSOT" 会在编译期被拦下，
   * 而 string 只会让服务器返回 405，排查时先怀疑的是后端路由。
   */
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

  /**
   * 请求体。传普通对象，这一层负责 JSON.stringify 和 Content-Type。
   *
   * 类型是 unknown 而不是泛型或 Record：调用方传什么形状是它自己的契约，
   * 这一层只管序列化。收窄成 Record<string, unknown> 会拒掉合法的数组体。
   */
  body?: unknown;
}

/**
 * 发一个 JSON 请求，把底层五花八门的失败翻译成 ApiError。
 *
 * 返回 Promise<unknown> 而不是泛型 Promise<T>：
 * 这一层**没有**任何依据知道响应是什么形状。写成 `request<Document[]>()` 会让调用方
 * 以为拿到的是 Document[]，而实际上那只是一句没人验证过的断言 —— 等价于 any，
 * 只是伪装得更体面。收窄类型是 schemas/ 层的活，它有 schema 作为证据。
 */
export async function request(
  path: string,
  {
    query,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal,
    method = "GET",
    body,
  }: RequestOptions = {},
): Promise<unknown> {
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

  // context 带上方法：错误日志里只写 "/api/uploads" 分不清是列表查询还是上传，
  // 而这两条路径的故障原因完全不同。
  const context = `${method} ${path}`;

  try {
    const response = await fetch(url, {
      method,
      signal: controller.signal,
      // Content-Type 只在真有 body 时才发。
      // 给 GET 加这个头会让浏览器对跨域请求发一次 preflight（OPTIONS），
      // 平白多一个往返，而且 mock 后端不处理 OPTIONS 时会直接 404——
      // 表现出来是"GET 突然连不上了"，很难联想到是一个多余的请求头。
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      // undefined 而不是 null：fetch 对 body: null 的处理是"空 body"，
      // 对 GET/HEAD 来说带 body 本身就是非法的，会抛 TypeError。
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    // 坑一：fetch 对 4xx/5xx 不 reject。服务器返回 500，上面这行照样 resolve。
    // 只有网络层挂了才会进 catch。所以 HTTP 错误必须在这里手动抛。
    if (!response.ok) {
      // 错误响应体里可能有后端给的具体原因，比"服务器返回 500"有用。
      // 但读它本身可能失败（body 是 HTML 错误页 / 空 body），所以整个包在 catch 里：
      // 错误处理路径不能成为新的失败源。
      let detail: ParsedApiErrorResponse = {
        message: `服务器返回 ${response.status}`,
        code: "http_error",
        traceId: response.headers.get("X-Request-ID"),
      };
      try {
        detail = parseApiErrorResponse(await response.json(), detail);
      } catch {
        // body 不是 JSON，用默认文案。这不是问题，网关经常这样。
      }
      throw new ApiError("http", detail.message, {
        status: response.status,
        code: detail.code,
        traceId: detail.traceId,
        context,
      });
    }

    // 坑二：fetch 是两段式。上面只等到响应头，body 要再 await 一次，
    // 而 .json() 自己也可能抛（响应不是合法 JSON）。
    return await response.json();
  } catch (error) {
    throw toApiError(error, { timeoutMs, externalSignal: signal, context });
  } finally {
    // 成功、失败、取消都要清定时器，否则它还会在 timeoutMs 后 abort 一个已结束的请求。
    clearTimeout(timer);
  }
}

/** 把原生错误归一成 ApiError。抽成函数是为了能单独测。 */
function toApiError(
  error: unknown,
  {
    timeoutMs,
    externalSignal,
    context,
  }: { timeoutMs: number; externalSignal?: AbortSignal; context: string },
): ApiError {
  // 上面手动抛的 http 错误、以及校验层抛的 contract 错误，原样透传
  if (error instanceof ApiError) return error;

  // 改进一：原来写的是 `error.name === "AbortError"`。
  // TS 拦下来了 —— catch 到的是 unknown，可能是字符串、可能是 null，读 .name 会炸。
  // 这不是理论风险：`throw null` 在第三方库里真实存在，一旦发生，
  // 原来的代码会在错误处理里抛出第二个错误（TypeError: cannot read .name of null），
  // 真实故障原因就此丢失。
  if (error instanceof Error && error.name === "AbortError") {
    // abort 有两个来源：我们的超时定时器，或外部取消。
    // 外部取消时 externalSignal.aborted 为 true —— 这是区分二者的唯一依据。
    return externalSignal?.aborted
      ? new ApiError("aborted", "请求已被取消", { context })
      : new ApiError("timeout", `请求超过 ${timeoutMs}ms 未响应`, { context });
  }

  if (error instanceof SyntaxError) {
    // .json() 解析失败：服务器返回了 200 但 body 不是 JSON（常见于网关吐 HTML 错误页）
    return new ApiError("http", "服务器返回了无法解析的内容", { context, cause: error });
  }

  // 剩下的（TypeError: Failed to fetch）是真·网络失败：断网、DNS、服务器没起
  return new ApiError("network", "无法连接服务器，请检查网络", { context, cause: error });
}
