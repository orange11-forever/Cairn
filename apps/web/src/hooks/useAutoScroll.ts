// 消息列表的自动滚动。
//
// 这是 useRef + useEffect 的一个正当用途，也是本日「什么时候必须用 Effect」的
// 第二个正面样本：**滚动位置无法用渲染表达**。
//
// React 的模型是「UI 是 state 的函数」，但 scrollTop 不是 UI 的一部分——
// 它是浏览器持有的一个可变状态，没有任何 JSX 语法能描述"滚到底部"。
// 这类操作只能在 DOM 已经更新完之后，命令式地做一次。Effect 是它唯一的落点。
//
// ---------------------------------------------------------------------------
// 这个 Hook 的难点不是"怎么滚"，是"什么时候不该滚"。
//
// 无条件 `scrollTop = scrollHeight` 是最常见的实现，也是最惹人烦的：
// 用户往上翻去看第一个回答里的引用，这时新消息到了，页面把他弹回底部。
// 他失去了正在读的位置，而且不知道为什么。
//
// 正确行为：只在用户**本来就贴着底部**时才跟着滚。他往上翻了就说明在读历史，
// 这时候新消息可以到，但视口不动。
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useRef } from "react";

/**
 * 判定"贴底"的容差（像素）。
 *
 * 不能用 `scrollTop + clientHeight === scrollHeight` 严格判等：
 * 这三个值在缩放、分数像素、以及某些浏览器的滚动惯性下会差出零点几像素，
 * 严格判等会让"用户明明在底部"被判成"在读历史"，于是自动滚动随机失效。
 * 这类"大部分时候好用"的 bug 比彻底不工作难查得多。
 */
const BOTTOM_TOLERANCE_PX = 40;

/**
 * 让容器在内容变化时滚到底部——**仅当用户本来就在底部**。
 *
 * @param dependency 内容变化的信号。传消息条数，不传整个数组：
 *                   数组每次渲染都是新引用（setMessages 返回新数组），
 *                   用它做依赖等于每次渲染都滚一次。条数是原始值，只在真变了时触发。
 * @returns 挂到滚动容器上的 ref
 */
export function useAutoScroll<T extends HTMLElement = HTMLDivElement>(dependency: number) {
  // 泛型参数而不是写死 HTMLElement：React 的 ref 属性要求类型精确匹配
  //（RefObject<HTMLElement> 不能赋给 <div> 的 ref，因为 HTMLDivElement
  // 比 HTMLElement 多几个字段）。默认 HTMLDivElement 覆盖最常见的情况。
  const containerRef = useRef<T | null>(null);

  // "用户是否贴着底部"。
  //
  // 用 ref 而不是 useState 的理由是硬的，不是偏好：
  //   1. 这个值不参与渲染——UI 不因为它变化而长得不一样。
  //   2. scroll 事件是高频的（一次滚动动作能触发几十次）。每次 setState
  //      就是一次重渲染，而这个组件里挂着一整个消息列表。
  // 这是 useRef 的教科书用途：需要跨渲染保存的可变值，且它不影响输出。
  //
  // 初始 true：列表刚挂载时是空的（也就在底部），第一条消息应该能滚进视野。
  const stickToBottom = useRef(true);

  // ---------------------------------------------------------------------------
  // 订阅 scroll 事件用 **ref 回调**，不用 useEffect。
  //
  // 这是踩出来的：原来写的是
  //   useEffect(() => {
  //     const container = containerRef.current;
  //     if (container === null) return;
  //     container.addEventListener("scroll", handleScroll);
  //     return () => container.removeEventListener("scroll", handleScroll);
  //   }, []);
  //
  // 它在 verify-web.mjs 的自动滚动帧里被抓住了：用户翻到顶部后，
  // 新消息仍然把他弹回底部（scrollTop=375 而不是 ~0）。
  //
  // 原因是**滚动容器是条件渲染的**。MessageList 在消息为空时渲染的是一个 <p>，
  // 不是 .message-scroll。于是首次挂载时 containerRef.current 是 null，
  // 那个 Effect 直接 return——而依赖是 []，它**再也不会重跑**。
  // 监听器从此不存在，stickToBottom 永远停在初始的 true，
  // 于是"是否贴底"这个判断彻底失效，退化成了无条件滚动。
  //
  // 症状的隐蔽之处：自动滚动**看起来是好的**（因为无条件滚也会滚到底），
  // 坏掉的只有"用户在读历史时不打扰他"这一半。手工测试几乎不会发现。
  //
  // ref 回调没有这个问题：它由 React 在**节点真正挂载/卸载时**调用，
  // 条件渲染的元素出现时它一定会被调到。
  // React 19 支持从 ref 回调里返回清理函数，所以订阅和退订能写在一处。
  // ---------------------------------------------------------------------------
  const attachRef = useCallback((node: T | null) => {
    containerRef.current = node;
    if (node === null) return;

    // 捕进一个 const 再用。
    // 直接在 handleScroll 里读 node 会报 "node is possibly null"——
    // TypeScript 的收窄不跨函数边界传递（它无法证明这个闭包不会在 node
    // 被重新赋值之后才执行）。const 让"这个值不会变"这件事对编译器可见。
    const element = node;

    function handleScroll() {
      const distanceFromBottom =
        element.scrollHeight - element.scrollTop - element.clientHeight;
      stickToBottom.current = distanceFromBottom <= BOTTOM_TOLERANCE_PX;
    }

    // passive: true 告诉浏览器这个监听器不会调用 preventDefault，
    // 于是它不必等 JS 跑完再决定要不要滚动。滚动类监听器不加这个会掉帧。
    element.addEventListener("scroll", handleScroll, { passive: true });

    // React 19 的 ref 清理函数。节点卸载时调用——
    // 不退订的后果是每次容器重挂载都多一个持有旧闭包的监听器（内存泄漏的经典形状）。
    return () => {
      element.removeEventListener("scroll", handleScroll);
      containerRef.current = null;
    };
  }, []);

  // ---- 内容变化后滚到底部 ----
  useEffect(() => {
    const container = containerRef.current;
    if (container === null) return;
    if (!stickToBottom.current) return; // 用户在读历史，别动他的视口

    // 这一行必须在 DOM 更新之后跑，否则 scrollHeight 还是旧的高度，
    // 滚过去会差最后一条消息的距离。useEffect 的时机正好在 commit 之后，
    // 这就是"为什么不能把它写在渲染函数里"的具体答案。
    container.scrollTop = container.scrollHeight;
  }, [dependency]);

  return attachRef;
}
