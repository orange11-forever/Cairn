import { act, render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

function motion(reduced: boolean) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query.includes("prefers-reduced-motion") && reduced,
    media: query, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
}

async function load() {
  vi.resetModules();
  return import("../../src/components/StartupIntro.tsx");
}

beforeEach(() => { vi.useFakeTimers(); motion(false); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

test("fast restoration finishes the sequence before releasing the destination", async () => {
  const { StartupIntro, INTRO_MIN_MS, INTRO_EXIT_MS } = await load();
  const view = render(<StrictMode><StartupIntro restoring><button>进入项目</button></StartupIntro></StrictMode>);
  view.rerender(<StrictMode><StartupIntro restoring={false}><button>进入项目</button></StartupIntro></StrictMode>);
  const intro = document.querySelector(".startup-intro")!;
  expect(intro).toHaveAttribute("aria-hidden", "true");
  expect(document.querySelector(".startup-content")).toHaveAttribute("inert");
  expect(screen.queryByText("进入项目")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
  act(() => vi.advanceTimersByTime(INTRO_MIN_MS - 1));
  expect(intro).toHaveAttribute("data-phase", "play");
  act(() => vi.advanceTimersByTime(1));
  expect(intro).toHaveAttribute("data-phase", "exit");
  act(() => vi.advanceTimersByTime(INTRO_EXIT_MS));
  expect(document.querySelector(".startup-intro")).toBeNull();
  expect(document.querySelector(".startup-content")).not.toHaveAttribute("inert");
  expect(screen.getByRole("button", { name: "进入项目" })).toBeVisible();
});

test("slow restoration holds the assembled logo until the session settles", async () => {
  const { StartupIntro, INTRO_MIN_MS } = await load();
  const view = render(<StartupIntro restoring />);
  act(() => vi.advanceTimersByTime(INTRO_MIN_MS * 3));
  expect(document.querySelector(".startup-intro")).toHaveAttribute("data-phase", "play");
  view.rerender(<StartupIntro restoring={false} />);
  expect(document.querySelector(".startup-intro")).toHaveAttribute("data-phase", "exit");
});

test("a later restore or route remount cannot replay the intro", async () => {
  const { StartupIntro, INTRO_MIN_MS, INTRO_EXIT_MS } = await load();
  const view = render(<StartupIntro restoring />);
  view.rerender(<StartupIntro restoring={false} />);
  act(() => vi.advanceTimersByTime(INTRO_MIN_MS));
  act(() => vi.advanceTimersByTime(INTRO_EXIT_MS));
  view.rerender(<StartupIntro restoring />);
  expect(document.querySelector(".startup-intro")).toBeNull();
  view.unmount();
  render(<StartupIntro restoring />);
  expect(document.querySelector(".startup-intro")).toBeNull();
});

test("an already restored initial session never starts an intro later", async () => {
  const { StartupIntro } = await load();
  const view = render(<StartupIntro restoring={false} />);
  view.unmount();
  render(<StartupIntro restoring />);
  expect(document.querySelector(".startup-intro")).toBeNull();
});

test("reduced motion skips the minimum wait and keeps restoration readable", async () => {
  motion(true);
  const { StartupIntro, INTRO_EXIT_MS } = await load();
  const view = render(<StartupIntro restoring />);
  expect(screen.getByRole("status")).toHaveTextContent("正在恢复会话…");
  view.rerender(<StartupIntro restoring={false} />);
  expect(document.querySelector(".startup-intro")).toHaveAttribute("data-reduced", "true");
  expect(document.querySelector(".startup-intro")).toHaveAttribute("data-phase", "exit");
  act(() => vi.advanceTimersByTime(INTRO_EXIT_MS));
  expect(document.querySelector(".startup-intro")).toBeNull();
});
