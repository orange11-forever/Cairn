import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { TOAST_DURATION_MS, ToastProvider, useToast } from "../../src/components/toast/ToastContext.tsx";

let notify: ReturnType<typeof useToast>["notify"];
function Capture() {
  notify = useToast().notify;
  return null;
}
function mount() {
  render(<ToastProvider><Capture /></ToastProvider>);
  return screen.getByRole("region", { name: "操作结果" });
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

test("a success toast is announced politely and dismisses itself", () => {
  const region = mount();
  expect(region).toHaveAttribute("aria-live", "polite");
  act(() => notify({ title: "路标已放下", detail: "「整理架构说明」已完成" }));
  expect(within(region).getByText("路标已放下")).toBeInTheDocument();
  expect(within(region).getByText("「整理架构说明」已完成")).toBeInTheDocument();
  act(() => vi.advanceTimersByTime(TOAST_DURATION_MS));
  expect(within(region).queryByText("路标已放下")).toBeNull();
});

test("hovering pauses the remaining countdown instead of restarting it", () => {
  const region = mount();
  act(() => notify({ title: "项目已创建" }));
  const toast = within(region).getByText("项目已创建").closest(".toast")!;
  act(() => vi.advanceTimersByTime(1500));
  fireEvent.mouseEnter(toast);
  act(() => vi.advanceTimersByTime(TOAST_DURATION_MS + 1000));
  expect(within(region).getByText("项目已创建")).toBeInTheDocument();
  fireEvent.mouseLeave(toast);
  act(() => vi.advanceTimersByTime(TOAST_DURATION_MS - 1500));
  expect(within(region).queryByText("项目已创建")).toBeNull();
});

test("leaving a hovered toast keeps it paused while a control still has focus", () => {
  const region = mount();
  act(() => notify({ title: "项目已创建" }));
  const toast = within(region).getByText("项目已创建").closest(".toast")!;
  const close = within(region).getByRole("button", { name: "关闭提示" });
  fireEvent.mouseEnter(toast);
  fireEvent.focus(close);
  fireEvent.mouseLeave(toast);
  act(() => vi.advanceTimersByTime(TOAST_DURATION_MS + 1000));
  expect(within(region).getByText("项目已创建")).toBeInTheDocument();
  fireEvent.blur(close);
  act(() => vi.advanceTimersByTime(TOAST_DURATION_MS));
  expect(within(region).queryByText("项目已创建")).toBeNull();
});

test("at most three toasts stay visible and the close button dismisses one", () => {
  const region = mount();
  act(() => { for (const title of ["一", "二", "三", "四"]) notify({ title }); });
  expect(within(region).queryByText("一")).toBeNull();
  expect(within(region).getAllByRole("button", { name: "关闭提示" })).toHaveLength(3);
  fireEvent.click(within(region).getAllByRole("button", { name: "关闭提示" })[0]!);
  expect(within(region).queryByText("二")).toBeNull();
});

test("useToast outside the provider fails loudly", () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  expect(() => render(<Capture />)).toThrow("useToast 必须在 ToastProvider 内使用");
});
