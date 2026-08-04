// 上传区：
// 选文件 → 客户端校验（每个文件各自报错）→ POST /api/uploads → 显示处理任务。
//
// 本地 state 与服务端状态职责不同：
//   服务端状态：数据的真相在后端，前端只是缓存
//   本地 state（已选文件）：真相就在这个组件里，关掉就没了
//
// ---------------------------------------------------------------------------
// 这个表单和登录表单的一个关键差别：**file input 不能是受控组件。**
//
// `<input type="file" value={...}>` 被浏览器禁止（安全限制：网页不能凭空往
// 文件选择器里塞一个路径，否则任何页面都能偷偷上传你磁盘上的文件）。
// 所以模式是反的：DOM 持有真正的选择，我们在 onChange 时把它**复制**进 state。
//
// 后果是"清空已选文件"必须命令式地操作 DOM（input.value = ""），
// 这是本组件里 useRef 的用途——一个 React 无法用渲染表达的操作。
// 只 setSelected([]) 不清 input.value 的症状很微妙：用户再选同一个文件时
// onChange **不触发**（DOM 里的 value 没变），看起来像"选了没反应"。
// ---------------------------------------------------------------------------

import { FileUp, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";

import { uploadDocuments, type UploadResponse } from "../api/uploads.ts";
import { useAbortableAction } from "../hooks/useAbortableAction.ts";
import {
  ALLOWED_EXTENSIONS,
  MAX_FILE_BYTES,
  MAX_FILE_COUNT,
  formatBytes,
  validateFiles,
  type FileIssue,
} from "../lib/validation.ts";

export function UploadZone({ parentSignal }: { parentSignal?: AbortSignal }) {
  // useState 而不是模块级变量：这个状态属于这个组件的这次挂载。
  // 放模块级会让状态在组件卸载后残留，下次挂载时诡异地"记得"上次选的文件——
  // 登录用户切换后，下一个人不能看到前一个人选的文件名。
  const [selected, setSelected] = useState<File[]>([]);
  const [issues, setIssues] = useState<FileIssue[]>([]);
  const [result, setResult] = useState<UploadResponse | null>(null);

  // file input 的引用。用途见文件头：清空选择必须动 DOM。
  const inputRef = useRef<HTMLInputElement>(null);

  const action = useAbortableAction(uploadDocuments, parentSignal);

  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    // event.target.files 是 FileList，不是数组——没有 .map/.filter。
    // 展开成真数组（tsconfig 的 DOM.Iterable 让这一行通过类型检查）。
    const files = event.target.files ? [...event.target.files] : [];
    setSelected(files);

    // 选完立刻校验，**不等提交**。
    //
    // 这和 LoginForm 的时机判断相反，而理由是输入方式不同：
    //   打字是渐进的——"z" 还不是一个完整的邮箱，中途报错是在骂没打完的字。
    //   选文件是原子的——用户点"打开"的那一刻，他的输入就完整了。
    //     这时候立刻说"这个 .exe 不支持"是及时的帮助；
    //     等他点了提交再说，就白等了一次往返。
    // 判据：**输入是否已经完整。** 完整了就该给反馈。
    setIssues(files.length === 0 ? [] : validateFiles(files));

    // 清掉上一次的结果。留着它会出现"已接受 2 个文件"和新选的文件并列显示，
    // 用户不知道那句话说的是哪一批。
    setResult(null);
    if (action.state.phase === "error") action.reset();
  }

  /** 清空选择。既清 state 也清 DOM——见文件头那个"选了没反应"的坑。 */
  function clearSelection() {
    setSelected([]);
    setIssues([]);
    if (inputRef.current !== null) inputRef.current.value = "";
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const problems = validateFiles(selected);
    setIssues(problems);
    if (problems.length > 0) {
      // 焦点回到 file input：用户下一步要做的是重新选文件。
      inputRef.current?.focus();
      return;
    }

    const response = await action.run(selected);
    if (response === undefined) return; // 失败已进 action.state，UI 会显示

    setResult(response);
    clearSelection(); // 成功了就清空，让用户能接着传下一批
  }

  // 数量/整体级的问题（name 为空串）和单文件问题分开渲染：
  // "一次最多 5 个"不属于任何一个文件，挂在某个文件名下面会让人以为是那个文件的错。
  const generalIssues = issues.filter((issue) => issue.name === "");
  const fileIssues = issues.filter((issue) => issue.name !== "");

  return (
    <form
      aria-label="文档上传"
      className="upload-zone"
      data-selected-count={selected.length}
      onSubmit={handleSubmit}
    >
      <label htmlFor="upload-input">上传文档</label>

      <input
        id="upload-input"
        name="upload"
        type="file"
        multiple
        ref={inputRef}
        // accept 让文件选择器默认只显示这些类型。
        // 它是**便利**不是校验：用户能在选择器里切到"所有文件"绕过它，
        // 所以 validateFiles 仍然必需。把 accept 当校验用是一个常见的错。
        accept={ALLOWED_EXTENSIONS.join(",")}
        onChange={handleChange}
        disabled={action.pending}
        aria-invalid={issues.length > 0 ? "true" : undefined}
        aria-describedby="upload-hint"
      />

      {/* 常驻说明。把限制**提前**说出来，比等用户选错了再报错有用得多。
          这是"可读错误"标准之外的一条：最好的错误提示是没有错误发生。 */}
      {/*
        写成一行而不是折行：JSX 里的换行会在两个文本节点之间留一个空格，
        于是读屏播报出来是"10.0 MB， 一次最多"——多一个空格。
        肉眼看页面看不出来（HTML 会折叠连续空白），但 aria 描述里它是真实存在的，
        写测试时才发现。源码的排版会渗进无障碍文本，这是 JSX 的一个真实副作用。
      */}
      <p className="field-hint" id="upload-hint">
        支持 {ALLOWED_EXTENSIONS.join("、")}，单个不超过 {formatBytes(MAX_FILE_BYTES)}，一次最多{" "}
        {MAX_FILE_COUNT} 个
      </p>

      {/*
        条件渲染用 `length > 0 &&` 而不是 `length &&`。
        后者在 length 为 0 时返回数字 0，而 React 会把 0 渲染成字面的 "0"——
        页面上会凭空出现一个孤零零的零。这是 JSX 里最常见的一个真实 bug。
      */}
      {selected.length > 0 && (
        <ul className="upload-selection">
          {selected.map((file) => {
            const problem = fileIssues.find((issue) => issue.name === file.name);
            return (
              // key 用文件名：同一次选择里文件名不会重复（浏览器不允许）。
              <li key={file.name} data-invalid={problem !== undefined ? "true" : undefined}>
                <span className="upload-file-name">{file.name}</span>
                <span className="upload-file-size">{formatBytes(file.size)}</span>
                {/*
                  错误挨着**出错的那个文件**，不堆在表单顶部。
                  选了 5 个文件其中 2 个太大时，顶部一句"部分文件不符合要求"
                  等于让用户自己去猜是哪两个。
                */}
                {problem !== undefined && (
                  <span className="field-error" role="alert">
                    {problem.error}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {generalIssues.map((issue) => (
        <p className="field-error" role="alert" key={issue.error}>
          {issue.error}
        </p>
      ))}

      {/* 服务端错误。和客户端校验分开显示——见 LoginForm 文件头那段「两类错误」。
          这里最常见的是 413（服务端也认为太大）和 415（类型不支持），
          它们出现说明客户端校验和服务端规则不一致，是需要被看见的信号。 */}
      {action.state.phase === "error" && (
        <p className="form-error" role="alert">
          {action.state.error.message}
        </p>
      )}

      {/* 成功结果。刻意说"加入处理队列"而不是"上传成功"：
          文档还没被解析和索引，现在去问答是问不出东西的（见 api/uploads.ts 的注释）。
          说"成功"会让用户立刻去提问然后失望。 */}
      {result !== null && (
        <p className="upload-result" role="status">
          已接受 {result.accepted} 个文件，加入处理队列：
          {result.jobs.map((job) => job.documentTitle).join("、")}
        </p>
      )}

      <div className="upload-actions">
        <button type="submit" disabled={action.pending || selected.length === 0}>
          <FileUp aria-hidden="true" size={16} strokeWidth={1.8} />
          {action.pending ? "上传中…" : "开始上传"}
        </button>

        {/*
          这里禁用空提交，而 MessageInput 刻意不禁用。差别在于
          **能不能给出有用的理由**：
            提问框空着时能说"请输入你的问题"——那句话有信息。
            文件没选时说"请先选择文件"是废话，用户看着旁边的选择框就知道。
          所以这里禁用，那里给理由。原则是同一条：让用户的下一步动作最清楚。
        */}
        {selected.length > 0 && !action.pending && (
          <button type="button" className="cancel-btn" onClick={clearSelection}>
            <Trash2 aria-hidden="true" size={16} strokeWidth={1.8} />
            清空选择
          </button>
        )}

        {action.pending && (
          <button type="button" className="cancel-btn" onClick={action.cancel}>
            <X aria-hidden="true" size={16} strokeWidth={1.8} />
            取消上传
          </button>
        )}
      </div>
    </form>
  );
}
