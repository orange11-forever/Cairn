// 一个表单字段：label + input + 错误提示。
//
// 为什么值得单独成组件：**可读错误的四条无障碍要求每个字段都要满足**，
// 而它们全是"忘了不会报错"的那种：
//   1. label 的 htmlFor 要对上 input 的 id
//   2. 出错时 aria-invalid="true"
//   3. aria-describedby 指向错误文案的 id
//   4. 错误文案带 role="alert"
//
// 手写三个字段就是这四条各写三遍，漏一处的症状是"视觉正常，读屏用户不知道自己错了"——
// 而那个症状不打开读屏软件根本发现不了。集中在一处之后，
// 它变成一件做对一次就永远对的事，而且能被一个测试守住。
//
// 这也是 Day 8「组件的合理边界」那个判断的延续：值得抽的不是"长得像"的东西，
// 是"容易做错且做错了不响"的东西。

import type { ReactNode } from "react";

interface FormFieldProps {
  /** input 的 id。label 和错误文案的关联都靠它推出来，所以必须唯一。 */
  id: string;
  label: string;
  /** 校验错误。null 表示没错。 */
  error: string | null;
  /** 常驻的说明文字，例如「至少 8 位」。和错误不同：它一直在，不是出错才出现。 */
  hint?: string;
  /**
   * 真正的 input。用 children 而不是把 type/value/onChange 全做成 props——
   * 后者等于重新实现一遍 input 的全部 API，且每加一种输入类型
   *（file、textarea、select）都要改这个组件。children 让它对输入类型完全无感。
   */
  children: ReactNode;
}

/** 错误文案的 id。组件内外都要用（input 的 aria-describedby），所以导出。 */
export function errorId(fieldId: string): string {
  return `${fieldId}-error`;
}

/** 说明文字的 id。 */
export function hintId(fieldId: string): string {
  return `${fieldId}-hint`;
}

/**
 * 给 input 的无障碍属性。调用方展开到 input 上：`{...fieldAria("email", error, true)}`
 *
 * 抽成函数而不是让 FormField 自己往 children 上挂属性：
 * 往 children 上挂属性要用 cloneElement，那是个脆弱的做法——
 * 它假设 children 是单个元素、且那个元素接受这些属性，
 * 而这两个假设都无法被类型检查，违反时只在运行时静默失效。
 * 显式展开虽然多打几个字，但"哪些属性挂到了哪个元素上"是看得见的。
 */
export function fieldAria(
  fieldId: string,
  error: string | null,
  hasHint = false,
): { "aria-invalid"?: "true"; "aria-describedby"?: string } {
  // describedby 可以指多个 id（空格分隔）。出错时同时播报说明和错误：
  // 用户听到"至少 8 位"和"当前 6 位"两条，合起来才知道该怎么改。
  const ids = [hasHint ? hintId(fieldId) : null, error !== null ? errorId(fieldId) : null].filter(
    (value): value is string => value !== null,
  );

  return {
    // undefined 而不是 "false"：aria-invalid="false" 是一个真实存在的属性值，
    // 部分读屏软件会播报它。同 Day 8 Sidebar 里 aria-current 那条。
    "aria-invalid": error !== null ? "true" : undefined,
    "aria-describedby": ids.length > 0 ? ids.join(" ") : undefined,
  };
}

export function FormField({ id, label, error, hint, children }: FormFieldProps) {
  return (
    <div className="form-field" data-invalid={error !== null ? "true" : undefined}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint !== undefined && (
        <p className="field-hint" id={hintId(id)}>
          {hint}
        </p>
      )}
      {/*
        role="alert" 让读屏在错误出现的瞬间就播报，不用等用户 tab 回那个字段。
        视觉用户看到红字是即时的，读屏用户也必须是即时的——否则他要一路 tab
        回去才发现问题，而那时候他已经点过提交了。

        条件渲染而不是渲染一个空的 <p>：role="alert" 的元素内容变化才会触发播报，
        一个常驻的空 alert 容器在某些读屏软件里会导致漏播（内容从空变成有字
        不总是被当成"新警告"）。整个元素出现/消失是最可靠的形式。
      */}
      {error !== null && (
        <p className="field-error" id={errorId(id)} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
