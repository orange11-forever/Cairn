// 消息列表的渲染测试。纯展示组件，直接传 props 进去，没有请求要打桩。
//
// ---------------------------------------------------------------------------
// 这个文件里有一条**明确的能力边界**要记住：
//
// 自动滚动（useAutoScroll）在这一层**测不了**。jsdom 没有布局引擎——
// scrollHeight、clientHeight 全返回 0，于是"是否贴底"永远算出 0 <= 40 = true，
// 而 scrollTop = 0 的赋值也观察不到任何效果。
//
// 在这里写一条 `expect(container.scrollTop).toBe(container.scrollHeight)`
// 会**通过**（0 === 0），但它什么都没证明——它是一条假绿的断言，
// 比没有测试更坏，因为它会让人以为这件事被验证过了。
//
// 所以：滚动行为由 verify-web.mjs 在真 Chromium 里验证。
// 这一层只测能测的东西（结构、文案、条件渲染）。
// 知道每层能证明什么、不能证明什么，比测试数量重要——这是 Day 5 起就在攒的那条。
// ---------------------------------------------------------------------------

import { describe, expect, test } from "vitest";
import { render, screen } from "@testing-library/react";

import { MessageList } from "../../src/components/MessageList.tsx";
import type { Message } from "../../src/components/MessageList.tsx";

const USER_MESSAGE: Message = { id: "u1", role: "user", text: "值班故障如何升级" };

const ASSISTANT_MESSAGE: Message = {
  id: "a1",
  role: "assistant",
  text: "先通知当班负责人。",
  sources: [{ label: "值班流程，section-4" }],
};

describe("空状态", () => {
  test("没有消息也不在等待时给引导", () => {
    render(<MessageList messages={[]} />);
    expect(screen.getByText("还没有提问。问一个问题试试。")).toBeInTheDocument();
  });

  test("正在等待时显示占位而不是引导文案", () => {
    // 用户刚提交，列表里已经有他的提问了，这时候显示"还没有提问"是自相矛盾的。
    render(<MessageList messages={[USER_MESSAGE]} pending />);

    expect(screen.queryByText("还没有提问。问一个问题试试。")).toBeNull();
    expect(screen.getByText("正在检索知识文档…")).toBeInTheDocument();
  });

  test("空列表 + 等待中：仍然显示占位", () => {
    // 边界情况：乐观更新失败回滚后又重试的瞬间可能出现。
    // 不处理的话会先闪一下"还没有提问"再变成"正在检索"。
    render(<MessageList messages={[]} pending />);
    expect(screen.queryByText("还没有提问。问一个问题试试。")).toBeNull();
    expect(screen.getByText("正在检索知识文档…")).toBeInTheDocument();
  });
});

describe("消息渲染", () => {
  test("用户消息不渲染引用区", () => {
    render(<MessageList messages={[USER_MESSAGE]} />);

    expect(screen.getByText("值班故障如何升级")).toBeInTheDocument();
    // "引用来源"标题下面空着看起来像功能坏了。
    // 用户的提问本来就没有引用，所以整块不该出现。
    expect(screen.queryByText("引用来源")).toBeNull();
  });

  test("助手消息渲染非链接引用标签", () => {
    render(<MessageList messages={[ASSISTANT_MESSAGE]} />);

    expect(screen.getByText("引用来源")).toBeInTheDocument();
    expect(screen.getByText("值班流程，section-4")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "值班流程，section-4" })).toBeNull();
  });

  test("引用为空数组时不渲染引用区", () => {
    // citations: [] 的含义是"这个问题在知识库里没找到依据"（schema 注释里定过），
    // 不是"忘了带引用"。这两种情况的 UI 都是"不显示引用区"，
    // 但区别在于前者是合法状态，Day 14 会给它专门的文案。
    render(
      <MessageList messages={[{ id: "a2", role: "assistant", text: "没找到。", sources: [] }]} />,
    );
    expect(screen.queryByText("引用来源")).toBeNull();
  });

  test("对话按顺序渲染在有序列表里", () => {
    render(<MessageList messages={[USER_MESSAGE, ASSISTANT_MESSAGE]} />);

    // ol 而不是 ul：对话有严格顺序，第 3 句只有在第 2 句之后才说得通。
    // 按 role="list" 找并检查它内部的顺序，而不是查标签名——
    // 顺序是用户能观察到的，标签名是实现。
    const list = screen.getByRole("list", { name: "对话记录" });

    // 只取**直接子项**。within(list).getAllByRole("listitem") 会连引用列表里的
    // <li> 一起收进来（引用嵌在助手消息内部），于是两条消息数出三项。
    // 这不是工具的毛病：从读屏的角度那三个 li 确实都在这棵子树里。
    // 要断言的是"对话有几轮"，那对应的是直接子项。
    const items = [...list.children];
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("值班故障如何升级");
    expect(items[1]).toHaveTextContent("先通知当班负责人。");
  });

  test("等待占位排在已有消息后面", () => {
    render(<MessageList messages={[USER_MESSAGE]} pending />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    // 占位在最后：用户看到的是"我的提问 + 正在检索"，两条挨着，等待的对象很清楚。
    expect(items[1]).toHaveTextContent("正在检索知识文档…");
  });

  test("等待占位不会被当成一条真回答", () => {
    // data-role="pending" 而不是复用 "assistant" 的理由：
    // 复用的话，"有一条 assistant 消息"这种断言会在还没答完时就通过。
    const { container } = render(<MessageList messages={[USER_MESSAGE]} pending />);

    expect(container.querySelectorAll('[data-role="assistant"]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-role="pending"]')).toHaveLength(1);
  });
});
