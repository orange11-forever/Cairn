// describeStatus 的单测。
//
// Day 8 新增。这套文案逻辑从 Day 7 起就在跑，但只被八帧浏览器脚本验证过——
// 那意味着要起 mock 服务器 + Playwright 才能问出「dropped=1 时文案对不对」。
// 成本高到没人愿意为一个边缘 case 加一帧，于是几个分支一直没被真正检查。
//
// 抽成纯函数后它变成普通的输入输出问题，这个文件就是那些一直没被问过的问题。

import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { describeStatus } from "../../src/lib/statusText.ts";
import { ApiError } from "../../src/api/errors.ts";

describe("describeStatus —— 四个 phase 的语气与文案", () => {
  it("idle 给的是引导，不是空白", () => {
    assert.deepEqual(describeStatus({ phase: "idle" }), {
      tone: "idle",
      text: "点击「加载文档」开始",
    });
  });

  it("loading", () => {
    assert.deepEqual(describeStatus({ phase: "loading" }), {
      tone: "loading",
      text: "加载中…",
    });
  });

  it("success 有数据 —— tone 是 ok，报出条数", () => {
    const docs = [{ id: "1" }, { id: "2" }, { id: "3" }];
    assert.deepEqual(describeStatus({ phase: "success", documents: docs, dropped: 0 }), {
      tone: "ok",
      text: "已加载 3 个文档",
    });
  });

  it("success 空数据 —— tone 是 empty 而非 error，因为空不是错", () => {
    assert.deepEqual(describeStatus({ phase: "success", documents: [], dropped: 0 }), {
      tone: "empty",
      text: "还没有文档，上传第一个吧",
    });
  });
});

describe("dropped 后缀 —— 沉默地少显示数据是不可接受的", () => {
  it("dropped > 0 时必须在文案里说出来", () => {
    const { text } = describeStatus({
      phase: "success",
      documents: [{ id: "1" }, { id: "2" }, { id: "3" }],
      dropped: 2,
    });
    // 用户看到"已加载 3 个"而后端实际有 5 个，他会以为文档丢了。
    // 真相是前端没看懂其中 2 条，这必须写在脸上。
    assert.equal(text, "已加载 3 个文档（2 条无法显示）");
  });

  it("dropped === 0 时不留空括号", () => {
    const { text } = describeStatus({
      phase: "success",
      documents: [{ id: "1" }],
      dropped: 0,
    });
    assert.equal(text, "已加载 1 个文档");
    assert.ok(!text.includes("（"), "dropped 为 0 时不该出现括号");
  });

  it("全部被丢掉 —— 0 条数据但 dropped > 0，走的是 empty 分支", () => {
    // 这个组合以前从没被验证过：校验层把所有数据都丢了，
    // documents 是空数组，于是命中 empty 的早返回，dropped 信息丢失。
    // 记录当前的真实行为——它是个已知的取舍，不是 bug：
    // empty 的引导文案（"上传第一个吧"）在这种情况下其实是误导，
    // 用户明明上传过。Day 12 接正式请求层时值得回来重新考虑。
    const { tone, text } = describeStatus({ phase: "success", documents: [], dropped: 4 });
    assert.equal(tone, "empty");
    assert.equal(text, "还没有文档，上传第一个吧");
  });
});

describe("errorText —— 五种 kind 给出的行动指引必须不同", () => {
  it("network 提示可重试", () => {
    const state = {
      phase: "error",
      error: new ApiError("network", "无法连接服务器，请检查网络"),
    };
    assert.deepEqual(describeStatus(state), {
      tone: "error",
      text: "无法连接服务器，请检查网络（可重试）",
    });
  });

  it("http 5xx 归因到服务器", () => {
    const state = { phase: "error", error: new ApiError("http", "boom", { status: 500 }) };
    assert.equal(describeStatus(state).text, "服务器出错（500），请稍后重试");
  });

  it("http 4xx 不说『稍后重试』—— 稍后也一样", () => {
    const state = { phase: "error", error: new ApiError("http", "boom", { status: 404 }) };
    assert.equal(describeStatus(state).text, "请求无法完成（404）");
  });

  it("timeout 和 network 的文案必须能被区分", () => {
    const timeout = describeStatus({
      phase: "error",
      error: new ApiError("timeout", "请求超过 3000ms 未响应"),
    });
    const network = describeStatus({
      phase: "error",
      error: new ApiError("network", "无法连接服务器"),
    });
    assert.equal(timeout.text, "请求超过 3000ms 未响应，网络较慢，可重试");
    assert.notEqual(timeout.text, network.text);
  });

  it("contract 刻意不提重试 —— 那是代码 bug，重试一万次结果一样", () => {
    const message = "文档数据格式不符合预期，请联系管理员";
    const state = { phase: "error", error: new ApiError("contract", message) };
    const { text } = describeStatus(state);
    assert.equal(text, message);
    assert.ok(!text.includes("重试"), "contract 错误不该引导用户重试");
  });

  it("aborted 有文案，尽管 store 正常不会让它到这儿", () => {
    const state = { phase: "error", error: new ApiError("aborted", "已取消") };
    assert.equal(describeStatus(state).text, "请求已取消");
  });
});

describe("穷尽检查 —— 未知 phase 抛错而非静默空白", () => {
  it("不在联合里的 phase 会抛错", () => {
    // 绕过类型检查模拟「将来加了新 phase 但忘了处理」。
    // 关键是它必须抛错：静默返回空白状态栏是最难发现的一类 bug。
    assert.throws(() => describeStatus({ phase: "archived" }), /未处理的状态/);
  });
});
