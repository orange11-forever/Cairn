// 上传区。持有自己的本地 state：用户已选但还没提交的文件。
//
// 今天不发请求（Day 9 接受控表单、Day 10 接服务端状态）。它现在的职责是
// 成为「本地 state」的一个真实样本，好和 documentStore 那种「服务端状态」对照：
//   服务端状态：数据的真相在后端，前端只是缓存，要处理加载中/失败/陈旧
//   本地 state：真相就在这个组件里，没有加载中，没有失败，关掉就没了
// 这两种状态的生命周期和失败模式完全不同，混在一个 store 里管是常见的设计错误。
//
// 它也是 Day 8 验收「交互状态不会意外互相污染」的一个被测对象：
// 在这里选好文件后去触发文档加载，已选文件不该被清空。

import { useState } from "react";

export function UploadZone() {
  // useState 而不是模块级变量：这个状态属于这个组件的这次挂载。
  // 放模块级会让状态在组件卸载后残留，下次挂载时诡异地"记得"上次选的文件。
  const [selected, setSelected] = useState<File[]>([]);

  function handleChange(event: React.ChangeEvent<HTMLInputElement>) {
    // event.target.files 是 FileList，不是数组——没有 .map/.filter。
    // 展开成真数组（tsconfig 的 DOM.Iterable 让这一行通过类型检查）。
    setSelected(event.target.files ? [...event.target.files] : []);
  }

  return (
    <div className="upload-zone" data-selected-count={selected.length}>
      <label htmlFor="upload-input">上传文档</label>
      <input id="upload-input" name="upload" type="file" multiple onChange={handleChange} />

      {/*
        条件渲染用 `length > 0 &&` 而不是 `length &&`。
        后者在 length 为 0 时返回数字 0，而 React 会把 0 渲染成字面的 "0"——
        页面上会凭空出现一个孤零零的零。这是 JSX 里最常见的一个真实 bug。
      */}
      {selected.length > 0 && (
        <ul className="upload-selection">
          {selected.map((file) => (
            // key 用文件名：同一次选择里文件名不会重复（浏览器不允许）。
            <li key={file.name}>{file.name}</li>
          ))}
        </ul>
      )}

      {/* 今天不发请求，按钮先禁用并说明原因，胜过一个点了没反应的按钮 */}
      <button type="button" disabled title="上传功能在 Day 10 接入">
        开始上传
      </button>
    </div>
  );
}
