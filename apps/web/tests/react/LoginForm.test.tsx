// 登录表单的组件测试。
//
// ---------------------------------------------------------------------------
// 「测试关注用户行为而不是组件内部实现」这条验收标准在这个文件里的具体含义：
//
//   ✗ 不做的事：读组件的 state、断言 useState 被调用了几次、
//               用 container.querySelector("#login-email") 找元素、
//               断言某个 class 名存在。
//               这些全是实现细节——把 id 改个名、把 useState 换成 useReducer，
//               用户什么都感觉不到，而这类测试会全红。它们守的不是行为。
//
//   ✓ 做的事：用**用户找元素的方式**找元素（按 label 文字、按角色、按可见文本），
//             用**用户能观察到的东西**做断言（屏幕上的文字、按钮能不能点、
//             读屏会播报什么）。
//
// 判据：如果把组件从头重写一遍、只保证外部行为一致，这些测试应当全绿。
// ---------------------------------------------------------------------------

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LoginForm } from "../../src/components/LoginForm.tsx";

/**
 * 假的 fetch。
 *
 * 为什么在 fetch 这一层打桩，而不是 mock 掉 api/auth.ts：
 * 打在 fetch 上，被测的范围包含了真实的 client.ts（超时、错误分类、
 * response.ok 判断）和真实的 schema 校验。那些是这个表单实际依赖的东西，
 * mock 掉 auth.ts 就等于把它们全部替换成"假定它们是对的"。
 *
 * 换句话说：桩打得越靠外，测试证明的东西越多。
 */
function stubFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(handler));
}

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

const VALID_IDENTITY = {
  user: { id: "00000000-0000-4000-8000-000000001001", email: "demo@cairn.dev", displayName: "演示用户" },
  organization: { id: "00000000-0000-4000-8000-000000002001", slug: "cairn-demo", name: "Cairn Demo" },
  membership: { id: "00000000-0000-4000-8000-000000003001", role: "owner" },
  csrfToken: "csrf-test-token",
};

