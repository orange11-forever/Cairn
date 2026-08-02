// 统一错误模型。
// 整个前端只认这一种错误类型，调用方靠 kind 决定给用户什么反馈。
// Day 12 会把它接进正式请求层，Day 25 还要把后端 LLM Provider 的错误映射进这几类。
//
// Day 7 从 .js 迁到 .ts，并新增 "contract" 这一类，理由见下。

/**
 * 错误种类。决定 UI 文案和是否可重试。
 *
 * Day 7 新增 "contract"：数据校验失败。
 *
 * 为什么不复用 "http"：两者的处置方式完全相反。
 *   http 500  → 后端临时故障，重试有意义，用户等一会儿再点。
 *   contract  → 请求成功了（200），但响应体不符合契约。这是**代码 bug**
 *               （前后端版本不匹配、字段改名没同步），重试一万次结果一样。
 * 给用户显示"请稍后重试"是误导，它永远不会好。这两种情况必须能被分开处理，
 * 所以要有自己的 kind。
 */
export type ErrorKind = "network" | "http" | "timeout" | "aborted" | "contract";

export interface ApiErrorOptions {
  status?: number | null;
  code?: string | null;
  traceId?: string | null;
  context?: string | null;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly kind: ErrorKind;

  /** 仅 kind === "http" 时有值。 */
  readonly status: number | null;

  readonly code: string | null;
  readonly traceId: string | null;

  /**
   * 出错的位置，例如 "GET /api/docs"。仅诊断用，不显示给用户。
   * contract 错误尤其需要它 —— "校验失败"不说明是哪个接口，等于没说。
   */
  readonly context: string | null;

  constructor(
    kind: ErrorKind,
    message: string,
    options: ApiErrorOptions = {},
  ) {
    // cause 传给 Error 基类：保留原始错误的堆栈，排查时能看到最初是哪一行抛的
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.traceId = options.traceId ?? null;
    this.context = options.context ?? null;
  }

  /**
   * 哪些错误值得让用户点「重试」。
   *
   * aborted 是用户自己取消的，不该弹重试；http 4xx 是请求本身有问题，重试也没用；
   * contract 是代码 bug，重试永远是同样的结果 —— 让用户重试是骗他。
   */
  get retryable(): boolean {
    if (this.kind === "aborted") return false;
    if (this.kind === "contract") return false;
    if (this.kind === "http") return (this.status ?? 0) >= 500;
    return true; // network / timeout 都值得重试
  }
}

/**
 * 把任意 catch 到的东西收成 ApiError。
 *
 * 为什么入参是 unknown：TypeScript 里 catch 变量的类型就是 unknown，因为
 * JS 允许 `throw "字符串"`、`throw null`、`throw {code:1}`。
 * Day 6 交接里记的 `documentStore.js:54` 那个 `error.message` 问题就在这 ——
 * 它在 JS 里能跑只是因为运行时碰巧 throw 的都是 Error 实例，那是运气不是保证。
 */
export function toApiError(value: unknown, fallbackMessage = "未知错误"): ApiError {
  if (value instanceof ApiError) return value;

  if (value instanceof Error) {
    return new ApiError("network", value.message || fallbackMessage, { cause: value });
  }

  // 到这里 value 可能是字符串、数字、null、普通对象 —— 都不能直接读 .message
  return new ApiError("network", fallbackMessage, { cause: value });
}
