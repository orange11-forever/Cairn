import { expect, test } from "vitest";

import { intervalLabel, parseFeishuDocumentId } from "../../src/lib/feishuDocument.ts";

test.each([
  ["Doc123", "Doc123"],
  ["https://feishu.cn/docx/Doc123", "Doc123"],
  ["https://team.feishu.cn/docx/Doc123/?from=share#section", "Doc123"],
  ["https://feishu.cn/docx/Doc123:444", null],
  ["http://feishu.cn/docx/Doc123", null],
  ["https://feishu.cn.evil.invalid/docx/Doc123", null],
  ["https://user@feishu.cn/docx/Doc123", null],
  ["https://feishu.cn:8443/docx/Doc123", null],
  ["https://feishu.cn/wiki/Doc123", null],
  ["https://feishu.cn/sheets/Doc123", null],
  ["https://feishu.cn/docx/Doc123/extra", null],
  ["https://feishu.cn/docx/%44oc123", null],
  ["Doc-123", null],
])("parses only an exact local docx ID from %s", (input, expected) => {
  expect(parseFeishuDocumentId(input)).toBe(expected);
});

test("preserves exact nonpreset interval value", () => {
  expect(intervalLabel(600)).toBe("每 600 秒");
});
