// 每个 React 测试文件跑之前先执行这里。
//
// 两件事：装 jest-dom 的断言，和保证测试之间互不污染。

import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jest-dom 的断言。
//
// 用 "/vitest" 这个入口而不是 `expect.extend(matchers)`：
// 它同时做两件事——注册断言（运行时）**和**扩展 vitest 的 Assertion 接口（类型）。
// 手动 expect.extend 只做前者，于是 tsc 会对每一个 toBeDisabled 报
// "Property does not exist on type Assertion"——测试跑得过但 typecheck 全红。
// 这是踩了才知道的：两个入口的运行时行为一样，类型效果不一样。
//
// 为什么值得多一个依赖：
//
//   expect(button).toBeDisabled()
//   expect(button.hasAttribute("disabled")).toBe(true)
//
// 上面那行读起来是「按钮不可用」——一句关于**用户看到什么**的陈述。
// 下面那行读起来是「这个 DOM 节点有个叫 disabled 的属性」——关于实现细节。
// 而"测试关注用户行为而不是组件内部实现"正是今天的验收标准，
// 断言的措辞是它最直接的落点。
//
// toHaveAccessibleDescription 更是没法手写：它要模拟读屏软件解析
// aria-describedby 的整个过程（多个 id、空格分隔、拼接顺序）。
import "@testing-library/jest-dom/vitest";

// 每个测试后卸载渲染的组件。
//
// 不做的后果：上一个测试的 DOM 留在 document.body 里，下一个测试
// getByLabelText("邮箱") 会找到两个匹配然后报错——而报的错是
// "Found multiple elements"，看起来像组件里重复渲染了 label，
// 完全指不到真正的原因（前一个测试没清理）。
//
// 顺带：cleanup 会触发组件卸载，于是 useAsyncAction 的卸载清理 Effect
// 真的会跑。那意味着这些测试同时在验证"卸载时 abort"没有崩溃——
// 免费拿到的一层保障。
afterEach(() => {
  cleanup();
});