beforeEach(() => {
  stubFetch(async () => jsonResponse(VALID_IDENTITY));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("显示 Cairn 品牌场景且不改变登录表单契约", () => {
  render(<LoginForm onSuccess={vi.fn()} />);

  expect(screen.getByRole("region", { name: "Cairn 品牌场景" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Cairn" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Cairn 看板娘" })).toHaveAttribute(
    "data-variant",
    "full",
  );
  expect(screen.getByRole("heading", { name: "登录 Cairn" })).toBeInTheDocument();
  expect(screen.getByLabelText("邮箱")).toHaveAttribute("id", "login-email");
  expect(screen.getByLabelText("密码")).toHaveAttribute("id", "login-password");
});

test("wordmark 加载失败时整个元素从 DOM 移除，不留白色空块", () => {
  render(<LoginForm onSuccess={vi.fn()} />);

  const wordmark = screen.getByRole("img", { name: "Cairn" });
  fireEvent.error(wordmark);

  // 关键是用 querySelector 而不是 queryByRole。
  //
  // queryByRole 走无障碍树，对 hidden 元素本来就返回 null，旧实现
  //（event.currentTarget.hidden = true）也能让它通过，那样这条测试什么都没守住。
  // querySelector 查的是真实 DOM：只有图片和胶囊一起移除才会返回 null。
  expect(document.querySelector(".login-wordmark")).toBeNull();
  expect(document.querySelector(".login-wordmark-chip")).toBeNull();
});

describe("字段校验", () => {
  test("空表单提交：两个字段各显示一条可读错误，且不发请求", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    render(<LoginForm onSuccess={onSuccess} />);

    await user.click(screen.getByRole("button", { name: "登录" }));

    // getByRole("alert") 而不是找 .field-error：
    // alert 是**读屏软件会播报**的那个角色，也就是"错误对用户可见"的真正含义。
    // 按 class 找只能证明某个 div 存在，证明不了用户会知道。
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(2);
    expect(alerts.map((el) => el.textContent)).toEqual(["请填写邮箱", "请填写密码"]);

    // 校验没过就不该发请求
    expect(fetch).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  test("邮箱错误说清了怎么改，而不只是说「格式错误」", async () => {
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    // getByLabelText 就是用户找输入框的方式：他看的是"邮箱"那两个字。
    await user.type(screen.getByLabelText("邮箱"), "zhangsan");
    await user.type(screen.getByLabelText("密码"), "cairn-demo-2026");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // 断言完整文案。这条断言守的是「可读错误」标准第 1 条——
    // 把文案改成"邮箱格式不正确"会让这个测试红，而那正是我们想禁止的退化。
    expect(screen.getByRole("alert")).toHaveTextContent("邮箱缺少 @，例如 name@company.com");
  });

  test("出错的字段被标记为无效，且错误文案关联到输入框", async () => {
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    const email = screen.getByLabelText("邮箱");
    await user.type(email, "zhangsan");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // aria-invalid：读屏软件靠它说"无效数据"。少了它，视觉用户看到红框，
    // 读屏用户什么都不知道。
    expect(email).toHaveAttribute("aria-invalid", "true");

    // toHaveAccessibleDescription 走的是读屏软件解析 aria-describedby 的
    // 完整过程（找到那些 id、取文本、按顺序拼接）。
    // 手写等价断言要自己实现那套逻辑，而实现里的 bug 会让断言假通过。
    expect(email).toHaveAccessibleDescription("邮箱缺少 @，例如 name@company.com");
  });

  test("密码字段同时播报常驻说明和错误——用户要两条合起来才知道怎么改", async () => {
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    const password = screen.getByLabelText("密码");

    // 没出错时只有说明
    expect(password).toHaveAccessibleDescription("至少 8 位");

    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(password, "abc123");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // 出错后两条都在："至少 8 位" 说规则，"当前 6 位" 说差多少
    expect(password).toHaveAccessibleDescription("至少 8 位 密码至少 8 位，当前 6 位");
  });

  test("提交后焦点移到第一个出错的字段", async () => {
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    // 只有密码错（邮箱填对了）→ 焦点该到密码上，不是无脑跳第一个字段
    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "abc");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // 键盘和读屏用户提交后焦点在按钮上，得反向 tab 去找哪里错了。
    // 这条断言守的是"他下一步唯一想去的地方"。
    expect(screen.getByLabelText("密码")).toHaveFocus();
  });

  test("提交前不校验：边打字边报错等于骂用户还没打完的字", async () => {
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    // 打了一个字符就算"邮箱缺少 @"，但这时候不该说
    await user.type(screen.getByLabelText("邮箱"), "d");

    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("提交过一次后改输入，错误即时消失", async () => {
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(screen.getAllByRole("alert")).toHaveLength(2);

    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");

    // 邮箱那条消失，密码那条还在。
    // 「错误的消失可以是即时的，错误的出现不行」——这条断言和上一个测试
    // 合起来才把那个非对称性钉住。只测一半的话，把校验时机改成"每次按键都校验"
    // 仍然能过这一个。
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("请填写密码");
  });
});

describe("服务端错误", () => {
  test("401 显示在表单级别，不挂在某个字段上", async () => {
    stubFetch(async () => jsonResponse({ message: "邮箱或密码不正确" }, 401));

    const user = userEvent.setup();
    const onSuccess = vi.fn();
    render(<LoginForm onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "wrongpassword");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // findBy* 会等到元素出现（内含 waitFor），因为请求是异步的
    expect(await screen.findByRole("alert")).toHaveTextContent("邮箱或密码不正确");

    // 关键断言：**两个字段都没被标记为无效。**
    //
    // 这条守的是 LoginForm 文件头那段「两类错误」。把 401 挂到密码字段上是
    // 常见的错，后果是用户盯着密码反复改，而真正错的可能是邮箱。
    // 没有这条断言，那个错误改动能悄悄通过。
    expect(screen.getByLabelText("邮箱")).not.toHaveAttribute("aria-invalid");
    expect(screen.getByLabelText("密码")).not.toHaveAttribute("aria-invalid");

    expect(onSuccess).not.toHaveBeenCalled();
  });

  test("401 不提示重试，500 提示可以再试一次", async () => {
    const user = userEvent.setup();

    // 401：密码错了，重试一万次还是错。提示重试是骗用户。
    stubFetch(async () => jsonResponse({ message: "邮箱或密码不正确" }, 401));
    const { unmount } = render(<LoginForm onSuccess={vi.fn()} />);
    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "wrongpassword");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("可以再试一次");
    unmount();

    // 500：服务器临时故障，重试有意义。
    stubFetch(async () => jsonResponse({ message: "服务器内部错误" }, 500));
    render(<LoginForm onSuccess={vi.fn()} />);
    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "cairn-demo-2026");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("可以再试一次");
  });

  test("改输入时清掉服务端错误", async () => {
    stubFetch(async () => jsonResponse({ message: "邮箱或密码不正确" }, 401));

    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "wrongpassword");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();

    await user.type(screen.getByLabelText("密码"), "x");

    // 留着它会是这个样子：用户改了密码，红字还在，他以为改完还是错的。
    // 而那条错误说的是上一次提交。
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("提交中与成功", () => {
  test("提交中按钮禁用且文案变成「登录中…」", async () => {
    // 一个不 resolve 的请求，把 pending 状态钉住好断言
    let release: (() => void) | undefined;
    stubFetch(
      () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(jsonResponse(VALID_IDENTITY));
        }),
    );

    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} />);

    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "cairn-demo-2026");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // 按 name 找按钮，找的是**用户读到的文字**。
    // 文案变了就找不到——这正是想要的：文案是用户看到的东西，属于行为。
    const submitting = await screen.findByRole("button", { name: "登录中…" });

    // toBeDisabled 而不是 hasAttribute("disabled")：断言的是"用户不能点"。
    // 只变灰不禁用的实现会被这条抓住（那种情况下用户连点会发三个请求）。
    expect(submitting).toBeDisabled();

    release?.();
  });

  test("成功后把用户交给调用方", async () => {
    const user = userEvent.setup();
    const onSuccess = vi.fn();
    render(<LoginForm onSuccess={onSuccess} />);

    await user.type(screen.getByLabelText("邮箱"), "demo@cairn.dev");
    await user.type(screen.getByLabelText("密码"), "cairn-demo-2026");
    await user.click(screen.getByRole("button", { name: "登录" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(onSuccess).toHaveBeenCalledWith(VALID_IDENTITY);

    const call = vi.mocked(fetch).mock.calls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;
    expect(new URL((call[0] as Request).url).pathname).toBe("/api/v1/login");
  });

});
