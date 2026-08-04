// 前端环境变量的类型声明。
//
// 为什么要单独写而不是在 tsconfig 里加 `"types": ["vite/client"]`：
//
// `vite/client` 把 `import.meta.env` 声明成一个索引签名（任意 key 都返回 string），
// 于是打错名字不会报错——写 `VITE_API_UEL` 会安静地得到 undefined，
// 然后 `?? "http://localhost:8787"` 兜底生效，看起来一切正常，
// 而实际上你配的那个后端地址从来没被用上。
//
// 显式列出每一个变量之后，打错名字是**编译错误**，而且有自动补全。
// **类型的价值在于它能拒绝什么，不在于它能通过什么。**
//
// ---------------------------------------------------------------------------
// 一条安全规则：**只有 `VITE_` 前缀的变量会被 Vite 注入前端产物。**
//
// 这是 Vite 刻意的设计——否则服务器上的 `DATABASE_PASSWORD`、`LLM_API_KEY`
// 之类会被打进 JS 文件，任何打开浏览器的人都能看到。
//
// 反过来说：**能出现在下面这个接口里的值，都等于公开的。**
// 别把任何密钥、token、内部地址放进 VITE_ 变量。需要保密的东西必须由后端持有，
// 前端通过 API 间接使用它。
// ---------------------------------------------------------------------------

interface ImportMetaEnv {
  /** Vite 编译期常量；开发服务器为 true，生产构建为 false。 */
  readonly DEV: boolean;

  /**
 * Identity API base URL, for example `https://identity.example.com`.
 *
 * Defaults to the local FastAPI identity service when omitted.
 */
  readonly VITE_IDENTITY_API_URL?: string;
  /** Mock documents, uploads, and conversations API base URL. */
  readonly VITE_MOCK_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
