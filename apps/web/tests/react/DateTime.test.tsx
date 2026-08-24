import { expect, test } from "vitest";

import { formatCalendarDate } from "../../src/lib/dateTime.ts";

const UTC_DATE_FORMAT = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
  timeZone: "UTC",
});

test("calendar dates preserve an RFC3339 leap second without rolling into the next day", () => {
  expect(formatCalendarDate("1990-12-31T23:59:60Z", UTC_DATE_FORMAT)).toBe(
    UTC_DATE_FORMAT.format(new Date("1990-12-31T23:59:59Z")),
  );
});

test("calendar date formatting falls back without throwing for an unexpected value", () => {
  expect(formatCalendarDate("not-a-date", UTC_DATE_FORMAT)).toBe("not-a-date");
  expect(formatCalendarDate("2026-08-10T09:30:60Z", UTC_DATE_FORMAT)).toBe(
    "2026-08-10T09:30:60Z",
  );
});
