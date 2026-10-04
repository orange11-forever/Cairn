import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { KnowledgeDocumentBody } from "../../src/components/knowledge/KnowledgeDocumentBody.tsx";

test("renders Markdown structure and EOF with trusted line positions while blocking remote media and dangerous URLs", () => {
  const { container } = render(<KnowledgeDocumentBody format="markdown" content={'# Heading\n\n- first\n- second\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n<img src="https://invalid.example/x">\n\n![tracker](https://invalid.example/pixel)\n\n[bad](javascript:alert(1))\n\nEOF'} highlight={null} />);
  expect(screen.getByRole("heading", { name: "Heading" })).toHaveAttribute("data-line-start", "1");
  expect(screen.getByRole("table")).toBeVisible();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  expect(screen.getByText("EOF")).toBeVisible();
  expect(container.querySelectorAll("img,iframe,script")).toHaveLength(0);
  expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
});

test("preserves TXT whitespace and highlights only trusted citation lines", () => {
  const { container } = render(<KnowledgeDocumentBody format="text" content={'  first\n\nhit\nEOF\n'} highlight={{ chunkId: "chunk", lineStart: 3, lineEnd: 3, text: "hit", matchType: "exact" }} />);
  const hit = container.querySelector('[data-citation-hit="true"]');
  expect(hit).toHaveTextContent("hit");
  expect(hit).toHaveAttribute("data-line-start", "3");
  expect(container.querySelectorAll('[data-citation-hit="true"]')).toHaveLength(1);
  expect(container.textContent).toBe("  first\n\nhit\nEOF\n");
});

test("copies parsed fenced code and offers recovery when clipboard fails", async () => {
  const user = userEvent.setup();
  const copy = vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("denied"));
  render(<KnowledgeDocumentBody format="markdown" content={'```sh\necho hi\n```'} highlight={null} />);
  await user.click(screen.getByRole("button", { name: "复制代码" }));
  expect(copy).toHaveBeenCalledWith("echo hi\n");
  expect(await screen.findByRole("status")).toHaveTextContent("复制失败");
});
