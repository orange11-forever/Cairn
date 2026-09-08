// 表单校验的纯函数测试。跑在 node --test 里，不需要 DOM。
//
// 这些用例存在的**理由**就是 lib/validation.ts 文件头写的那件事：
// 校验逻辑的 bug 全在边界值上（0 字节、正好 8 位、正好 500 字、没有扩展名），
// 而边界值只有在提问成本足够低的时候才会真的被问到。
// 这里每个 case 三行，所以它们被问了。

import test from "node:test";
import assert from "node:assert/strict";

const {
  PASSWORD_MIN_LENGTH,
  formatBytes,
  validateEmail,
  validatePassword,
} = await import(new URL("../../src/lib/validation.ts", import.meta.url));

// ---------------------------------------------------------------------------
// 邮箱
// ---------------------------------------------------------------------------

test("合法邮箱通过", () => {
  for (const email of [
    "demo@cairn.dev",
    "zhang.san@company.com.cn",
    "a+tag@sub.domain.io",
    // 前后空格要被 trim 掉——复制粘贴常带空白
    "  demo@cairn.dev  ",
  ]) {
    assert.equal(validateEmail(email), null, `${email} 应当通过`);
  }
});

test("每条邮箱错误都说清了怎么改", () => {
  // 断言**具体文案**而不只是"返回了非 null"。
  // 只断言非 null 的话，把文案改成"错误"仍然会通过，
  // 而"错误"这个词违反了「说清怎么改」这条验收标准——测试守不住它就等于没有标准。
  const cases = [
    ["", "请填写邮箱"],
    ["   ", "请填写邮箱"],
    ["zhangsan", "邮箱缺少 @，例如 name@company.com"],
    ["a@@b.com", "邮箱里有多个 @，请检查是否多打了一个"],
    ["@company.com", "@ 前面缺少用户名，例如 name@company.com"],
    ["zhangsan@", "@ 后面缺少域名，例如 name@company.com"],
    // 内网习惯：只写主机名不写后缀
    ["zhangsan@company", "域名缺少后缀，例如 company.com 而不是 company"],
  ];

  for (const [input, expected] of cases) {
    assert.equal(validateEmail(input), expected, `输入 ${JSON.stringify(input)}`);
  }
});

// ---------------------------------------------------------------------------
// 密码
// ---------------------------------------------------------------------------

test("密码正好达到下限时通过", () => {
  // 边界值：正好 8 位。`< MIN` 写成 `<= MIN` 会在这里被抓住，
  // 而随便挑一个 12 位的密码测永远抓不到。
  assert.equal(validatePassword("a".repeat(PASSWORD_MIN_LENGTH)), null);
  assert.equal(validatePassword("a".repeat(PASSWORD_MIN_LENGTH - 1)), "密码至少 8 位，当前 7 位");
});

test("密码错误文案带上当前位数", () => {
  // "至少 8 位"单独说不够——用户不知道自己打了几位（密码框是圆点）。
  // 带上"当前 6 位"他才知道还差多少。
  assert.equal(validatePassword("abc123"), "密码至少 8 位，当前 6 位");
  assert.equal(validatePassword(""), "请填写密码");
});

test("密码不 trim：空格是合法密码字符", () => {
  // 和邮箱相反的处理。用户的密码可能真的以空格开头/结尾，
  // trim 掉会让他"密码明明对的但登不进去"，而且永远查不出为什么。
  assert.equal(validatePassword("        "), null, "8 个空格是合法密码");
  assert.equal(validatePassword(" abc123 "), null, "8 位（含空格）应当通过");
});

test("formatBytes 三档", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1023), "1023 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(10 * 1024 * 1024), "10.0 MB");
});
