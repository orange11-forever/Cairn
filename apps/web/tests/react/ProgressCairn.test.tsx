import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ProgressCairn } from "../../src/components/trail/ProgressCairn.tsx";

afterEach(() => vi.useRealTimers());

test("progress describes the known task scope without celebrating historical completions", () => {
  render(<ProgressCairn tasks={[{ id: "a", status: "done" }, { id: "b", status: "todo" }]} hasMore />);
  expect(screen.getByRole("status", { name: "任务完成进度" })).toHaveTextContent("已加载任务已完成 1 / 2 项");
  expect(document.querySelector(".progress-cairn")).not.toHaveAttribute("data-adding");
});

test("only a known task becoming done adds a stone, which settles and can be undone", () => {
  vi.useFakeTimers();
  const view = render(<ProgressCairn tasks={[{ id: "a", status: "in_progress" }]} hasMore={false} />);
  view.rerender(<ProgressCairn tasks={[{ id: "a", status: "done" }]} hasMore={false} />);
  expect(screen.getByRole("status")).toHaveTextContent("已完成 1 / 1 项");
  expect(document.querySelector(".progress-cairn")).toHaveAttribute("data-adding", "true");
  act(() => vi.advanceTimersByTime(700));
  expect(document.querySelector(".progress-cairn")).not.toHaveAttribute("data-adding");
  view.rerender(<ProgressCairn tasks={[{ id: "a", status: "todo" }]} hasMore={false} />);
  expect(screen.getByRole("status")).toHaveTextContent("已完成 0 / 1 项");
  expect(document.querySelectorAll(".progress-cairn-stack [data-filled='true']")).toHaveLength(0);
});

test("loading another page updates counts without replaying completion feedback", () => {
  const view = render(<ProgressCairn tasks={[{ id: "a", status: "todo" }]} hasMore />);
  view.rerender(<ProgressCairn tasks={[{ id: "a", status: "todo" }, { id: "b", status: "done" }]} hasMore={false} />);
  expect(screen.getByRole("status")).toHaveTextContent("项目进度已完成 1 / 2 项");
  expect(document.querySelector(".progress-cairn")).not.toHaveAttribute("data-adding");
});

test("an empty project has no false completed stone", () => {
  render(<ProgressCairn tasks={[]} hasMore={false} />);
  expect(screen.getByRole("status")).toHaveTextContent("已完成 0 / 0 项");
  expect(document.querySelectorAll(".progress-cairn-stack [data-filled='true']")).toHaveLength(0);
});
