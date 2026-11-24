import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { PrimaryNavigation } from "../../src/components/PrimaryNavigation.tsx";

function mount(path: string, projectId: string | null) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <PrimaryNavigation projectId={projectId} />
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("the sidebar always lists the same project modules", () => {
  mount("/projects/p1/knowledge/sources", "p1");
  const nav = screen.getByRole("navigation", { name: "主导航" });
  expect(within(nav).getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual(["任务", "知识", "智能体"]);
  expect(within(nav).getByRole("link", { name: "知识" })).toHaveAttribute("aria-current", "page");
  expect(within(nav).getByRole("link", { name: "任务" })).toHaveAttribute("href", "/projects/p1/tasks");
  expect(within(nav).getByRole("link", { name: "智能体" })).toHaveAttribute("href", "/projects/p1/agents");
  expect(nav.querySelector(".nav-indicator")).toHaveAttribute("data-index", "1");
  expect(within(nav).queryByRole("button", { name: "设置" })).toBeNull();
});

test("without a project the modules stay in place but are disabled", () => {
  mount("/projects", null);
  const nav = screen.getByRole("navigation", { name: "主导航" });
  expect(within(nav).queryAllByRole("link")).toHaveLength(0);
  for (const label of ["任务", "知识", "智能体"]) {
    expect(within(nav).getByText(label, { selector: ".nav-label-full" }).closest(".nav-item-disabled"))
      .toHaveAttribute("aria-disabled", "true");
  }
  expect(nav.querySelector(".nav-indicator")).toBeNull();
});

test("agent management stays selected and retains knowledge conversation context", () => {
  mount("/projects/p1/agents?conversation=conversation-1", "p1");
  const nav = screen.getByRole("navigation", { name: "主导航" });
  expect(within(nav).getByRole("link", { name: "智能体" })).toHaveAttribute("aria-current", "page");
  expect(within(nav).getByRole("link", { name: "知识" })).toHaveAttribute("href", "/projects/p1/knowledge?conversation=conversation-1");
  expect(nav.querySelector(".nav-indicator")).toHaveAttribute("data-index", "2");
});

test("the desktop app adds code and a settings entry", async () => {
  const postMessage = vi.fn();
  vi.stubGlobal("chrome", { webview: { postMessage } });
  mount("/projects/p1/code", "p1");
  const nav = screen.getByRole("navigation", { name: "主导航" });
  expect(within(nav).getByRole("link", { name: "代码" })).toHaveAttribute("aria-current", "page");
  await userEvent.setup().click(within(nav).getByRole("button", { name: "设置" }));
  expect(postMessage).toHaveBeenCalledWith("cairn:settings:models");
  await userEvent.setup().click(within(nav).getByRole("link", { name: "智能体" }));
  expect(within(nav).getByRole("link", { name: "智能体" })).toHaveAttribute("aria-current", "page");
  expect(nav.querySelector(".nav-indicator")).toHaveAttribute("data-index", "3");
  expect(nav.querySelector(".nav-indicator .stone")).not.toBeNull();
});
