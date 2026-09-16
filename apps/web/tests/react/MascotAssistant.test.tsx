import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { MascotAssistant } from "../../src/components/MascotAssistant.tsx";

function renderAssistant(page: "projects" | "knowledge" = "projects") {
  return render(
    <MemoryRouter>
      <MascotAssistant page={page} />
    </MemoryRouter>,
  );
}

describe("MascotAssistant", () => {
  test("opens with project context and closes with Escape", async () => {
    const user = userEvent.setup();
    renderAssistant();

    const trigger = screen.getByRole("button", { name: "打开岑宁助手" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(within(trigger).getByRole("img", { name: "岑宁，Cairn 知识向导" })).toHaveAttribute(
      "data-variant",
      "avatar",
    );

    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "岑宁助手" });
    expect(dialog).toHaveTextContent("项目任务助手");
    expect(within(dialog).getByRole("img", { name: "岑宁，Cairn 助手" })).toHaveAttribute(
      "data-variant",
      "half",
    );
    expect(within(dialog).getByRole("img", { name: "岑宁，Cairn 助手" })).toHaveAttribute(
      "src",
      "/assets/brand/mascot/cairn-mascot-chibi.png",
    );
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "岑宁助手" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  test("uses project knowledge context and closes after an outside click", async () => {
    const user = userEvent.setup();
    renderAssistant("knowledge");

    await user.click(screen.getByRole("button", { name: "打开岑宁助手" }));
    expect(screen.getByRole("dialog", { name: "岑宁助手" })).toHaveTextContent("项目知识助手");

    await user.click(document.body);
    expect(screen.queryByRole("dialog", { name: "岑宁助手" })).toBeNull();
  });
});
