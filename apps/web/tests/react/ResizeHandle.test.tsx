import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { ResizeHandle } from "../../src/components/ResizeHandle.tsx";

afterEach(() => vi.restoreAllMocks());

function mount(axis: "x" | "y" = "x", direction: 1 | -1 = 1) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const size = Number.parseFloat(this.style.width || this.style.height) || 600;
    return { width: size, height: size, left: 0, top: 0, right: size, bottom: size, x: 0, y: 0, toJSON() {} };
  });
  function Workspace() {
    const pane = useRef<HTMLDivElement>(null);
    const [size, setSize] = useState(200);
    return <div><div ref={pane} style={{ width: size, height: size }}><input aria-label="编辑草稿" defaultValue="保留的草稿" /></div><ResizeHandle axis={axis} direction={direction} label="调整面板" pane={pane} min={120} max={() => 360} onResize={setSize} onReset={() => setSize(200)} /><output>{size}</output></div>;
  }
  const view = render(<Workspace />);
  const handle = screen.getByRole("separator", { name: "调整面板" });
  Object.assign(handle, { setPointerCapture: vi.fn(), hasPointerCapture: () => true, releasePointerCapture: vi.fn() });
  return { ...view, handle };
}

function pointer(handle: HTMLElement, type: string, x: number, y = 0) {
  const event = new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: y });
  Object.defineProperties(event, { pointerId: { value: 1 }, isPrimary: { value: true } });
  fireEvent(handle, event);
}

test("keyboard resizing is bounded and resetting preserves the editor instance", () => {
  const { handle } = mount();
  const input = screen.getByLabelText("编辑草稿");
  expect(handle).toHaveAttribute("aria-orientation", "vertical");
  fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(screen.getByRole("status")).toHaveTextContent("210");
  fireEvent.keyDown(handle, { key: "End" });
  expect(handle).toHaveAttribute("aria-valuenow", "360");
  fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
  expect(screen.getByRole("status")).toHaveTextContent("360");
  fireEvent.keyDown(handle, { key: "Home" });
  expect(screen.getByRole("status")).toHaveTextContent("120");
  fireEvent.doubleClick(handle);
  expect(screen.getByRole("status")).toHaveTextContent("200");
  expect(screen.getByLabelText("编辑草稿")).toBe(input);
});

test("dragging a trailing pane grows it in the opposite direction and releases capture", () => {
  const { handle } = mount("x", -1);
  pointer(handle, "pointerdown", 400);
  pointer(handle, "pointermove", 350);
  expect(screen.getByRole("status")).toHaveTextContent("250");
  pointer(handle, "pointermove", 100);
  expect(screen.getByRole("status")).toHaveTextContent("360");
  pointer(handle, "pointerup", 100);
  expect(document.documentElement).not.toHaveAttribute("data-panel-resize-axis");
  expect(handle.releasePointerCapture).toHaveBeenCalledWith(1);
});

test("vertical resizing and unmounting clean up the global drag state", () => {
  const { handle, unmount } = mount("y");
  expect(handle).toHaveAttribute("aria-orientation", "horizontal");
  pointer(handle, "pointerdown", 0, 100);
  pointer(handle, "pointermove", 0, 140);
  expect(screen.getByRole("status")).toHaveTextContent("240");
  unmount();
  expect(document.documentElement).not.toHaveAttribute("data-panel-resize-axis");
});
