// 表单校验的纯函数测试。跑在 node --test 里，不需要 DOM。
//
// 这些用例存在的**理由**就是 lib/validation.ts 文件头写的那件事：
// 校验逻辑的 bug 全在边界值上（0 字节、正好 8 位、正好 500 字、没有扩展名），
// 而边界值只有在提问成本足够低的时候才会真的被问到。
// 这里每个 case 三行，所以它们被问了。

import test from "node:test";
import assert from "node:assert/strict";

const {
  ALLOWED_EXTENSIONS,
  MAX_FILE_BYTES,
  MAX_FILE_COUNT,
  PASSWORD_MIN_LENGTH,
  QUESTION_MAX_LENGTH,
  fileExtension,
  formatBytes,
  validateEmail,
  validateFiles,
  validatePassword,
  validateQuestion,
} = await import(new URL("../../apps/web/src/lib/validation.ts", import.meta.url));

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

// ---------------------------------------------------------------------------
// 提问
// ---------------------------------------------------------------------------

test("提问的三个边界", () => {
  assert.equal(validateQuestion(""), "请输入你的问题");
  assert.equal(validateQuestion("   "), "请输入你的问题", "纯空白等于空");
  assert.equal(validateQuestion("？"), "问题太短了，多写几个字好让我知道你想问什么");
  assert.equal(validateQuestion("值班故障怎么升级"), null);

  // 正好 500 字通过，501 字不通过
  assert.equal(validateQuestion("字".repeat(QUESTION_MAX_LENGTH)), null);
  assert.equal(
    validateQuestion("字".repeat(QUESTION_MAX_LENGTH + 1)),
    `问题最多 ${QUESTION_MAX_LENGTH} 字，当前 ${QUESTION_MAX_LENGTH + 1} 字，请精简后再问`,
  );
});

test("长度按 trim 后算", () => {
  // 用户粘贴一段带大量尾随空白的文字时，不该因为空白被判超长。
  const text = "字".repeat(QUESTION_MAX_LENGTH) + "          ";
  assert.equal(validateQuestion(text), null);
});

// ---------------------------------------------------------------------------
// 文件
// ---------------------------------------------------------------------------

test("fileExtension 处理三种没有扩展名的情况", () => {
  assert.equal(fileExtension("report.PDF"), ".pdf", "扩展名统一转小写");
  assert.equal(fileExtension("readme"), "", "没有点");
  // 点在开头：".gitignore" 的"扩展名"是整个文件名，按扩展名判断没有意义
  assert.equal(fileExtension(".gitignore"), "", "点在开头");
  assert.equal(fileExtension("a.b.c.md"), ".md", "取最后一个点之后");
});

test("formatBytes 三档", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(1023), "1023 B");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(formatBytes(10 * 1024 * 1024), "10.0 MB");
});

test("没选文件时给的是引导而不是技术错误", () => {
  const issues = validateFiles([]);
  assert.equal(issues.length, 1);
  assert.equal(issues[0].error, "请先选择要上传的文件");
  // name 为空串 = 这条问题不属于任何一个文件。
  // UploadZone 靠这个区分"整体问题"和"某个文件的问题"，渲染位置不同。
  assert.equal(issues[0].name, "");
});

test("合法文件全部通过", () => {
  const issues = validateFiles([
    { name: "需求文档.pdf", size: 1024 },
    { name: "notes.md", size: 500 },
    { name: "log.txt", size: MAX_FILE_BYTES }, // 边界：正好等于上限，通过
    { name: "spec.docx", size: 2048 },
  ]);
  assert.deepEqual(issues, []);
});

test("一次报出所有问题，不是只报第一条", () => {
  // 这是 validateFiles 返回数组而不是单个错误的整个理由：
  // 只报第一条会让用户改一次、提交一次、再被拒一次，来回三轮。
  const issues = validateFiles([
    { name: "good.pdf", size: 100 },
    { name: "virus.exe", size: 100 },
    { name: "huge.pdf", size: MAX_FILE_BYTES + 1 },
    { name: "noext", size: 100 },
  ]);

  assert.equal(issues.length, 3, "三个坏文件应当各报一条");
  assert.deepEqual(
    issues.map((issue) => issue.name).sort(),
    ["huge.pdf", "noext", "virus.exe"],
  );
});

test("每条文件错误都带上具体数字或格式", () => {
  const [tooBig] = validateFiles([{ name: "huge.pdf", size: 15 * 1024 * 1024 }]);
  // 同时说"多大"和"上限多少"。只说"文件过大"用户不知道该压到多少。
  assert.equal(tooBig.error, "15.0 MB 超过单个文件 10.0 MB 的上限");

  const [wrongType] = validateFiles([{ name: "virus.exe", size: 100 }]);
  assert.equal(wrongType.error, `不支持 .exe 格式，请上传 ${ALLOWED_EXTENSIONS.join("、")}`);

  const [noExt] = validateFiles([{ name: "noext", size: 100 }]);
  assert.match(noExt.error, /没有扩展名/);
  assert.match(noExt.error, /\.pdf/, "要列出支持的格式，否则用户不知道该改成什么");
});

test("0 字节文件单独报，不是当成合法的小文件", () => {
  // 它能通过大小上限检查，但解析器拿到它会得到空文本，
  // 结果是"上传成功但问答里搜不到"——那种沉默的失败最难排查。
  const [issue] = validateFiles([{ name: "empty.pdf", size: 0 }]);
  assert.equal(issue.error, "文件是空的（0 字节），请检查是否选错");
});

test("类型不对的文件不再报大小——一个文件不报两条错", () => {
  const issues = validateFiles([{ name: "huge.exe", size: MAX_FILE_BYTES + 1 }]);
  assert.equal(issues.length, 1);
  assert.match(issues[0].error, /不支持 \.exe/);
});

test("数量超限报成整体问题，不挂在某个文件上", () => {
  const files = Array.from({ length: MAX_FILE_COUNT + 1 }, (_, i) => ({
    name: `doc${i}.pdf`,
    size: 100,
  }));
  const issues = validateFiles(files);

  assert.equal(issues.length, 1, "文件本身都合法，只有数量问题");
  assert.equal(issues[0].name, "", "数量问题不属于任何单个文件");
  assert.equal(issues[0].error, `一次最多上传 ${MAX_FILE_COUNT} 个文件，当前选了 6 个`);
});
