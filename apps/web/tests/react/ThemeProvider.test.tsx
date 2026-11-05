import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ThemeControl } from "../../src/components/ThemeControl.tsx";
import { ThemeProvider, useTheme } from "../../src/theme/ThemeContext.tsx";
import { THEME_STORAGE_KEY } from "../../src/theme/theme.ts";

function installMatchMedia(initialMatches: boolean) {
  let matches = initialMatches;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      get matches() {
        return matches;
      },
      media: "(prefers-color-scheme: dark)",
      onchange: null,
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
        listeners.add(listener),
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
        listeners.delete(listener),
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => true,
      setMatches(next: boolean) {
        matches = next;
        for (const listener of listeners) listener({ matches: next } as MediaQueryListEvent);
      },
    })),
  );
}

function Probe() {
  const theme = useTheme();
  return <output>{`${theme.preference}:${theme.resolvedTheme}`}</output>;
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("dark is the default before any manual selection, regardless of system light", () => {
  installMatchMedia(false);
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByText("dark:dark")).toBeInTheDocument();
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});

test("manual theme persists and ignores later system changes", async () => {
  installMatchMedia(true);
  const user = userEvent.setup();
  render(
    <ThemeProvider>
      <ThemeControl />
      <Probe />
    </ThemeProvider>,
  );
  await user.click(screen.getByRole("radio", { name: "日间" }));
  expect(screen.getByText("light:light")).toBeInTheDocument();
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
});

test("system selection is stored explicitly and follows the system scheme", async () => {
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  installMatchMedia(false);
  const user = userEvent.setup();
  render(
    <ThemeProvider>
      <ThemeControl />
      <Probe />
    </ThemeProvider>,
  );
  await user.click(screen.getByRole("radio", { name: "跟随系统" }));
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");
  expect(screen.getByText("system:light")).toBeInTheDocument();
});

test("a stored system preference survives a reload", () => {
  localStorage.setItem(THEME_STORAGE_KEY, "system");
  installMatchMedia(true);
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByText("system:dark")).toBeInTheDocument();
});
