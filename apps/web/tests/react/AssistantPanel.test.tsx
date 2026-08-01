// 问答面板的组件测试：消息渲染、乐观更新与回滚、取消、重试。
//
// 这个文件里最有价值的几条断言都在测**失败路径**（回滚、取消、重试），
// 因为成功路径手点一次就能验证，而失败路径要制造 500、要卡住请求再取消——
// 手工验证的成本高到实际上不会做，于是那些代码是整个应用里最少被走到的部分。
// 测试的价值和"手工验证这条路径有多难"成正比。

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssistantPanel } from "../../src/components/AssistantPanel.tsx";

const ANSWER = {
  id: "a-1",
  role: "assistant",
  content: "严重故障需要先通知当班负责人，再按照升级矩阵联系服务负责人。",
  createdAt: "2026-07-30T10:00:00Z",
  citations: [
    {
      documentId: 1,
      documentTitle: "值班流程",
      snippet: "P0 故障 5 分钟内通知当班负责人。",
      anchor: "section-4",
      score: 0.92,
    },
  ],
};

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function stubFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(handler));
}

const QUESTION = "值班故障如何升级";

/** 提一个问题。三个测试都要做，抽出来。 */
async function ask(user: ReturnType<typeof userEvent.setup>, text = QUESTION) {
  await user.type(screen.getByLabelText("你的问题"), text);
  await user.click(screen.getByRole("button", { name: "发送问题" }));
}

