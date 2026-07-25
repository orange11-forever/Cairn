// 统一错误模型。
// 整个前端只认这一种错误类型，调用方靠 kind 决定给用户什么反馈。
// Day 12 会把它接进正式请求层，Day 25 还要把后端 LLM Provider 的错误映射进这四类。

/** @typedef {"network" | "http" | "timeout" | "aborted"} ErrorKind */

export class ApiError extends Error {
  /**
   * @param {ErrorKind} kind  错误种类，决定 UI 文案和是否可重试
   * @param {string} message  给用户看的话，不是给开发者看的堆栈
   * @param {number | null} status  仅 kind === "http" 时有值
   */
  constructor(kind, message, status = null) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = status;
  }

  // 语义化判断：哪些错误值得让用户点「重试」。
  // aborted 是用户自己取消的，不该弹重试；http 4xx 是请求本身有问题，重试也没用。
  get retryable() {
    if (this.kind === "aborted") return false;
    if (this.kind === "http") return this.status >= 500;
    return true; // network / timeout 都值得重试
  }
}
