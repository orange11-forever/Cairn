// 上传表单的组件测试。
//
// 这里的重点是**每个文件的错误挨着那个文件显示**。选了 5 个文件其中 2 个太大时，
// 顶部一句"部分文件不符合要求"等于让用户自己去猜是哪两个——
// 而那种实现在只断言"出现了错误提示"的测试下会通过。
// 所以下面几条断言都在查错误和文件名的**位置关系**，不只是查错误存在。

import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { UploadZone } from "../../src/components/UploadZone.tsx";

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

function stubFetch(handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(handler));
}

/**
 * 造一个指定大小的 File。
 *
 * jsdom 有 File 构造函数，但 size 是从内容算出来的——要一个 15MB 的文件
 * 就得真造 15MB 的 Buffer，那会让测试变慢且吃内存。
 * 用 Object.defineProperty 直接改 size：这里在测的是"组件怎么对待 size 这个值"，
 * 文件内容和它无关。
 */
function fakeFile(name: string, size: number): File {
  const file = new File(["x"], name, { type: "application/octet-stream" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

/**
 * 建一个**不过滤 accept** 的 user 实例。
 *
 * 写测试时撞上的一个真实机制：`userEvent` 默认尊重 input 的 accept 属性，
 * 把不匹配的文件**静默丢掉**——于是 virus.exe 根本进不了组件，
 * 断言"应当报不支持 .exe"就永远失败，而失败信息是"找不到 alert"，
 * 看起来像组件忘了渲染错误。真实原因在测试工具这一侧。
 *（applyAccept 是 setup 级选项，不能传给单次 upload 调用——这一点也是踩了才知道。）
 *
 * 关掉它不是为了让测试通过而放宽，恰恰相反：它模拟的是真实场景。
 * UploadZone 里那条注释说的就是这件事——**accept 是便利，不是校验**。
 * 用户能在系统文件选择器里切到"所有文件"绕过 accept，那时 .exe 真的会进来，
 * 而 validateFiles 是唯一挡住它的东西。默认的 user 实例永远走不到那条路径上，
 * 于是那段校验代码在测试里等于不存在。
 */
const filePicker = () => userEvent.setup({ applyAccept: false });

async function selectFiles(
  user: ReturnType<typeof userEvent.setup>,
  files: File | File[],
): Promise<void> {
  await user.upload(screen.getByLabelText("上传文档"), files);
}

const okResponse = (names: string[]) =>
  jsonResponse(
    {
      accepted: names.length,
      jobs: names.map((name, index) => ({
        id: `job-${index}`,
        documentTitle: name,
        status: "pending",
      })),
    },
    201,
  );

beforeEach(() => {
  stubFetch(async () => okResponse(["需求文档.pdf"]));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("限制提前说出来", () => {
  test("常驻说明列出支持的格式和上限", () => {
    render(<UploadZone />);

    // 最好的错误提示是没有错误发生。把限制提前说清楚，
    // 用户就不会选一个 .exe 然后被拒。
    const input = screen.getByLabelText("上传文档");
    expect(input).toHaveAccessibleDescription(
      "支持 .pdf、.md、.txt、.docx，单个不超过 10.0 MB，一次最多 5 个",
    );
  });

  test("没选文件时提交按钮禁用", () => {
    render(<UploadZone />);
    // 这里禁用而 MessageInput 不禁用，差别在于能不能给出有用的理由：
    // "请先选择文件"是废话，用户看着旁边的选择框就知道。
    expect(screen.getByRole("button", { name: "开始上传" })).toBeDisabled();
  });
});

describe("选完立刻校验", () => {
  test("选到不支持的类型时立刻报错，不等提交", async () => {
    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("virus.exe", 100));

    // 选文件是**原子**输入：用户点"打开"的那一刻他的输入就完整了，
    // 这时候立刻给反馈是及时的帮助。（对比 LoginForm：打字是渐进的，中途报错是骂人。）
    expect(screen.getByRole("alert")).toHaveTextContent(
      "不支持 .exe 格式，请上传 .pdf、.md、.txt、.docx",
    );
    expect(fetch).not.toHaveBeenCalled();
  });

  test("错误显示在出错的那个文件旁边，不是堆在表单顶部", async () => {
    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, [
      fakeFile("good.pdf", 1024),
      fakeFile("huge.pdf", 15 * 1024 * 1024),
    ]);

    // 找到"huge.pdf"所在的那个列表项，在**它内部**查错误。
    // 这就是位置断言：错误堆在顶部的实现会让 within(...) 找不到它。
    const items = screen.getAllByRole("listitem");
    const hugeItem = items.find((item) => item.textContent?.includes("huge.pdf"));
    expect(hugeItem).toBeDefined();
    expect(within(hugeItem as HTMLElement).getByRole("alert")).toHaveTextContent(
      "15.0 MB 超过单个文件 10.0 MB 的上限",
    );

    // 合法的那个文件旁边不该有错误
    const goodItem = items.find((item) => item.textContent?.includes("good.pdf"));
    expect(within(goodItem as HTMLElement).queryByRole("alert")).toBeNull();
  });

  test("多个坏文件一次全报出来", async () => {
    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, [
      fakeFile("a.exe", 100),
      fakeFile("b.pdf", 20 * 1024 * 1024),
      fakeFile("c.md", 0),
    ]);

    // 只报第一条会让用户改一次、提交一次、再被拒一次，来回三轮。
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(3);
    expect(alerts[2]).toHaveTextContent("文件是空的（0 字节），请检查是否选错");
  });

  test("数量超限的错误不挂在某个文件上", async () => {
    const user = filePicker();
    render(<UploadZone />);

    const files = Array.from({ length: 6 }, (_, i) => fakeFile(`doc${i}.pdf`, 100));
    await selectFiles(user, files);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("一次最多上传 5 个文件，当前选了 6 个");

    // "一次最多 5 个"不属于任何一个文件。挂在某个文件名下面会让人以为是那个文件的错。
    const items = screen.getAllByRole("listitem");
    for (const item of items) {
      expect(within(item).queryByRole("alert")).toBeNull();
    }
  });

  test("每个文件显示大小，用户能看出是哪个超了", async () => {
    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("需求文档.pdf", 1536));

    expect(screen.getByText("1.5 KB")).toBeInTheDocument();
  });
});

describe("上传成功", () => {
  test("说的是「加入处理队列」而不是「上传成功」", async () => {
    stubFetch(async () => okResponse(["需求文档.pdf"]));

    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("需求文档.pdf", 1024));
    await user.click(screen.getByRole("button", { name: "开始上传" }));

    // 文档还没被解析和索引，现在去问答是问不出东西的。
    // 说"成功"会让用户立刻去提问然后失望——这是产品判断，不是文案偏好。
    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("已接受 1 个文件，加入处理队列：需求文档.pdf");
    expect(result).not.toHaveTextContent("上传成功");
  });

  test("发出去的是文件名和大小（今天不发二进制）", async () => {
    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("需求文档.pdf", 1024));
    await user.click(screen.getByRole("button", { name: "开始上传" }));

    await waitFor(() => expect(fetch).toHaveBeenCalled());

    // 显式判空而不是 `calls[0]!`：tsconfig 开了 noUncheckedIndexedAccess，
    // 索引访问的类型是 T | undefined。断言掉它就等于在测试里放弃了
    // 这个项目专门开启的那道检查。
    const call = vi.mocked(fetch).mock.calls[0];
    expect(call).toBeDefined();
    if (call === undefined) return;

    const [, init] = call;
    expect(init?.method).toBe("POST");
    // 这条断言守的是 api/uploads.ts 里那个坑：直接 JSON.stringify(File) 得到 `{}`，
    // 因为 File 的属性在原型上不是自有可枚举属性。必须显式取值。
    expect(JSON.parse(String(init?.body))).toEqual({
      files: [{ name: "需求文档.pdf", size: 1024 }],
    });
  });

  test("成功后清空选择，能接着传下一批", async () => {
    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("需求文档.pdf", 1024));
    await user.click(screen.getByRole("button", { name: "开始上传" }));
    await screen.findByRole("status");

    // 文件列表清空，提交按钮回到禁用
    expect(screen.queryByText("需求文档.pdf")).toBeNull();
    expect(screen.getByRole("button", { name: "开始上传" })).toBeDisabled();
  });

  test("上传中禁用输入并给出取消入口", async () => {
    let release: (() => void) | undefined;
    stubFetch(
      () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(okResponse(["需求文档.pdf"]));
        }),
    );

    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("需求文档.pdf", 1024));
    await user.click(screen.getByRole("button", { name: "开始上传" }));

    expect(await screen.findByRole("button", { name: "上传中…" })).toBeDisabled();
    expect(screen.getByLabelText("上传文档")).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消上传" })).toBeInTheDocument();

    release?.();
  });
});