beforeEach(() => {
  stubFetch(async () => jsonResponse(ANSWER));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("消息渲染", () => {
  test("没有消息时给引导，不是一片空白", async () => {
    render(<AssistantPanel />);
    expect(screen.getByText("还没有提问。问一个问题试试。")).toBeInTheDocument();
  });

  test("成功后显示提问、回答和引用链接", async () => {
    const user = userEvent.setup();
    render(<AssistantPanel />);

    await ask(user);

    // 用户的提问和助手的回答都在屏幕上
    expect(await screen.findByText(QUESTION)).toBeInTheDocument();
    expect(await screen.findByText(ANSWER.content)).toBeInTheDocument();

    // 引用渲染成一个**可点的链接**。
    // 按 role="link" 找而不是找 <a>：用户要的是"能点过去"，
    // 而一个没有 href 的 <a> 在 DOM 里还是 a，但不是 link 角色，也点不了。
    const citation = await screen.findByRole("link", { name: "值班流程，section-4" });
    expect(citation).toHaveAttribute("href", "/documents/1#section-4");
  });

  test("引用标题带上锚点，否则多条引用指向同一文档时看起来一样", async () => {
    stubFetch(async () =>
      jsonResponse({
        ...ANSWER,
        citations: [
          { ...ANSWER.citations[0], anchor: "section-4" },
          { ...ANSWER.citations[0], anchor: "section-7" },
        ],
      }),
    );

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    const links = await screen.findAllByRole("link");
    // 两条引用的可读文本必须不同——都显示"值班流程"的话，
    // 用户看到两行一样的字，不知道该点哪个。
    expect(links.map((el) => el.textContent)).toEqual(["值班流程，section-4", "值班流程，section-7"]);
  });

  test("没有 anchor 的引用退化成跳文档开头，而不是被丢掉", async () => {
    stubFetch(async () =>
      jsonResponse({
        ...ANSWER,
        citations: [{ documentId: 7, documentTitle: "部署手册", snippet: "先备份。" }],
      }),
    );

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    // 能跳到文档但落在开头，仍然比没有引用有用得多
    const link = await screen.findByRole("link", { name: "部署手册" });
    expect(link).toHaveAttribute("href", "/documents/7");
  });
});

describe("等待与乐观更新", () => {
  test("提交后立刻显示提问，不等回答", async () => {
    let release: (() => void) | undefined;
    stubFetch(
      () => new Promise<Response>((resolve) => { release = () => resolve(jsonResponse(ANSWER)); }),
    );

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    // 这就是乐观更新的全部意义：等待期间屏幕上有用户自己的话在，
    // 他不会怀疑发送没成功然后再点一次。
    expect(screen.getByText(QUESTION)).toBeInTheDocument();

    // 而且明确告诉他在等什么
    expect(screen.getByText("正在检索知识文档…")).toBeInTheDocument();

    release?.();
  });

  test("等待期间输入框禁用、按钮文案变化、出现停止生成", async () => {
    let release: (() => void) | undefined;
    stubFetch(
      () => new Promise<Response>((resolve) => { release = () => resolve(jsonResponse(ANSWER)); }),
    );

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    // 禁用输入的理由：用户在等待期间改了问题，回答到达时会显示在
    // 他已经改掉的问题下面——他会以为系统答错了。
    expect(screen.getByLabelText("你的问题")).toBeDisabled();
    expect(await screen.findByRole("button", { name: "正在回答…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "停止生成" })).toBeInTheDocument();

    release?.();
  });

  test("空闲时没有停止生成按钮", () => {
    render(<AssistantPanel />);
    // 常驻一个灰色的"停止"会让用户以为随时有东西可以停
    expect(screen.queryByRole("button", { name: "停止生成" })).toBeNull();
  });

  test("提交后清空草稿", async () => {
    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    await waitFor(() => expect(screen.getByLabelText("你的问题")).toHaveValue(""));
  });
});

describe("失败与回滚", () => {
  test("请求失败时撤掉那条提问，不留孤儿", async () => {
    stubFetch(async () => jsonResponse({ message: "服务器内部错误" }, 500));

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    // 显示的是**后端给的那句话**（client.ts 的 extractErrorMessage 提取的），
    // 不是 statusText.ts 里那句"服务器出错（500），请稍后重试"。
    //
    // 这两条路径的文案策略现在不一致：文档列表走 describeStatus 做统一映射，
    // 问答直接显示 error.message。写这条断言时才发现——已记为待定问题，
    // Day 12 建统一请求层时一起收口（那时该有一个"错误文案在哪一层决定"的答案）。
    expect(await screen.findByRole("alert")).toHaveTextContent("服务器内部错误");

    // 关键断言：那条提问必须消失。
    // 留着它，列表里就有一条永远等不到回答的提问——用户会以为系统在想，
    // 而实际上什么都不会再发生。
    await waitFor(() => expect(screen.queryByText(QUESTION)).toBeNull());

    // 回到空列表状态，引导文案重新出现
    expect(screen.getByText("还没有提问。问一个问题试试。")).toBeInTheDocument();
  });

  test("失败后能重试，且不用重新打一遍问题", async () => {
    let calls = 0;
    stubFetch(async () => {
      calls += 1;
      return calls === 1 ? jsonResponse({ message: "服务器内部错误" }, 500) : jsonResponse(ANSWER);
    });

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    // 草稿在提交时已经清空了，所以重试必须用**原文**——
    // 让用户重新打一遍是把系统的失败转嫁给他。
    await user.click(await screen.findByRole("button", { name: "重试" }));

    expect(await screen.findByText(ANSWER.content)).toBeInTheDocument();
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  test("成功之后重试按钮消失", async () => {
    let calls = 0;
    stubFetch(async () => {
      calls += 1;
      return calls === 1 ? jsonResponse({ message: "服务器内部错误" }, 500) : jsonResponse(ANSWER);
    });

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);
    await user.click(await screen.findByRole("button", { name: "重试" }));
    await screen.findByText(ANSWER.content);

    // 成功了就没有可重试的东西。留着按钮会让用户以为刚才那条答案有问题。
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("契约错误不给重试——重试一万次结果一样", async () => {
    // content 缺失 → schema 拒绝 → contract 错误。
    // 这是代码 bug（前后端版本不匹配），不是临时故障。
    stubFetch(async () => jsonResponse({ id: "a-1", role: "assistant", citations: [] }));

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("格式不正确");
    // ApiError.retryable 对 contract 返回 false，UI 必须尊重它。
    // 给用户一个永远不会成功的重试按钮是骗他。
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
  });
});

describe("取消", () => {
  test("停止生成真的 abort 了请求，并撤掉提问", async () => {
    // 记录 fetch 收到的 signal，用它证明取消不只是 UI 上装样子。
    let capturedSignal: AbortSignal | undefined;
    stubFetch(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          capturedSignal = init?.signal ?? undefined;
          // 真 fetch 在 abort 时是 reject 一个 AbortError，这里照样模拟
          init?.signal?.addEventListener("abort", () => {
            reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
          });
        }),
    );

    const user = userEvent.setup();
    render(<AssistantPanel />);
    await ask(user);

    await user.click(screen.getByRole("button", { name: "停止生成" }));

    // 这条断言是整条取消链路的证据：
    // useAsyncAction → askQuestion → request → fetch，任何一环漏传 signal，
    // 这里就是 false——而 UI 照样会显示"已停止"，看起来一切正常。
    await waitFor(() => expect(capturedSignal?.aborted).toBe(true));

    // 取消**不是错误**：不该弹红条（同 documentStore 里那条判断）
    expect(screen.queryByRole("alert")).toBeNull();

    // 提问也要撤掉：用户主动放弃了，留着它没有意义
    await waitFor(() => expect(screen.queryByText(QUESTION)).toBeNull());

    // 回到可以重新提问的状态
    expect(await screen.findByRole("button", { name: "发送问题" })).toBeEnabled();
    expect(screen.getByLabelText("你的问题")).toBeEnabled();
  });
});
