import { afterEach, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DesktopSettings } from "../../src/components/DesktopSettings.tsx";

afterEach(() => vi.unstubAllGlobals());

test("ordinary browsers do not expose desktop data controls", () => {
  render(<><DesktopSettings /><button type="button">工作区</button></>);
  expect(screen.queryByText("设置")).not.toBeInTheDocument();
});

test("desktop settings group native actions and close after selection or Escape", async () => {
  const postMessage = vi.fn();
  vi.stubGlobal("chrome", { webview: { postMessage } });
  const user = userEvent.setup();
  render(<DesktopSettings />);
  const trigger = screen.getByText("设置").closest("summary")!;
  await user.click(trigger);
  expect(screen.getByText("数据管理")).toBeVisible();
  expect(screen.getByText("帮助与诊断")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "模型连接" }));
  expect(postMessage).toHaveBeenCalledExactlyOnceWith("cairn:settings:models");
  expect(screen.getByRole("group")).not.toHaveAttribute("open");
  await user.click(trigger);
  await user.keyboard("{Escape}");
  expect(screen.getByRole("group")).not.toHaveAttribute("open");
  expect(trigger).toHaveFocus();
  await user.click(trigger);
  await user.click(document.body);
  expect(screen.getByRole("group")).not.toHaveAttribute("open");
});
