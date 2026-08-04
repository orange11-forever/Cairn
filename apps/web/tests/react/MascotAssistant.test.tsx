import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { MascotAssistant } from "../../src/components/MascotAssistant.tsx";

function renderAssistant(page: "documents" | "ask" = "documents") {
  return render(
    <MemoryRouter>
      <MascotAssistant page={page} />
    </MemoryRouter>,
  );
}

describe("MascotAssistant", () => {
  test("opens with document context and closes with Escape", async () => {
    const user = userEvent.setup();
    renderAssistant();

    const trigger = screen.getByRole("button", { name: "打开看板娘助手" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("知识文档");
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "看板娘助手" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  test("uses question context and closes after an outside click", async () => {
    const user = userEvent.setup();
    renderAssistant("ask");

    await user.click(screen.getByRole("button", { name: "打开看板娘助手" }));
    expect(screen.getByRole("dialog", { name: "看板娘助手" })).toHaveTextContent("知识问答");

    await user.click(document.body);
    expect(screen.queryByRole("dialog", { name: "看板娘助手" })).toBeNull();
  });
});
