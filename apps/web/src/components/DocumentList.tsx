// 文档列表。纯展示：数据进来，列表出去。不发请求、不管状态。

import { statusLabel } from "../lib/documents.ts";
import type { Document } from "../schemas/documents.ts";

interface DocumentListProps {
  documents: Document[];
}

export function DocumentList({ documents }: DocumentListProps) {
  return (
    <ul id="document-list" className="document-list" aria-label="文档列表">
      {documents.map((doc) => (
        // key 用 doc.id，不用数组下标。
        //
        // 下标做 key 在"列表只会整体替换"时看起来没问题，实际上会在增删和重排时出错：
        // React 靠 key 判断"这一项还是不是原来那一项"，下标做 key 等于说
        // "第 2 个位置永远是同一项"——删掉第 1 项后，原来的第 3 项占到位置 2，
        // React 认为它没变，于是复用了错误的 DOM 节点和它内部的状态。
        // 列表项存在「展开/折叠」等局部 state 时，这个 bug 会表现为删掉一项后
        // 展开状态跳到了另一项身上。
        //
        // doc.id 由 schema 保证存在且唯一（schemas/documents.ts 里校验过），
        // 所以这里能安全地用它。
        <li key={doc.id}>
          <strong>{doc.title}</strong>
          {/*
            data-state 是 CSS 的挂钩点，也是测试和 Playwright 的选择器依据。
            用 data-* 而不是 class 拼接，状态值和样式实现解耦。

            JSX 在这里顺带解决了旧代码的一个隐患：手写版本必须用 textContent
            而不能拼 innerHTML，因为标题来自用户上传的文件名，拼字符串就是 XSS 入口。
            JSX 的 {doc.title} 默认转义，同样安全，但不需要靠人记得。
            这是"安全的做法同时是最省事的做法"。
          */}
          <span className="document-status" data-state={doc.status}>
            {statusLabel(doc.status)}
          </span>
        </li>
      ))}
    </ul>
  );
}
