// 文档列表渲染。只负责「数据 → DOM」，不发请求、不管状态。

import { statusLabel } from "../lib/documents.js";

/**
 * 把文档数组画进容器。
 * 用 textContent 而不是 innerHTML 拼字符串：标题来自用户上传的文件名，
 * 直接拼进 innerHTML 就是一个 XSS 入口（Day 32 会正经讲）。
 *
 * @param {HTMLElement} container
 * @param {import("../lib/documents.js").Document[]} documents
 */
export function renderDocumentList(container, documents) {
  container.replaceChildren(
    ...documents.map((doc) => {
      const item = document.createElement("li");

      const title = document.createElement("strong");
      title.textContent = doc.title;

      const status = document.createElement("span");
      status.className = "document-status";
      // data-state 是 CSS 的挂钩点，也是测试和 Playwright 的选择器依据。
      // 用 data-* 而不是 class 拼接，状态值和样式实现解耦。
      status.dataset.state = doc.status;
      status.textContent = statusLabel(doc.status);

      item.append(title, status);
      return item;
    }),
  );
}
