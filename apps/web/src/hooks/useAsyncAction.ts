// 由用户动作触发的异步请求的生命周期。
//
// 三个表单（登录、提问、上传）都要做同样四件事：
//   1. 提交中把按钮禁用，改文案（否则用户会连点，发出三个请求）
//   2. 失败时把错误显示出来，且能重试
//   3. 用户能中途取消
//   4. **组件卸载时 abort 在飞的请求**
//
// 第 4 条是抽这个 Hook 的硬理由。前三条手写三遍只是啰嗦，第 4 条手写三遍
// 就是三处可能忘——而忘了它不会有任何报错：请求照样跑完，回调照样执行，
// 只是它想更新的那个组件已经不在了。React 18 之前这会打印
// "Can't perform a React state update on an unmounted component"，
// 现在那条警告被移除了（因为它误报太多），于是这个问题变得**完全静默**。
//
// ---------------------------------------------------------------------------
// 这个 Hook 里 useEffect 只出现一次，就是那个卸载清理。这是本日的重点之一：
// 「什么时候该用 Effect」的正面样本。
//
// Effect 的正当用途是**把 React 之外的东西和 React 的生命周期对齐**：
// 订阅要退订、定时器要清、请求要取消、DOM 监听要移除。共同点是"有一个需要
// 对称释放的资源"。这里的资源是 AbortController。
//
// 反面：请求本身**不**在 Effect 里发。它由用户点提交触发，属于"响应事件"，
// 写在事件处理函数里。写成 `useEffect(() => { if (submitted) fetch() }, [submitted])`
// 是个常见的错误形状——它多引入一个 submitted 状态、多一次渲染，
// 而且"提交两次同样的内容"会因为 state 没变而不触发第二次请求。
// ---------------------------------------------------------------------------

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, toApiError } from "../api/errors.ts";

/** 请求阶段。刻意不含 success：见下面 State 的注释。 */
export type ActionPhase = "idle" | "pending" | "error";

/**
 * 用可辨识联合表达，和 documentStore 同一套思路（Day 7）。
 *
 * 没有 success 态是刻意的：这个 Hook 不持有结果。
 * 结果的归属方是调用者——AssistantPanel 要把回答 append 进消息列表，
 * LoginForm 要把 user 交给 SessionGate。如果 Hook 自己存一份结果，
 * 就有两处真相（Hook 里的 last result + 组件里的列表），
 * 而"哪个才是当前的"这个问题没有好答案。
 *
 * 所以 run() 直接返回结果，Hook 只管"过程"。
 */
export type ActionState =
  | { phase: "idle" }
  | { phase: "pending" }
  | { phase: "error"; error: ApiError };

export interface AsyncAction<Args extends unknown[], Result> {
  state: ActionState;
  /** 便利派生值。组件里写 action.pending 比 action.state.phase === "pending" 好读。 */
  pending: boolean;
  /**
   * 跑一次。成功返回结果，失败或被取消返回 undefined。
   *
   * 为什么不 throw：调用方几乎总是写在 onSubmit 里，抛异常就得每处包 try/catch，
   * 而漏掉一处就是一个 unhandled rejection（控制台红字，Day 5 的验收项之一）。
   * 返回 undefined 让调用方用 `if (result === undefined) return;` 一行处理，
   * 错误已经进了 state，UI 会自己显示。
   */
  run: (...args: Args) => Promise<Result | undefined>;
  /** 用户主动取消。回 idle，不显示错误——取消不是失败（同 documentStore 的判断）。 */
  cancel: () => void;
  /** 清掉错误。用户开始改输入时调用，让红字消失。 */
  reset: () => void;
}

/**
 * @param fn 真正干活的函数。它必须接受一个 AbortSignal 作为最后一个参数，
 *           并把它传给底层的 fetch——否则 cancel() 只会让 UI 假装停了，
 *           请求还在飞。这个约定写在类型里（signal 是必需参数），编译器会盯着。
 */