describe("服务端错误", () => {
  test("413 显示在表单级别，客户端校验通过也可能撞上", async () => {
    // 客户端说 9MB 没问题，服务端说不行——两边规则不一致时会这样。
    // 这个错误必须被看见：它是"两处校验漂移了"的唯一信号。
    stubFetch(async () => jsonResponse({ message: "big.pdf 超过服务端 10MB 上限" }, 413));

    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("big.pdf", 9 * 1024 * 1024));
    await user.click(screen.getByRole("button", { name: "开始上传" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("超过服务端 10MB 上限");
    // 失败了不清空选择——用户可能想改一下再传，清空等于让他重新选一遍
    expect(screen.getByText("big.pdf")).toBeInTheDocument();
  });

  test("重新选文件时清掉上一次的服务端错误", async () => {
    stubFetch(async () => jsonResponse({ message: "服务端拒绝了" }, 415));

    const user = filePicker();
    render(<UploadZone />);

    await selectFiles(user, fakeFile("a.pdf", 100));
    await user.click(screen.getByRole("button", { name: "开始上传" }));
    await screen.findByRole("alert");

    stubFetch(async () => okResponse(["b.pdf"]));
    await selectFiles(user, fakeFile("b.pdf", 100));

    // 留着它会让用户以为新选的文件也被拒了
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  test("清空选择同时清掉 DOM 里的 value——否则再选同一个文件不触发 change", async () => {
    const user = filePicker();
    render(<UploadZone />);

    const input = screen.getByLabelText("上传文档") as HTMLInputElement;
    await selectFiles(user, fakeFile("a.pdf", 100));
    expect(input.files).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "清空选择" }));

    // 只 setSelected([]) 不清 input.value 的症状很微妙：
    // 用户再选同一个文件，onChange **不触发**（DOM 里 value 没变），
    // 看起来像"选了没反应"。这条断言直接查 DOM 是刻意的——
    // 被测的行为本身就是"DOM 状态被正确清理了"。
    expect(input.value).toBe("");
    expect(input.files).toHaveLength(0);
  });
});
