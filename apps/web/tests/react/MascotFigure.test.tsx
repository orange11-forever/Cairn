import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { MascotFigure } from "../../src/components/MascotFigure.tsx";

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
});