export function useAsyncAction<Args extends unknown[], Result>(
  fn: (...args: [...Args, AbortSignal]) => Promise<Result>,
): AsyncAction<Args, Result> {
  const [state, setState] = useState<ActionState>({ phase: "idle" });

  // 在飞的请求。用 ref 而不是 state，有两个独立的理由：
  //   1. 它不参与渲染。UI 不需要知道 controller 长什么样，只需要知道 pending。
  //      放 state 会白触发一次重渲染。
  //   2. 更关键：ref 的 .current 是**立即**生效的。state 的更新要等下一次渲染，
  //      而"发新请求前先取消旧的"必须在同一个事件循环里就看到最新值——
  //      用 state 的话，快速连点两次提交时第二次读到的 controller 还是 null，
  //      第一个请求就漏掉没被取消。
  const inFlight = useRef<AbortController | null>(null);

  // fn 存进 ref：调用方几乎总是传内联箭头函数（每次渲染都是新的），
  // 如果 run 的 useCallback 依赖 fn，run 就每次渲染都变，
  // 从而让依赖 run 的 Effect 反复重跑。存 ref 让 run 的身份保持稳定。
  //
  // 赋值放在 Effect 里而不是直接写 `fnRef.current = fn`：
  // 渲染函数必须是纯的，在渲染期间写外部可变值是 React 明确禁止的
  // （并发渲染下同一次渲染可能被丢弃重跑，那次写入就成了幽灵副作用）。
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });

  // 组件是否还挂着。卸载后不能再 setState——不会报错，但那是一次无意义的
  // 状态更新，且在 StrictMode 的双重挂载下会掩盖真实问题。
  const mounted = useRef(true);

  // ---- 唯一的资源清理 Effect ----
  useEffect(() => {
    // StrictMode 下 Effect 会挂载→卸载→再挂载。第二次挂载时 mounted 已被上一轮
    // 的 cleanup 置为 false，所以这里必须重新置 true。
    // 只写 cleanup 不写这一行，开发环境下所有 setState 都会被静默跳过——
    // 表现是"生产环境好的，开发环境点了没反应"，是最容易被误判成缓存问题的一类 bug。
    mounted.current = true;

    return () => {
      mounted.current = false;
      // 卸载时取消在飞的请求。省掉它的后果不是崩溃，是浪费：
      // 用户点了提交立刻切走页面，那个请求还会跑完、还会占一个连接、
      // 服务端还会做完全部工作，而结果没有任何人要。
      inFlight.current?.abort();
    };
  }, []);

  const run = useCallback(async (...args: Args): Promise<Result | undefined> => {
    // 发新请求前取消旧的。同 documentStore 里那段：防陈旧响应竞态——
    // 慢的那个后到，会用旧结果盖掉新结果。
    inFlight.current?.abort();

    const controller = new AbortController();
    inFlight.current = controller;

    setState({ phase: "pending" });

    try {
      const result = await fnRef.current(...args, controller.signal);
      // 拿到结果后仍要检查是否已被取消。
      // abort 之后 fetch 会 reject，正常情况下走不到这里；但如果响应恰好在
      // abort 的同一刻到达（竞态窗口很小但真实存在），这里会拿到一个
      // 用户已经明确放弃的结果。把它当成功处理 = 用户点了取消却还是提交了。
      if (controller.signal.aborted) return undefined;
      if (mounted.current) setState({ phase: "idle" });
      return result;
    } catch (error) {
      const apiError = toApiError(error);

      // 用户取消不是错误，回 idle 不弹红条。和 documentStore 里同一条判断——
      // 这个判断出现两次是因为它属于两个不同的状态机，不是重复代码。
      if (apiError.kind === "aborted") {
        if (mounted.current) setState({ phase: "idle" });
        return undefined;
      }

      if (mounted.current) setState({ phase: "error", error: apiError });
      return undefined;
    } finally {
      // 只在仍是自己那次请求时才清，否则会把后一次请求的 controller 误清掉
      // （和 documentStore 里那条 `if (inFlight === controller)` 是同一个理由）。
      if (inFlight.current === controller) inFlight.current = null;
    }
  }, []);

  const cancel = useCallback(() => {
    inFlight.current?.abort();
  }, []);

  const reset = useCallback(() => {
    setState({ phase: "idle" });
  }, []);

  return { state, pending: state.phase === "pending", run, cancel, reset };
}
