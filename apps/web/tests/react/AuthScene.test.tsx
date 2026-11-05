import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { AuthScene } from "../../src/components/AuthScene.tsx";

test("the auth scene frames the card with a decorative trail and the guide", () => {
  const { container } = render(
    <AuthScene cardClassName="login-card" cardLabelledBy="t"><h1 id="t">登录 Cairn</h1></AuthScene>,
  );
  expect(container.querySelector("main.login-page > svg.topo-background")).toHaveAttribute("data-variant", "scene");
  expect(container.querySelector(".login-trail")).toHaveAttribute("aria-hidden", "true");
  expect(container.querySelectorAll(".login-cairn .stone")).toHaveLength(4);
  expect(screen.getByRole("img", { name: "岑宁，Cairn 知识向导" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("岑宁 · 项目向导");
  expect(screen.getByRole("region", { name: "登录 Cairn" })).toHaveClass("login-card");
});
