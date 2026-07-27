// 状态文案：把状态机的 phase 翻译成一句人话 + 一个语气。
//
// Day 8 从 ui/statusBar.ts 抽出来。抽离的理由不是审美，是可测性：
// 原来这套逻辑嵌在 renderStatusBar(element, state) 里，要测它就得先造一个 DOM 元素，
// 于是它只能在浏览器里被验证（八帧脚本）。八帧是好东西，但它一次跑八种情况、
// 要起服务器和 Playwright，加一个 case 的成本很高——所以实际上从没人为
// 「dropped 是 1 还是 0」这种细节单独加一帧。
//
// 抽成 (state) => {tone, text} 的纯函数后，它能被 node --test 直接调用：
// 输入是普通对象，输出是普通对象，没有 DOM、没有网络、没有时序。
// 这也是为什么这个文件是 .ts 而不是 .tsx——Node 的 --test 不认 JSX 语法。
//
// 所有面向用户的文案集中在这里，方便日后接 i18n，也方便 review 文案是否得体。

import type { ApiError } from "../api/errors.ts";
import type { DocumentState } from "../state/documentStore.ts";

/** 语气。CSS 靠 data-tone 选择颜色，测试靠它断言。 */
export type Tone = "idle" | "loading" | "ok" | "empty" | "error";

export interface StatusText {
  tone: Tone;
  text: string;
}

export function describeStatus(state: DocumentState): StatusText {
  switch (state.phase) {
    case "idle":
      return { tone: "idle", text: "点击「加载文档」开始" };

    case "loading":
      return { tone: "loading", text: "加载中…" };

    case "success": {
      // 空数据是成功的一种，给引导而不是报错——这是产品判断，不是技术判断。
      if (state.documents.length === 0) {
        return { tone: "empty", text: "还没有文档，上传第一个吧" };
      }

      // 校验层丢过数据时必须说出来。用户看到"已加载 3 个文档"而实际后端有 5 个，
      // 他会以为文档丢了 —— 而真相是前端没看懂其中两条。沉默地少显示数据，
      // 是那种"用户过很久才发现、发现时已经不信任这个系统"的问题。
      const suffix = state.dropped > 0 ? `（${state.dropped} 条无法显示）` : "";
      return { tone: "ok", text: `已加载 ${state.documents.length} 个文档${suffix}` };
    }

    case "error":
      // 联合类型在这里的回报：state.error 必然存在，不用判空。
      return { tone: "error", text: errorText(state.error) };

    default:
      // 穷尽性检查。将来往 DocumentState 加一个 phase 而忘了在这里处理，
      // 这一行会报 "Type 'xxx' is not assignable to type 'never'"。
      //
      // 原来这里是 `default: return { tone: "idle", text: "" }` —— 一个静默兜底。
      // 那个写法会让新增的状态显示成一条空白状态栏：不报错、不崩溃、就是没文字，
      // 是最难发现的一类 bug。换成 never 之后同样的疏忽变成编译错误。
      return assertNever(state);
  }
}

/**
 * 穷尽性断言。参数类型是 never，所以只有"所有分支都处理过了"时才能调用成功。
 *
 * 运行时仍然抛错而不是返回兜底值：能走到这里说明有人绕过类型检查（比如从 JS 调用），
 * 那时候安静地显示空白比抛错更糟。
 */
function assertNever(value: never): never {
  throw new Error(`未处理的状态：${JSON.stringify(value)}`);
}

// 按错误种类给不同文案，这就是 ApiError.kind 存在的全部意义：
// 用户看到「检查网络」和「服务器出错，稍后重试」时，采取的行动完全不同。
function errorText(error: ApiError): string {
  switch (error.kind) {
    case "network":
      return `${error.message}（可重试）`;

    case "http":
      return (error.status ?? 0) >= 500
        ? `服务器出错（${error.status}），请稍后重试`
        : `请求无法完成（${error.status}）`;

    case "timeout":
      return `${error.message}，网络较慢，可重试`;

    case "contract":
      // 刻意不加"请重试"：contract 是代码 bug，重试一万次结果一样，
      // 让用户重试是骗他。给的引导是"联系管理员"（message 里已有），
      // 因为这个问题只能由开发者修。
      return error.message;

    case "aborted":
      // 正常情况下走不到：store 把 aborted 转成 idle 了。
      // 但仍要显式列出来，否则下面的穷尽检查过不去 —— 这正是穷尽检查的作用：
      // 它强迫你对每一种错误都想一遍"这里该显示什么"。
      return "请求已取消";

    default:
      return assertNever(error.kind);
  }
}
