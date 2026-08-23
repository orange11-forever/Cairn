const RFC3339_LEAP_SECOND = /^(\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}):60(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/;

function parseDateTime(value: string): Date | null {
  const leapSecond = RFC3339_LEAP_SECOND.exec(value);
  const normalized = (leapSecond === null
    ? value
    : `${leapSecond[1]}:59${leapSecond[2] ?? ""}${leapSecond[3]}`)
    .replace("t", "T")
    .replace(/z$/, "Z");
  const timestamp = Date.parse(normalized);
  if (Number.isNaN(timestamp)) return null;
  // Date cannot represent :60; the preceding second preserves its calendar date.
  return new Date(timestamp);
}

export function formatCalendarDate(value: string, formatter: Intl.DateTimeFormat): string {
  const date = parseDateTime(value);
  return date === null ? value : formatter.format(date);
}
