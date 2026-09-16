// 表单校验：纯函数层。输入是用户敲进来的值，输出是给用户看的一句话（或 null）。
//
// 不放在组件里，是为了让分支密集的规则可以脱离 DOM 单独验证。
// 校验规则是这个应用里**分支最多**的一类逻辑（空、太短、格式错、太长、字符集不对），
// 而它一旦嵌在组件的 handleSubmit 里，要问"密码 7 个字符时说什么"就得
// 起 jsdom、渲染组件、模拟输入、读 DOM。成本高到没人愿意为边界值加测试，
// 于是那些分支就一直没被验证过——而校验逻辑的 bug 全都在边界值上。
//
// 抽成纯函数后，同一个问题是三行断言，还能在 node --test 里跑（不需要 DOM）。
//
// 返回**错误文案**而不是布尔值或错误码：
//   返回 boolean  → 文案得在别处再写一次 switch，两处各自演进，很快就不一致
//   返回错误码    → 多一层间接，而当前应用没有 i18n 需求
// 文案就是这一层的产出物。真要接 i18n，改的是这一个文件（同 lib/statusText.ts）。

/** 校验结果：null 表示通过，字符串是给用户看的错误文案。 */
export type FieldError = string | null;

// ---------------------------------------------------------------------------
// 文案的硬标准（设计文档「可读错误的具体标准」第 1 条）
//
// 每条错误必须说清**怎么改**，不能只说"错了"。对照：
//   ✗ "邮箱格式不正确"        —— 用户盯着 zhangsan@company 看不出哪不对
//   ✓ "邮箱缺少 @，例如 name@company.com"
// 判据：用户读完这句话，知不知道下一步该敲什么。
// ---------------------------------------------------------------------------

/** 邮箱。 */
export function validateEmail(value: string): FieldError {
  const email = value.trim();

  if (email === "") return "请填写邮箱";

  // 刻意**不用** RFC 5322 那个正则。理由：
  // 那个正则长达几百字符、没人能读懂、且仍然判不准（合法邮箱它拒、非法邮箱它收）。
  // 邮箱是否真实存在只有通过验证邮件才能确认。
  // 前端校验的目标不是"证明邮箱有效"，是"挡住明显的手滑"，并把话说清楚。
  if (!email.includes("@")) return "邮箱缺少 @，例如 name@company.com";

  const [local, ...rest] = email.split("@");
  if (rest.length > 1) return "邮箱里有多个 @，请检查是否多打了一个";

  const domain = rest[0] ?? "";
  if (local === "") return "@ 前面缺少用户名，例如 name@company.com";
  if (domain === "") return "@ 后面缺少域名，例如 name@company.com";
  // 域名必须有点：company 不是合法域名，company.com 才是。
  // 这条能挡住企业内网习惯（很多人在内网只写用户名）造成的手滑。
  if (!domain.includes(".")) return "域名缺少后缀，例如 company.com 而不是 company";

  return null;
}

/** 密码最短长度。 */
export const PASSWORD_MIN_LENGTH = 8;

/**
 * 密码。
 *
 * 只查长度，**不查"必须含大写字母和特殊符号"**。这是有依据的决定，不是省事：
 * NIST SP 800-63B 明确建议不要强制复杂度规则，因为它的实际效果是把用户
 * 推向 `Password1!` 这类可预测的模式，而长度才是真正提高破解成本的因素。
 * 服务端仍需使用合适的密码哈希算法并防御撞库，这不属于前端复杂度校验。
 */
export function validatePassword(value: string): FieldError {
  // 密码**不 trim**：空格是合法密码字符，用户的密码可能真以空格开头。
  // 邮箱 trim 是因为复制粘贴常带空白且空白在邮箱里无意义——两个字段的处理
  // 不同不是不一致，是因为它们的语义不同。
  if (value === "") return "请填写密码";
  if (value.length < PASSWORD_MIN_LENGTH) {
    return `密码至少 ${PASSWORD_MIN_LENGTH} 位，当前 ${value.length} 位`;
  }
  return null;
}

/** 人类可读的字节数。1536 → "1.5 KB"。 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
