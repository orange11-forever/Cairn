// 状态条。纯展示：状态进来，一句人话出去。
//
// 文案逻辑不在这里——在 lib/statusText.ts。这个组件只负责把它渲染出来。
// 分开的理由见那个文件的头注释（一句话：纯函数能被 node --test 直接调用，JSX 不能）。

import { describeStatus } from "../lib/statusText.ts";
import type { DocumentLoadState } from "../lib/statusText.ts";

interface StatusBarProps {
  state: DocumentLoadState;
}

export function StatusBar({ state }: StatusBarProps) {
  const { tone, text } = describeStatus(state);

  return (
    // id 和 data-tone 照原样保留：CSS 靠 data-tone 选颜色，
    // verify-web.mjs 的八帧靠 #status-bar + data-tone 断言。
    // Day 8 换了整个渲染层，那个脚本一行不改——它没参与这次改动，
    // 所以它的判决才能证明"行为没变"，而不只是"新代码和新断言自洽"。
    //
    // aria-live：状态变化要让读屏用户听到，而不只是看到颜色变了。
    <p id="status-bar" className="status" data-tone={tone} role="status" aria-live="polite">
      {text}
    </p>
  );
}
