import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { MascotFigure } from "../../src/components/MascotFigure.tsx";
import { WorkspaceStatus } from "../../src/components/WorkspaceStatus.tsx";

describe("MascotFigure", () => {
  test("renders the requested mascot variant and explicit state", () => {
    render(<MascotFigure variant="half" state="thinking" label="看板娘正在检索" />);

    expect(screen.getByRole("img", { name: "看板娘正在检索" })).toHaveAttribute(
      "data-variant",
      "half",
    );
    expect(screen.getByRole("img")).toHaveAttribute("data-state", "thinking");
    expect(screen.getByRole("status")).toHaveTextContent("思考中");
  });

  test("falls back to the Cairn mark when the mascot asset fails", () => {
    render(<MascotFigure label="看板娘" />);

    fireEvent.error(screen.getByRole("img", { name: "看板娘" }));

    expect(screen.getByRole("img", { name: "看板娘" })).toHaveAttribute(
      "src",
      "/assets/brand/cairn-logo.png",
    );
  });

  test("keeps an accessible non-image fallback after the Cairn mark also fails", () => {
    render(<MascotFigure label="看板娘" />);

    fireEvent.error(screen.getByRole("img", { name: "看板娘" }));
    fireEvent.error(screen.getByRole("img", { name: "看板娘" }));

    expect(screen.getByRole("img", { name: "看板娘" })).not.toHaveAttribute("src");
    expect(screen.getByRole("status")).toHaveTextContent("准备中");
  });
});

describe("WorkspaceStatus", () => {
  test.each([
    ["loading", "attention", "thinking"],
    ["error", "thinking", "attention"],
  ] as const)("uses its %s state instead of the mascot %s state", (state, mascotState, expected) => {
    render(
      <WorkspaceStatus
        description="状态说明"
        mascot={{ label: "看板娘", state: mascotState }}
        state={state}
        title="工作区状态"
      />,
    );

    expect(screen.getByRole("img", { name: "看板娘" })).toHaveAttribute("data-state", expected);
  });
});
