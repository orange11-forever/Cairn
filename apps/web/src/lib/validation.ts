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

/** 提问的长度上限。给个具体数字，UI 才能显示剩余字数。 */
export const QUESTION_MAX_LENGTH = 500;

/** 提问。 */
export function validateQuestion(value: string): FieldError {
  const question = value.trim();

  if (question === "") return "请输入你的问题";
  // 太短的问题检索不出东西。给出的下限很低（3 字），只挡住误触和纯标点。
  if (question.length < 3) return "问题太短了，多写几个字好让我知道你想问什么";
  if (question.length > QUESTION_MAX_LENGTH) {
    return `问题最多 ${QUESTION_MAX_LENGTH} 字，当前 ${question.length} 字，请精简后再问`;
  }

  return null;
}

// ---------------------------------------------------------------------------
// 文件校验
// ---------------------------------------------------------------------------

/** 单文件大小上限（字节）。10 MB。 */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

/** 一次最多选几个文件。 */
export const MAX_FILE_COUNT = 5;

/** 允许的扩展名。小写，带点。 */
export const ALLOWED_EXTENSIONS = [".pdf", ".md", ".txt", ".docx"] as const;

/**
 * 校验只依赖 name 和 size，不依赖 File。
 *
 * 这是刻意的结构类型（duck typing）：浏览器里传进来的是真 File（它有这两个字段），
 * 测试里传 `{ name: "a.pdf", size: 100 }` 就行。
 * 如果签名写成 `(files: File[])`，这套逻辑就只能在有 File 构造函数的环境里被测——
 * 而它一行 DOM 都没碰，那个限制纯属签名过窄自己招来的。
 */
export interface FileLike {
  name: string;
  size: number;
}

/** 一个文件的校验结果。 */
export interface FileIssue {
  name: string;
  error: string;
}

/** 人类可读的字节数。1536 → "1.5 KB"。 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 取小写扩展名，含点。没有扩展名返回空串。 */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  // dot <= 0 覆盖两种情况：没有点（-1），以及 ".gitignore" 这种点在开头（0）——
  // 后者的"扩展名"是整个文件名，按扩展名判断没有意义，当作无扩展名处理。
  if (dot <= 0) return "";
  return name.slice(dot).toLowerCase();
}

/**
 * 逐个文件校验，返回所有问题。
 *
 * 返回**数组**而不是第一条错误：用户一次选了 5 个文件，其中 3 个有问题，
 * 只报第一个会让他改一次、提交一次、再被拒一次，来回三轮。
 * 一次全说清楚，用户一次就能改对。这条和列表校验的 parseList 是同一个思路——
 * 别让用户替系统的沉默买单。
 *
 * 数量超限单独返回一条不带文件名的问题（name 为空串）：它不属于任何一个文件。
 */
export function validateFiles(files: FileLike[]): FileIssue[] {
  const issues: FileIssue[] = [];

  if (files.length === 0) {
    return [{ name: "", error: "请先选择要上传的文件" }];
  }

  if (files.length > MAX_FILE_COUNT) {
    issues.push({
      name: "",
      error: `一次最多上传 ${MAX_FILE_COUNT} 个文件，当前选了 ${files.length} 个`,
    });
  }

  for (const file of files) {
    const ext = fileExtension(file.name);

    if (ext === "") {
      issues.push({
        name: file.name,
        error: `没有扩展名，无法判断文件类型（支持 ${ALLOWED_EXTENSIONS.join("、")}）`,
      });
      continue; // 类型都不认，就不用再报大小了——一个文件报两条错只会让人烦
    }

    // includes 在 readonly 元组上要收一下类型：ALLOWED_EXTENSIONS 的元素类型是
    // 那四个字面量的联合，而 ext 是 string，直接 includes 过不了类型检查。
    if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
      issues.push({
        name: file.name,
        error: `不支持 ${ext} 格式，请上传 ${ALLOWED_EXTENSIONS.join("、")}`,
      });
      continue;
    }

    // 0 字节文件单独报。它能通过大小上限检查，但解析器拿到它会得到空文本，
    // 结果是"上传成功但问答里搜不到"——那种沉默的失败最难排查。
    if (file.size === 0) {
      issues.push({ name: file.name, error: "文件是空的（0 字节），请检查是否选错" });
      continue;
    }

    if (file.size > MAX_FILE_BYTES) {
      issues.push({
        name: file.name,
        // 同时说出"多大"和"上限多少"。只说"文件过大"用户不知道该压到多少。
        error: `${formatBytes(file.size)} 超过单个文件 ${formatBytes(MAX_FILE_BYTES)} 的上限`,
      });
    }
  }

  return issues;
}
