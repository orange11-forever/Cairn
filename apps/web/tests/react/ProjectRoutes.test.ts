import { beforeEach, expect, test } from "vitest";

import { clearLastProject, readLastProject, writeLastProject } from "../../src/app/lastProject.ts";
import { projectIdFromPath, projectModuleFromPath, projectPath } from "../../src/app/projectRoutes.ts";

beforeEach(() => localStorage.clear());

test("project paths resolve id and module only for module routes", () => {
  expect(projectIdFromPath("/projects/p%201/knowledge/sources")).toBe("p 1");
  expect(projectModuleFromPath("/projects/p1/knowledge/sources")).toBe("knowledge");
  expect(projectModuleFromPath("/projects/p1/tasks")).toBe("tasks");
  expect(projectModuleFromPath("/projects/p1/code")).toBe("code");
  expect(projectIdFromPath("/projects/new")).toBeNull();
  expect(projectIdFromPath("/projects")).toBeNull();
  expect(projectIdFromPath("/account/identities")).toBeNull();
});

test("project paths are encoded", () => {
  expect(projectPath("p 1", "tasks")).toBe("/projects/p%201/tasks");
});

test("the last project is remembered per organization", () => {
  writeLastProject(localStorage, "org-a", "p1");
  writeLastProject(localStorage, "org-b", "p2");
  expect(readLastProject(localStorage, "org-a")).toBe("p1");
  expect(localStorage.getItem("cairn-last-project:org-b")).toBe("p2");
  clearLastProject(localStorage, "org-a");
  expect(readLastProject(localStorage, "org-a")).toBeNull();
});
