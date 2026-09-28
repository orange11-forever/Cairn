import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { BrandMark } from "../../src/components/BrandMark.tsx";

test("Cairn wordmark uses the concept mountain silhouette and real brand spelling", () => {
  render(<BrandMark />);
  const mark = screen.getByRole("img", { name: "Cairn" });
  expect(mark).toHaveTextContent("Cairn");
  expect(mark.querySelectorAll("svg path")).toHaveLength(3);
  expect(mark.querySelector("img")).toBeNull();
});

test("compact Cairn mountain mark remains accessible", () => {
  render(<BrandMark compact />);
  const mark = screen.getByRole("img", { name: "Cairn" });
  expect(mark.querySelectorAll("svg path")).toHaveLength(3);
  expect(mark.querySelector("span[aria-hidden='true']")).toBeNull();
});
