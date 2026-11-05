import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";

import { CairnLoader } from "../../src/components/trail/CairnLoader.tsx";
import { EmptyState } from "../../src/components/trail/EmptyState.tsx";
import { Odometer } from "../../src/components/trail/Odometer.tsx";
import { ProjectTrail } from "../../src/components/trail/ProjectTrail.tsx";
import { StatusStone } from "../../src/components/trail/Stone.tsx";
import { ThinkingStones } from "../../src/components/trail/ThinkingStones.tsx";
import { TopoBackground } from "../../src/components/trail/TopoBackground.tsx";
import { TrailBreadcrumb } from "../../src/components/trail/TrailBreadcrumb.tsx";
import { PRIORITY_CODES, PRIORITY_LABELS } from "../../src/lib/priority.ts";
import { projectKeys } from "../../src/queries/projects.ts";

afterEach(() => vi.useRealTimers());

test("status stone exposes the status label and its shape hook", () => {
  render(<StatusStone status="blocked" label="已阻塞" />);
  const stone = screen.getByRole("img", { name: "已阻塞" });
  expect(stone).toHaveAttribute("data-status", "blocked");
  expect(stone).not.toHaveAttribute("data-settling");
});

test("status stone settles only when a task becomes done, then rests", () => {
  vi.useFakeTimers();
  const { rerender } = render(<StatusStone status="in_progress" label="进行中" />);
  rerender(<StatusStone status="done" label="已完成" />);
  const stone = screen.getByRole("img", { name: "已完成" });
  expect(stone).toHaveAttribute("data-settling", "true");
  act(() => vi.advanceTimersByTime(700));
  expect(stone).not.toHaveAttribute("data-settling");
});

test("a task that is already done does not replay the settle animation", () => {
  render(<StatusStone status="done" label="已完成" />);
  expect(screen.getByRole("img", { name: "已完成" })).not.toHaveAttribute("data-settling");
});

test("cairn loader is a live status with readable text", () => {
  render(<CairnLoader label="正在读取任务" />);
  expect(screen.getByRole("status")).toHaveTextContent("正在读取任务");
});

test("thinking stones keep the surrounding status text", () => {
  render(<p role="status"><ThinkingStones>正在查找资料并生成回答…</ThinkingStones></p>);
  expect(screen.getByRole("status")).toHaveTextContent("正在查找资料并生成回答…");
});

test("odometer reads as the number and positions each reel", () => {
  const { container } = render(<Odometer value={12} />);
  expect(screen.getByText("12")).toHaveClass("visually-hidden");
  expect(container.textContent).toBe("12");
  expect([...container.querySelectorAll(".odometer-digit")].map((node) => node.getAttribute("data-digit"))).toEqual(["1", "2"]);
});

test("priority codes map to P0-P3 with Chinese labels", () => {
  expect(PRIORITY_CODES).toEqual({ critical: "P0", high: "P1", medium: "P2", low: "P3" });
  expect(PRIORITY_LABELS.high).toBe("高优先级");
});

test("topo background is decorative", () => {
  const { container } = render(<TopoBackground variant="scene" />);
  const svg = container.querySelector("svg.topo-background");
  expect(svg).toHaveAttribute("aria-hidden", "true");
  expect(svg).toHaveAttribute("data-variant", "scene");
  expect(svg).not.toHaveAttribute("data-draw");
});

test("trail breadcrumb links earlier stops and marks the current one", () => {
  render(
    <MemoryRouter initialEntries={["/projects/p1/knowledge/sources"]}>
      <TrailBreadcrumb items={[
        { label: "Cairn 工作空间", to: "/projects/p1/tasks" },
        { label: "知识", to: "/projects/p1/knowledge" },
        { label: "来源与同步" },
      ]} />
    </MemoryRouter>,
  );
  const nav = screen.getByRole("navigation", { name: "当前位置" });
  expect(screen.getByRole("link", { name: "Cairn 工作空间" })).toHaveAttribute("href", "/projects/p1/tasks");
  expect(screen.getByRole("link", { name: "知识" })).toHaveAttribute("href", "/projects/p1/knowledge");
  expect(screen.getByText("来源与同步")).toHaveAttribute("aria-current", "page");
  expect(nav.querySelectorAll(".trail-path")).toHaveLength(2);
});

test("empty state draws its contours only the first time in a page load", () => {
  const first = render(<EmptyState drawKey="test-empty" title="这里还没有路标" description="放下第一块石头" />);
  expect(screen.getByRole("heading", { name: "这里还没有路标" })).toBeInTheDocument();
  expect(first.container.querySelector(".topo-background")).toHaveAttribute("data-draw", "true");
  first.unmount();
  const second = render(<EmptyState drawKey="test-empty" title="这里还没有路标" description="放下第一块石头" />);
  expect(second.container.querySelector(".topo-background")).not.toHaveAttribute("data-draw");
});

test("project trail prefixes the project name once it is known", () => {
  const projectId = "00000000-0000-4000-8000-000000004001";
  const queryClient = new QueryClient();
  queryClient.setQueryData(projectKeys.detail("org", projectId), {
    id: projectId, revision: 1, name: "知识库迁移", description: null,
    createdAt: "2026-08-01T08:00:00Z", updatedAt: "2026-08-01T08:00:00Z",
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/projects/${projectId}/code`]}>
        <ProjectTrail organizationId="org" projectId={projectId} trail={[{ label: "代码" }]} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByRole("link", { name: "知识库迁移" })).toHaveAttribute("href", `/projects/${projectId}/tasks`);
  expect(screen.getByText("代码")).toHaveAttribute("aria-current", "page");
});

test("project trail renders nothing until the page has loaded the project", () => {
  const { container } = render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ProjectTrail organizationId="org" projectId="p1" trail={[{ label: "代码" }]} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(container).toBeEmptyDOMElement();
});
