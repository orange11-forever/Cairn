// 状态条：把状态机的 phase 翻译成一句人话。
// 所有面向用户的文案集中在这里，方便日后接 i18n，也方便 review 文案是否得体。

/**
 * @param {HTMLElement} element
 * @param {{ phase: string, documents: unknown[], error: import("../api/errors.js").ApiError | null }} state
 */
export function renderStatusBar(element, state) {
  const { tone, text } = describe(state);
  element.dataset.tone = tone;
  element.textContent = text;
}

function describe({ phase, documents, error }) {
  switch (phase) {
    case "idle":
      return { tone: "idle", text: "点击「加载文档」开始" };

    case "loading":
      return { tone: "loading", text: "加载中…" };

    case "success":
      // 空数据是成功的一种，给引导而不是报错——这是产品判断，不是技术判断。
      return documents.length === 0
        ? { tone: "empty", text: "还没有文档，上传第一个吧" }
        : { tone: "ok", text: `已加载 ${documents.length} 个文档` };

    case "error":
      return { tone: "error", text: errorText(error) };

    default:
      return { tone: "idle", text: "" };
  }
}

// 按错误种类给不同文案，这就是 ApiError.kind 存在的全部意义：
// 用户看到「检查网络」和「服务器出错，稍后重试」时，采取的行动完全不同。
function errorText(error) {
  if (!error) return "发生未知错误";

  switch (error.kind) {
    case "network":
      return `${error.message}（可重试）`;
    case "http":
      return error.status >= 500
        ? `服务器出错（${error.status}），请稍后重试`
        : `请求无法完成（${error.status}）`;
    case "timeout":
      return `${error.message}，网络较慢，可重试`;
    default:
      return error.message;
  }
}
