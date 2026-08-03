// 引用来源。纯展示，粒度最小的组件。
//
// 为什么值得单独成一个组件：引用是 Cairn 的核心承诺——
// "回答只依据已处理完成的知识文档"，没有引用的回答不可信。
// 它将来要长出更多东西（跳转到文档内锚点、显示相关度、标记引用片段是否已过期），
// 现在把它隔离出来，那些变化就只影响这一个文件。

import { BookOpenText } from "lucide-react";

export interface CitationSource {
  /** 人类可读的位置，例如 "值班流程，第 4 节" */
  label: string;
}

interface CitationProps {
  sources: CitationSource[];
}

export function Citation({ sources }: CitationProps) {
  // 没有引用就不渲染标题——一个"引用来源"标题下面空着，
  // 看起来像功能坏了，而实际情况是这条回答没有引用。
  if (sources.length === 0) return null;

  return (
    <>
      <h3>
        <BookOpenText aria-hidden="true" size={15} strokeWidth={1.8} />
        引用来源
      </h3>
      {/* ol 而不是 ul：引用有顺序，第 1 条通常是最相关的那条。
          aria-label 同 MessageList：两个列表在同一屏，读屏用户要能分清。 */}
      <ol className="citation-list" aria-label="引用来源">
        {sources.map((source, index) => (
          <li key={`${source.label}-${index}`}>
            <span>{source.label}</span>
          </li>
        ))}
      </ol>
    </>
  );
}
