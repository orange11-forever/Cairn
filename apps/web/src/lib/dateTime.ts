const RFC3339_LEAP_SECOND = /^(\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}):60(\.\d+)?([Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;

function isUtcMonthEndMinute(date: Date): boolean {
  const followingSecond = new Date(date.getTime() + 1_000);
  return date.getUTCHours() === 23 &&
    date.getUTCMinutes() === 59 &&
    date.getUTCSeconds() === 59 &&
    followingSecond.getUTCDate() === 1 &&
    followingSecond.getUTCHours() === 0 &&
    followingSecond.getUTCMinutes() === 0 &&
    followingSecond.getUTCSeconds() === 0;
}

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
  const date = new Date(timestamp);
  return leapSecond !== null && !isUtcMonthEndMinute(date) ? null : date;
}

export function formatCalendarDate(value: string, formatter: Intl.DateTimeFormat): string {
  const date = parseDateTime(value);
  return date === null ? value : formatter.format(date);
}
