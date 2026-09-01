import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { MascotFigure } from "../../src/components/MascotFigure.tsx";
import { WorkspaceStatus } from "../../src/components/WorkspaceStatus.tsx";

describe("MascotFigure", () => {
  test("uses the approved mascot name in its default accessible label", () => {
    render(<MascotFigure />);

    expect(screen.getByRole("img", { name: "岑宁，Cairn 知识向导" })).toBeInTheDocument();
  });

  test("renders the requested mascot variant and explicit state", () => {
    render(<MascotFigure variant="half" state="thinking" label="看板娘正在检索" />);

    expect(screen.getByRole("img", { name: "看板娘正在检索" })).toHaveAttribute(
      "data-variant",
      "half",
    );
    expect(screen.getByRole("img")).toHaveAttribute("data-state", "thinking");
    expect(screen.getByRole("status")).toHaveTextContent("思考中");
  });

  test.each(["avatar", "half"] as const)("uses the thumbnail for the %s variant", (variant) => {
    render(<MascotFigure label="看板娘" variant={variant} />);

    expect(screen.getByRole("img", { name: "看板娘" })).toHaveAttribute(
      "src",
      "/assets/brand/mascot/cairn-mascot-avatar.png",
    );
  });

  test("art-directs the full variant to the thumbnail on mobile", () => {
    const { container } = render(<MascotFigure label="看板娘" variant="full" />);

    expect(container.querySelector("source")).toHaveAttribute("media", "(max-width: 599px)");
    expect(container.querySelector("source")).toHaveAttribute(
      "srcset",
      "/assets/brand/mascot/cairn-mascot-avatar.png",
    );
    expect(screen.getByRole("img", { name: "看板娘" })).toHaveAttribute(
      "src",
      "/assets/brand/mascot/cairn-mascot-transparent.png",
    );
  });

  test("removes mobile art direction before showing the logo fallback", () => {
    const { container } = render(<MascotFigure label="看板娘" variant="full" />);

    expect(container.querySelector("source")).toBeInTheDocument();
    fireEvent.error(screen.getByRole("img", { name: "看板娘" }));

    expect(container.querySelector("source")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "看板娘" })).toHaveAttribute(
      "src",
      "/assets/brand/cairn-logo.png",
    );
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
